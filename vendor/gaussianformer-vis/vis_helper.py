#!/usr/bin/env python3
"""
vis_helper.py - Backend helper for GaussianFormer visualization extension.
Handles scanning directories, loading point clouds, and loading Gaussian features.
"""

import argparse
import base64
import json
import os
import pickle
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Label definitions
# ---------------------------------------------------------------------------

LABEL_COLORS: Dict[int, Tuple[float, float, float]] = {
    0: (1, 0, 0),
    1: (0, 1, 0),
    2: (0, 0, 1),
    3: (1, 1, 0),
    4: (1, 0, 1),
    5: (0, 1, 1),
    6: (0.5, 0.5, 0.5),
    7: (1, 0.5, 0),
    8: (0.5, 0, 1),
    9: (0, 0.5, 0),
    10: (1, 0, 0.5),
    11: (0.5, 1, 0),
    12: (0, 0.5, 1),
    13: (0.5, 0, 0.5),
    14: (1, 0.5, 0.5),
    15: (0.5, 1, 0.5),
    16: (0.5, 0.5, 1),
    17: (1, 1, 0.5),
    18: (0.8, 0.2, 0.2),
    19: (0.2, 0.8, 0.2),
    20: (0.2, 0.2, 0.8),
    21: (0.8, 0.8, 0.2),
    22: (0.8, 0.2, 0.8),
    23: (0.2, 0.8, 0.8),
    24: (0.3, 0.3, 0.3),
    25: (0.7, 0.3, 0),
    26: (0, 0, 0),
}

LABEL_NAMES: Dict[int, str] = {
    0: "ignore",
    1: "asphalt",
    2: "cement",
    3: "epoxy_floor",
    4: "brick_road",
    5: "gravel",
    6: "cobbles",
    7: "grass",
    8: "dirt",
    9: "hard_sand",
    10: "soft_sand",
    11: "water",
    12: "ice",
    13: "snow",
    14: "other_surface",
    15: "road_noise",
    16: "bumper",
    17: "manhole_cover",
    18: "steel_plate",
    19: "drain",
    20: "road_beam",
    21: "railway",
    22: "step",
    23: "other_bump",
    24: "moving_obstacle",
    25: "fixed_obstacle",
    26: "ignore",
}

DEFAULT_IGNORE = {26}

# Must match z_scale branch in _encode_point_cloud (UI label says ×10, factor is 5)
Z_SCALE_FACTOR = 5.0

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _natural_sort_key(s: str) -> List[Any]:
    """Key function for natural (human) sort order."""
    parts = re.split(r"(\d+)", s)
    result: List[Any] = []
    for part in parts:
        if part.isdigit():
            result.append(int(part))
        else:
            result.append(part.lower())
    return result


def _encode_f32(arr: np.ndarray) -> str:
    """Encode a numpy array as a base64 string of float32 bytes."""
    return base64.b64encode(arr.astype(np.float32).tobytes()).decode("ascii")


def _encode_f16(arr: np.ndarray) -> str:
    """Encode a numpy array as a base64 string of float16 bytes (2x smaller than f32)."""
    return base64.b64encode(arr.astype(np.float16).tobytes()).decode("ascii")


def _encode_u8(arr: np.ndarray) -> str:
    """Encode a numpy array as a base64 string of uint8 bytes (4x smaller than int32)."""
    return base64.b64encode(arr.astype(np.uint8).tobytes()).decode("ascii")


def _load_pcd_bin_npy(fp: str) -> np.ndarray:
    """
    Load a point cloud file.  Accepts .npy, .npz, or raw .bin formats.
    Returns array of shape (N, 4+) with columns [x, y, z, label/intensity, ...].
    """
    if fp.endswith(".npz"):
        data = np.load(fp, allow_pickle=True)
        key = list(data.keys())[0]
        arr = data[key]
    elif fp.endswith(".npy"):
        arr = np.load(fp, allow_pickle=True)
    else:
        # raw binary float32
        arr = np.fromfile(fp, dtype=np.float32).reshape(-1, 4)

    arr = np.atleast_2d(arr).astype(np.float32)

    # ensure at least 4 columns (pad with zero label if necessary)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    if arr.shape[1] < 3:
        raise ValueError(f"Point cloud file has fewer than 3 columns: {fp}")
    if arr.shape[1] == 3:
        arr = np.concatenate([arr, np.zeros((arr.shape[0], 1), dtype=np.float32)], axis=1)

    return arr


def _build_label_counts(labels: np.ndarray) -> List[Dict[str, Any]]:
    """Per-class counts sorted by count descending."""
    if labels is None or len(labels) == 0:
        return []
    unique, counts = np.unique(labels.astype(np.int32), return_counts=True)
    order = np.argsort(-counts)
    out: List[Dict[str, Any]] = []
    for i in order:
        lbl = int(unique[i])
        out.append({
            "id": lbl,
            "name": LABEL_NAMES.get(lbl, f"label_{lbl}"),
            "count": int(counts[i]),
        })
    return out


def _build_label_info(labels: np.ndarray) -> str:
    """Build a human-readable label summary string."""
    parts = [f"{c['name']}({c['count']})" for c in _build_label_counts(labels)]
    return ", ".join(parts)


def _build_intensity_label_info(intensities: np.ndarray) -> str:
    """Build a human-readable intensity summary string."""
    if len(intensities) == 0:
        return "intensity: N/A"
    return (
        f"intensity: min={float(intensities.min()):.3f}, "
        f"max={float(intensities.max()):.3f}, "
        f"mean={float(intensities.mean()):.3f}"
    )


# Z offsets for traj_transformer left-view layers (match qt5visualizetool_v6.py)
TRAJ_TRANSFORMER_Z_OFFSETS = {
    "gt": -0.10,
    "pred": 0.10,
}


def _encode_traj_transformer_cloud(
    fp: str,
    z_offset: float = 0.0,
    z_scale: bool = False,
    ignore_labels: Optional[set] = None,
) -> Optional[Dict[str, Any]]:
    """Load `{base}_traj_{gt|pred}.npy` and encode like a semantic point cloud.

    File format (eval.py / v6): [N, >=4] = x, y, z, label, (optional valid_mask...)
    """
    if not fp or not os.path.isfile(fp):
        return None
    try:
        data = np.load(fp, allow_pickle=True)
    except Exception as e:
        sys.stderr.write(f"Warning: traj transformer load failed ({fp}): {e}\n")
        return None

    data = np.asarray(data, dtype=np.float32)
    if data.ndim != 2 or data.shape[1] < 4 or data.shape[0] == 0:
        return None

    xyz = np.ascontiguousarray(data[:, :3], dtype=np.float32)
    labels = np.rint(data[:, 3]).astype(np.int32)

    ignore_set = set(ignore_labels) if ignore_labels else set(DEFAULT_IGNORE)
    ignore_set.add(26)
    mask = np.ones(len(labels), dtype=bool)
    for lbl in ignore_set:
        mask &= labels != lbl
    mask &= np.isfinite(xyz).all(axis=1)
    xyz = xyz[mask]
    labels = labels[mask]
    if len(xyz) == 0:
        return None

    # Match v6: optional Z stretch around min_z, then apply layer offset
    if z_scale:
        raw_min_z = float(np.min(xyz[:, 2]))
        xyz[:, 2] = (xyz[:, 2] - raw_min_z) * Z_SCALE_FACTOR + raw_min_z
        xyz[:, 2] += float(z_offset) * Z_SCALE_FACTOR
    else:
        xyz[:, 2] += float(z_offset)

    return {
        "xyz_b64": _encode_f16(xyz),
        "lbl_b64": _encode_u8(np.clip(labels, 0, 255)),
        "cloud_type": "semantic",
        "count": int(len(xyz)),
        "label_info": _build_label_info(labels),
        "file": os.path.basename(fp),
    }


def _load_traj_transformer(
    base_dir: str,
    base_name: str,
    z_scale: bool = False,
    ignore_labels: Optional[set] = None,
) -> Dict[str, Any]:
    """Load traj_gt / traj_pred for left-view '轨迹transformer' mode (v6)."""
    gt_fp = os.path.join(base_dir, base_name + "_traj_gt.npy")
    pred_fp = os.path.join(base_dir, base_name + "_traj_pred.npy")
    gt = _encode_traj_transformer_cloud(
        gt_fp, TRAJ_TRANSFORMER_Z_OFFSETS["gt"], z_scale, ignore_labels
    )
    pred = _encode_traj_transformer_cloud(
        pred_fp, TRAJ_TRANSFORMER_Z_OFFSETS["pred"], z_scale, ignore_labels
    )
    # Missing files are silent (no error); only report what is present.
    info_parts = []
    if gt:
        info_parts.append(f"traj_gt: {gt['count']} pts ({gt.get('file', '')})")
    if pred:
        info_parts.append(f"traj_pred: {pred['count']} pts ({pred.get('file', '')})")
    if not info_parts:
        info_parts.append("traj: 无")
    return {
        "gt": gt,
        "pred": pred,
        "hasTraj": bool(gt or pred),
        "info": " | ".join(info_parts),
        "warnings": [],
        "root_dir": base_dir,
    }


# mesh_gt 路面真值 + traj_gt_mesh（mesh 上插值的轨迹真值），见 eval.py dump
MESH_TRAJ_Z_OFFSET = 0.08  # 轨迹叠在 mesh 上略抬高，便于观察


def _load_npy_xyz_label(fp: str) -> Optional[np.ndarray]:
    """Load npy as float32 [N,>=4]; return None on any failure (no raise)."""
    if not fp or not os.path.isfile(fp):
        return None
    try:
        data = np.load(fp, allow_pickle=True)
        data = np.asarray(data, dtype=np.float32)
    except Exception as e:
        sys.stderr.write(f"Warning: npy load skipped ({fp}): {e}\n")
        return None
    if data.ndim != 2 or data.shape[1] < 4 or data.shape[0] == 0:
        return None
    return data


def _encode_semantic_xyz_label(
    arr: np.ndarray,
    z_offset: float = 0.0,
    z_scale: bool = False,
    max_points: Optional[int] = None,
    ignore_labels: Optional[set] = None,
    apply_ignore: bool = True,
    require_positive_col4: bool = False,
) -> Optional[Dict[str, Any]]:
    """Encode [N,>=4] xyz+label with same Z×scale convention as OCC GT (projection-safe).

    Args:
        apply_ignore: if True, drop ignore_labels (default includes 26).
        require_positive_col4: if True and arr has col4, keep only col4>0.5
            (traj_gt_mesh 的 valid_mask)。mesh_gt 的 col4 是 drivable，整幅显示时应为 False。
    """
    if arr is None or arr.shape[0] == 0:
        return None
    xyz = np.ascontiguousarray(arr[:, :3], dtype=np.float32)
    labels = np.rint(arr[:, 3]).astype(np.int32)

    mask = np.isfinite(xyz).all(axis=1)
    if apply_ignore:
        ignore_set = set(ignore_labels) if ignore_labels else set(DEFAULT_IGNORE)
        ignore_set.add(26)
        for lbl in ignore_set:
            mask &= labels != lbl
    # traj_gt_mesh 第5列 valid_mask；mesh_gt 第5列是 drivable，整幅显示不要按此过滤
    if require_positive_col4 and arr.shape[1] >= 5:
        mask &= arr[:, 4] > 0.5

    xyz = xyz[mask]
    labels = labels[mask]
    if len(xyz) == 0:
        return None

    if max_points and len(xyz) > max_points:
        rng = np.random.default_rng(seed=42)
        sel = rng.choice(len(xyz), max_points, replace=False)
        xyz = xyz[sel]
        labels = labels[sel]

    # Match _encode_point_cloud / panel displayToVcs: z *= Z_SCALE_FACTOR
    if z_scale:
        xyz[:, 2] *= Z_SCALE_FACTOR
        xyz[:, 2] += float(z_offset) * Z_SCALE_FACTOR
    else:
        xyz[:, 2] += float(z_offset)

    return {
        "xyz_b64": _encode_f16(xyz),
        "lbl_b64": _encode_u8(np.clip(labels, 0, 255)),
        "cloud_type": "semantic",
        "count": int(len(xyz)),
        "label_info": _build_label_info(labels),
    }


def _apply_z_display(xyz: np.ndarray, z_offset: float = 0.0, z_scale: bool = False) -> np.ndarray:
    """Copy xyz and apply the same display Z transform used by point encoding."""
    out = np.array(xyz, dtype=np.float32, copy=True)
    if z_scale:
        out[:, 2] *= Z_SCALE_FACTOR
        out[:, 2] += float(z_offset) * Z_SCALE_FACTOR
    else:
        out[:, 2] += float(z_offset)
    return out


def _build_mesh_wire_edges(xyz: np.ndarray) -> Optional[np.ndarray]:
    """Build thin grid wireframe segments from irregularly-present mesh vertices.

    height_field is an approximately regular XY grid (≈0.05m). Missing cells are OK:
    an edge is emitted only when both endpoints exist.
    Returns float32 array shaped [E*2, 3] suitable for THREE.LineSegments.
    """
    if xyz is None or len(xyz) < 4:
        return None
    pts = np.asarray(xyz, dtype=np.float32)
    # Quantize XY so floating noise doesn't break neighbor matching
    xq = np.round(pts[:, 0], 5)
    yq = np.round(pts[:, 1], 5)
    xs = np.unique(xq)
    ys = np.unique(yq)
    if xs.size < 2 or ys.size < 2:
        return None
    dx = float(np.median(np.diff(xs)))
    dy = float(np.median(np.diff(ys)))
    if dx <= 1e-6 or dy <= 1e-6:
        return None

    ix = np.rint((xq - xs[0]) / dx).astype(np.int32)
    iy = np.rint((yq - ys[0]) / dy).astype(np.int32)
    # Pack (ix,iy) → vertex index; keep first occurrence
    key = ix.astype(np.int64) * (int(ys.size) + 4) + iy.astype(np.int64)
    order = np.argsort(key, kind="mergesort")
    key_s = key[order]
    uniq_mask = np.ones(len(key_s), dtype=bool)
    uniq_mask[1:] = key_s[1:] != key_s[:-1]
    kept = order[uniq_mask]
    key_kept = key[kept]
    idx_map = {int(k): int(i) for k, i in zip(key_kept, kept)}

    stride = int(ys.size) + 4
    segs = []
    for k, i in idx_map.items():
        ix0 = int(k // stride)
        iy0 = int(k % stride)
        j_r = idx_map.get(int((ix0 + 1) * stride + iy0))
        if j_r is not None:
            segs.append(pts[i])
            segs.append(pts[j_r])
        j_u = idx_map.get(int(ix0 * stride + (iy0 + 1)))
        if j_u is not None:
            segs.append(pts[i])
            segs.append(pts[j_u])

    if not segs:
        return None
    return np.ascontiguousarray(np.stack(segs, axis=0), dtype=np.float32)


def _encode_mesh_surface(
    arr: np.ndarray,
    z_scale: bool = False,
    max_points: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Encode full mesh vertices + XY-grid wireframe edges for left-view 'mesh真值'."""
    if arr is None or arr.shape[0] == 0:
        return None
    xyz0 = np.ascontiguousarray(arr[:, :3], dtype=np.float32)
    labels0 = np.rint(arr[:, 3]).astype(np.int32)
    mask = np.isfinite(xyz0).all(axis=1)
    xyz0 = xyz0[mask]
    labels0 = labels0[mask]
    if len(xyz0) == 0:
        return None

    # Wireframe from full mesh (before any point downsample)
    xyz_disp = _apply_z_display(xyz0, z_offset=0.0, z_scale=z_scale)
    edges = None
    try:
        edges = _build_mesh_wire_edges(xyz_disp)
    except Exception as e:
        sys.stderr.write(f"Warning: mesh wireframe skipped: {e}\n")
        edges = None

    xyz = xyz_disp
    labels = labels0
    if max_points and len(xyz) > max_points:
        rng = np.random.default_rng(seed=42)
        sel = rng.choice(len(xyz), max_points, replace=False)
        xyz = xyz[sel]
        labels = labels[sel]

    out: Dict[str, Any] = {
        "xyz_b64": _encode_f16(xyz),
        "lbl_b64": _encode_u8(np.clip(labels, 0, 255)),
        "cloud_type": "semantic",
        "count": int(len(xyz)),
        "label_info": _build_label_info(labels),
        "edges_b64": _encode_f16(edges) if edges is not None else None,
        "edge_count": int(len(edges) // 2) if edges is not None else 0,
    }
    return out


def _empty_mesh_result(base_dir: str, info: str = "mesh: 无") -> Dict[str, Any]:
    return {
        "mesh": None,
        "trajMesh": None,
        "hasMesh": False,
        "info": info,
        "warnings": [],
        "root_dir": base_dir,
    }


def _first_existing_file(base_dir: str, base_name: str, suffixes) -> str:
    """Return first existing `{base}{suffix}`; if none exist, return the primary (first) path."""
    paths = [os.path.join(base_dir, base_name + s) for s in suffixes if s]
    for p in paths:
        if os.path.isfile(p):
            return p
    return paths[0] if paths else ""


def _load_mesh_files(
    base_dir: str,
    base_name: str,
    mesh_suffixes,
    traj_suffixes,
    mesh_info_name: str,
    traj_info_name: str,
    z_scale: bool = False,
    max_points: Optional[int] = None,
    ignore_labels: Optional[set] = None,
) -> Dict[str, Any]:
    """Load mesh npy + optional traj-on-mesh npy. Missing/bad files → empty, never raise."""
    try:
        mesh_fp = _first_existing_file(base_dir, base_name, mesh_suffixes)
        traj_mesh_fp = _first_existing_file(base_dir, base_name, traj_suffixes)

        mesh_arr = _load_npy_xyz_label(mesh_fp) if mesh_fp else None
        traj_arr = _load_npy_xyz_label(traj_mesh_fp) if traj_mesh_fp else None

        mesh = None
        if mesh_arr is not None:
            try:
                mesh = _encode_mesh_surface(
                    mesh_arr, z_scale=z_scale, max_points=max_points,
                )
            except Exception as e:
                sys.stderr.write(f"Warning: mesh encode skipped ({mesh_fp}): {e}\n")
                mesh = None

        traj_mesh = None
        if traj_arr is not None:
            try:
                traj_mesh = _encode_semantic_xyz_label(
                    traj_arr, z_offset=MESH_TRAJ_Z_OFFSET, z_scale=z_scale,
                    max_points=None, ignore_labels=ignore_labels,
                    apply_ignore=True, require_positive_col4=True,
                )
            except Exception as e:
                sys.stderr.write(f"Warning: traj-mesh encode skipped ({traj_mesh_fp}): {e}\n")
                traj_mesh = None

        if mesh:
            mesh["file"] = os.path.basename(mesh_fp)
        if traj_mesh:
            traj_mesh["file"] = os.path.basename(traj_mesh_fp)

        info_parts = []
        if mesh:
            ecount = mesh.get("edge_count") or 0
            info_parts.append(f"{mesh_info_name}: {mesh['count']} pts, {ecount} edges")
        if traj_mesh:
            info_parts.append(f"{traj_info_name}: {traj_mesh['count']} pts")
        if not info_parts:
            info_parts.append("mesh: 无")

        return {
            "mesh": mesh,
            "trajMesh": traj_mesh,
            "hasMesh": bool(mesh or traj_mesh),
            "info": " | ".join(info_parts),
            "warnings": [],
            "root_dir": base_dir,
        }
    except Exception as e:
        sys.stderr.write(f"Warning: mesh load skipped: {e}\n")
        return _empty_mesh_result(base_dir)


def _load_mesh_gt(
    base_dir: str,
    base_name: str,
    z_scale: bool = False,
    max_points: Optional[int] = None,
    ignore_labels: Optional[set] = None,
) -> Dict[str, Any]:
    """Load `{base}_mesh_gt.npy` + optional `{base}_traj_gt_mesh.npy` for left-view 'mesh真值'.

    mesh_gt 按整幅文件显示（不过滤 drivable / empty），并附带网格线框边；
    缺失文件 → 空结果，不抛错。
    """
    return _load_mesh_files(
        base_dir, base_name,
        mesh_suffixes=("_mesh_gt.npy",),
        traj_suffixes=("_traj_gt_mesh.npy",),
        mesh_info_name="mesh_gt",
        traj_info_name="traj_gt_mesh",
        z_scale=z_scale, max_points=max_points, ignore_labels=ignore_labels,
    )


def _load_mesh_pred(
    base_dir: str,
    base_name: str,
    z_scale: bool = False,
    max_points: Optional[int] = None,
    ignore_labels: Optional[set] = None,
) -> Dict[str, Any]:
    """Load pred mesh for right-view 'mesh预测' (symmetric to `_load_mesh_gt`).

    Primary: `{base}_mesh_pred.npy` (aligns with `{base}_mesh_gt.npy`).
    Fallback: `{base}_pred_mesh.npy`. Optional `{base}_traj_pred_mesh.npy`.
    缺失 / 空路径 / 格式异常 → 空结果，不抛错。
    """
    return _load_mesh_files(
        base_dir, base_name,
        mesh_suffixes=("_mesh_pred.npy", "_pred_mesh.npy"),
        traj_suffixes=("_traj_pred_mesh.npy",),
        mesh_info_name="mesh_pred",
        traj_info_name="traj_pred_mesh",
        z_scale=z_scale, max_points=max_points, ignore_labels=ignore_labels,
    )


def _encode_point_cloud(
    arr: np.ndarray,
    ignore_labels: Optional[set] = None,
    z_scale: bool = False,
    max_points: Optional[int] = None,
    is_lidar: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Encode a loaded point cloud array into the protocol format.

    SSH-optimised wire format — colours are computed in JavaScript, not sent:
      xyz_b64  : float16  (2x smaller than float32)
      lbl_b64  : uint8    (labels 0-26 for semantic, 0-255 intensity for lidar; 4x smaller)
      cloud_type: "semantic" | "intensity"
      count    : int
      label_info: str

    Removing rgb_b64 saves ~800-1300 KB per cloud (the biggest payload chunk).
    """
    if arr.shape[0] == 0:
        return None

    col3 = arr[:, 3] if arr.shape[1] > 3 else np.zeros(arr.shape[0], dtype=np.float32)

    if not is_lidar:
        labels_raw = col3.view(np.float32).astype(np.int32)

        # ── 1. Filter by label on indices (avoid copying full 1.9M array) ────
        if ignore_labels:
            mask = np.ones(len(labels_raw), dtype=bool)
            for lbl in ignore_labels:
                mask &= labels_raw != lbl
            keep_idx = np.where(mask)[0]
        else:
            keep_idx = np.arange(len(labels_raw))

        if len(keep_idx) == 0:
            return None

        # ── 2. Downsample on indices ──────────────────────────────────────────
        if max_points and len(keep_idx) > max_points:
            rng = np.random.default_rng(seed=int(keep_idx[0]))
            sel = rng.choice(len(keep_idx), max_points, replace=False)
            keep_idx = keep_idx[sel]

        # ── 3. Copy only survivors ────────────────────────────────────────────
        xyz    = arr[keep_idx, :3].astype(np.float32)
        labels = labels_raw[keep_idx]

        if z_scale:
            xyz[:, 2] *= Z_SCALE_FACTOR

        label_info = _build_label_info(labels)

        return {
            "xyz_b64":    _encode_f16(xyz),          # float16 – 2× smaller
            "lbl_b64":    _encode_u8(np.clip(labels, 0, 255)),  # uint8 semantic class
            "cloud_type": "semantic",
            "count":      int(len(xyz)),
            "label_info": label_info,
        }

    else:
        # lidar: send normalised intensity as uint8 (0-255); JS computes greyscale
        if max_points and len(arr) > max_points:
            rng = np.random.default_rng(seed=42)
            sel = rng.choice(len(arr), max_points, replace=False)
            xyz         = arr[sel, :3].astype(np.float32)
            intensities = col3[sel].astype(np.float32)
        else:
            xyz         = arr[:, :3].astype(np.float32)
            intensities = col3.astype(np.float32)

        if z_scale:
            xyz[:, 2] *= Z_SCALE_FACTOR

        i_min, i_max = float(intensities.min()), float(intensities.max())
        if i_max > i_min:
            norm_u8 = ((intensities - i_min) / (i_max - i_min) * 255).astype(np.uint8)
        else:
            norm_u8 = np.zeros(len(intensities), dtype=np.uint8)

        label_info = _build_intensity_label_info(intensities)

        return {
            "xyz_b64":    _encode_f16(xyz),    # float16 – 2× smaller
            "lbl_b64":    _encode_u8(norm_u8), # uint8 intensity 0-255
            "cloud_type": "intensity",
            "count":      int(len(xyz)),
            "label_info": label_info,
        }



# ---------------------------------------------------------------------------
# paths.json / sensor_param.json
# ---------------------------------------------------------------------------


def _is_valid_path_str(val: Any) -> bool:
    if val is None:
        return False
    s = str(val).strip()
    return bool(s) and s.lower() not in ("null", "none")


def _load_paths_json(base_dir: str, base_name: str) -> Optional[Dict[str, Any]]:
    """Load and sanitize {base}_paths.json for frontend display."""
    fp = os.path.join(base_dir, base_name + "_paths.json")
    if not os.path.isfile(fp):
        return None
    try:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    entries: List[Dict[str, str]] = []
    for section, label_prefix in (
        ("inputs", "input"),
        ("outputs", "output"),
        ("datalink_frame", "datalink"),
    ):
        block = data.get(section)
        if not isinstance(block, dict):
            continue
        for key, val in block.items():
            if _is_valid_path_str(val):
                entries.append(
                    {
                        "section": section,
                        "key": str(key),
                        "label": f"{label_prefix}.{key}",
                        "path": str(val).strip(),
                    }
                )

    result: Dict[str, Any] = {"entries": entries}
    scene_name = data.get("scene_name")
    if scene_name is not None and str(scene_name).strip():
        result["scene_name"] = str(scene_name).strip()
    if data.get("sample_idx") is not None:
        result["sample_idx"] = data.get("sample_idx")
    if data.get("has_gt") is not None:
        result["has_gt"] = bool(data.get("has_gt"))
    gt_note = data.get("gt_note")
    if _is_valid_path_str(gt_note):
        result["gt_note"] = str(gt_note).strip()

    if not entries and "scene_name" not in result:
        return None
    return result


def _quat_from_dict(d: Optional[Dict[str, Any]]) -> Optional[np.ndarray]:
    if not d or not isinstance(d, dict):
        return None
    if "w" in d:
        return np.array(
            [d.get("w", 0), d.get("x", 0), d.get("y", 0), d.get("z", 0)],
            dtype=np.float64,
        )
    if "qw" in d:
        return np.array(
            [d.get("qw", 0), d.get("qx", 0), d.get("qy", 0), d.get("qz", 0)],
            dtype=np.float64,
        )
    return None


def _vec_from_dict(d: Optional[Dict[str, Any]]) -> Optional[np.ndarray]:
    if not d or not isinstance(d, dict):
        return None
    return np.array([d.get("x", 0), d.get("y", 0), d.get("z", 0)], dtype=np.float64)


def _quat_to_rot(q: np.ndarray) -> np.ndarray:
    q = q / np.linalg.norm(q)
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def _make_T(q_dict: Optional[Dict[str, Any]], t_dict: Optional[Dict[str, Any]]) -> Optional[np.ndarray]:
    q = _quat_from_dict(q_dict)
    t = _vec_from_dict(t_dict)
    if q is None or t is None:
        return None
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = _quat_to_rot(q)
    T[:3, 3] = t
    return T


def _load_sensor_calib(base_dir: str, base_name: str) -> Optional[Dict[str, Any]]:
    """Load camera/lidar extrinsics and intrinsics from {base}_sensor_param.json."""
    fp = os.path.join(base_dir, base_name + "_sensor_param.json")
    if not os.path.isfile(fp):
        return None
    try:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    sp = data.get("sensor_param")
    if not isinstance(sp, dict):
        return None
    cam = sp.get("cam")
    lidar = sp.get("lidar")
    if not isinstance(cam, dict) or not isinstance(lidar, dict):
        return None

    proj = cam.get("proj_param") or {}
    dist = cam.get("dist_param") or {}
    res = cam.get("resolution") or {}
    fu = float(proj.get("fu", 0))
    fv = float(proj.get("fv", 0))
    cu = float(proj.get("cu", 0))
    cv = float(proj.get("cv", 0))
    ru = int(res.get("ru", 0))
    rv = int(res.get("rv", 0))
    if fu <= 0 or fv <= 0 or ru <= 0 or rv <= 0:
        return None

    T_vcs_cam = _make_T(cam.get("q_vcs_cam"), cam.get("t_vcs_cam"))
    T_vcs_lidar = _make_T(lidar.get("q_vcs_lidar"), lidar.get("t_vcs_lidar"))
    if T_vcs_cam is None or T_vcs_lidar is None:
        return None

    # T_vcs_* : sensor → VCS; projection uses inv(T_vcs_cam) on VCS points
    T_cam_vcs = np.linalg.inv(T_vcs_cam)

    result: Dict[str, Any] = {
        "fu": fu,
        "fv": fv,
        "cu": cu,
        "cv": cv,
        "ru": ru,
        "rv": rv,
        "k1": float(dist.get("k1", 0)),
        "k2": float(dist.get("k2", 0)),
        "k3": float(dist.get("k3", 0)),
        "k4": float(dist.get("k4", 0)),
        "T_cam_vcs": T_cam_vcs.tolist(),
        "z_scale_factor": Z_SCALE_FACTOR,
    }
    if _is_valid_path_str(data.get("filename")):
        result["filename"] = str(data["filename"]).strip()
    if _is_valid_path_str(data.get("pts_filename")):
        result["pts_filename"] = str(data["pts_filename"]).strip()
    return result


# ---------------------------------------------------------------------------
# Scene / frame scanning
# ---------------------------------------------------------------------------


def _get_scene_name(base: str, directory: str) -> str:
    """Extract scene name from _paths.json metadata file."""
    paths_file = os.path.join(directory, base + "_paths.json")
    if os.path.isfile(paths_file):
        try:
            with open(paths_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            scene = data.get("scene_name", "")
            if scene:
                return os.path.basename(str(scene))
        except Exception:
            pass
    return ""


def _find_image_path(directory: str, base: str) -> Optional[str]:
    """Return the first existing image path for the given base, or None."""
    candidates = [
        os.path.join(directory, base + "_image.jpg"),
        os.path.join(directory, base + "_image_cam0.jpg"),
        os.path.join(directory, base + "_image_cam1.jpg"),
        os.path.join(directory, base + "_image.png"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _find_image_paths(directory: str, base: str) -> List[str]:
    """Return all existing image paths for the given base."""
    candidates = [
        os.path.join(directory, base + "_image.jpg"),
        os.path.join(directory, base + "_image_cam0.jpg"),
        os.path.join(directory, base + "_image_cam1.jpg"),
        os.path.join(directory, base + "_image.png"),
    ]
    return [c for c in candidates if os.path.isfile(c)]


def _scan_directory(directory: str) -> Dict[str, Any]:
    """
    Walk directory recursively and group files by base name.
    Returns {"frames": [...], "total": N}.
    """
    # suffixes that indicate a known file
    suffixes = [
        "_gt.pcd.bin.npy",
        "_pred.pcd.bin.npy",
        "_lidar.pcd.bin.npy",
        "_gaussian.pkl",
        "_paths.json",
        "_sensor_param.json",
        "_traj_gt.npy",
        "_traj_pred.npy",
        "_mesh_gt.npy",
        "_traj_gt_mesh.npy",
        "_mesh_pred.npy",
        "_pred_mesh.npy",
        "_traj_pred_mesh.npy",
        "_image.jpg",
        "_image_cam0.jpg",
        "_image_cam1.jpg",
        "_image.png",
    ]

    bases_seen: Dict[str, Dict[str, bool]] = {}  # base -> {has_gt, has_pred, ...}

    def _onerror(err):
        # Don't abort on permission denied — just skip inaccessible directories
        sys.stderr.write(f"vis_helper scan skip: {err}\n")

    for root, dirs, files in os.walk(directory, onerror=_onerror):
        # skip hidden directories and common non-data dirs
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ('__pycache__', '.git', 'node_modules')]
        for fname in files:
            for suf in suffixes:
                if fname.endswith(suf):
                    base = fname[: -len(suf)]
                    rel_dir = os.path.relpath(root, directory)
                    # Use relative base path so files in subdirs don't collide
                    if rel_dir == ".":
                        full_base = base
                    else:
                        full_base = os.path.join(rel_dir, base).replace("\\", "/")

                    if full_base not in bases_seen:
                        bases_seen[full_base] = {
                            "has_gt": False,
                            "has_pred": False,
                            "has_lidar": False,
                            "has_gaussian": False,
                            "has_traj": False,
                            "has_mesh": False,
                            "has_mesh_pred": False,
                            "root": root,
                        }
                    entry = bases_seen[full_base]
                    if suf == "_gt.pcd.bin.npy":
                        entry["has_gt"] = True
                    elif suf == "_pred.pcd.bin.npy":
                        entry["has_pred"] = True
                    elif suf == "_lidar.pcd.bin.npy":
                        entry["has_lidar"] = True
                    elif suf == "_gaussian.pkl":
                        entry["has_gaussian"] = True
                    elif suf in ("_traj_gt.npy", "_traj_pred.npy"):
                        entry["has_traj"] = True
                    elif suf in ("_mesh_gt.npy", "_traj_gt_mesh.npy"):
                        entry["has_mesh"] = True
                    elif suf in ("_mesh_pred.npy", "_pred_mesh.npy", "_traj_pred_mesh.npy"):
                        entry["has_mesh_pred"] = True
                    break

    # Build sorted frame list
    sorted_bases = sorted(bases_seen.keys(), key=_natural_sort_key)
    frames = []
    for full_base in sorted_bases:
        entry = bases_seen[full_base]
        root = entry["root"]
        base = os.path.basename(full_base)
        # Do NOT read _paths.json here — on networked filesystems (JuiceFS/NFS)
        # opening 4000+ files during scan causes 30-120s delays.
        # sceneName is loaded lazily when the frame is first loaded.
        display_name = full_base

        frame_info: Dict[str, Any] = {
            "base": full_base,
            "displayName": display_name,
            "sceneName": "",  # loaded lazily on first frame access (avoids N×JuiceFS reads)
            "hasGt": entry["has_gt"],
            "hasPred": entry["has_pred"],
            "hasLidar": entry["has_lidar"],
            "hasGaussian": entry["has_gaussian"],
            "hasTraj": entry.get("has_traj", False),
            "hasMesh": entry.get("has_mesh", False),
            "hasMeshPred": entry.get("has_mesh_pred", False),
        }

        if entry["has_gaussian"]:
            gaussian_path = os.path.join(root, base + "_gaussian.pkl")
            frame_info["gaussian"] = gaussian_path

        frames.append(frame_info)

    return {"frames": frames, "total": len(frames)}


# ---------------------------------------------------------------------------
# Frame loading
# ---------------------------------------------------------------------------


def _load_frame(
    directory: str,
    idx: int,
    z_scale: bool = False,
    max_points: Optional[int] = None,
    ignore_labels: Optional[List[int]] = None,
    base_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Load all data for a specific frame index.

    If base_key is provided, skip the expensive rescan and use it directly.
    base_key format: "rel_subdir/basename" or just "basename" for root.
    """
    if base_key is not None:
        # Fast path: base_key passed from cached scan — no rescan needed
        full_base = base_key
        has_gaussian_hint = True   # unknown, will check file existence
    else:
        # Slow path: rescan (only used when called without base_key)
        scan_result = _scan_directory(directory)
        frames = scan_result["frames"]
        if idx < 0 or idx >= len(frames):
            raise IndexError(f"Frame index {idx} out of range (0-{len(frames) - 1})")
        full_base = frames[idx]["base"]
        has_gaussian_hint = frames[idx].get("hasGaussian", False)

    # Resolve the root directory for this frame
    base_dir = directory
    base_name = full_base
    if "/" in full_base:
        parts = full_base.rsplit("/", 1)
        base_dir = os.path.join(directory, parts[0])
        base_name = parts[1]
    elif "\\" in full_base:
        parts = full_base.rsplit("\\", 1)
        base_dir = os.path.join(directory, parts[0])
        base_name = parts[1]

    ignore_set = set(ignore_labels) if ignore_labels else set(DEFAULT_IGNORE)
    # Label 26 (ignore/black) is always filtered — it is never meaningful to display
    # and typically makes up >95% of points, so filtering it saves huge processing time
    ignore_set.add(26)

    # Load images
    image_paths = _find_image_paths(base_dir, base_name)

    # ── Load GT, Pred, Lidar in parallel ──────────────────────────────────────
    from concurrent.futures import ThreadPoolExecutor

    gt_fp    = os.path.join(base_dir, base_name + "_gt.pcd.bin.npy")
    pred_fp  = os.path.join(base_dir, base_name + "_pred.pcd.bin.npy")
    lidar_fp = os.path.join(base_dir, base_name + "_lidar.pcd.bin.npy")

    def _load_gt():
        if not os.path.isfile(gt_fp):
            return None
        try:
            return _encode_point_cloud(
                _load_pcd_bin_npy(gt_fp),
                ignore_labels=ignore_set, z_scale=z_scale,
                max_points=max_points, is_lidar=False)
        except Exception as e:
            sys.stderr.write(f"Warning: GT load failed: {e}\n")
            return None

    def _load_pred():
        if not os.path.isfile(pred_fp):
            return None
        try:
            return _encode_point_cloud(
                _load_pcd_bin_npy(pred_fp),
                ignore_labels=ignore_set, z_scale=z_scale,
                max_points=max_points, is_lidar=False)
        except Exception as e:
            sys.stderr.write(f"Warning: pred load failed: {e}\n")
            return None

    def _load_lidar():
        if not os.path.isfile(lidar_fp):
            return None
        try:
            return _encode_point_cloud(
                _load_pcd_bin_npy(lidar_fp),
                ignore_labels=None, z_scale=z_scale,
                max_points=max_points, is_lidar=True)
        except Exception as e:
            sys.stderr.write(f"Warning: lidar load failed: {e}\n")
            return None

    def _load_traj():
        try:
            return _load_traj_transformer(
                base_dir, base_name, z_scale=z_scale, ignore_labels=ignore_set
            )
        except Exception as e:
            sys.stderr.write(f"Warning: traj transformer load failed: {e}\n")
            return {
                "gt": None, "pred": None, "hasTraj": False,
                "info": "traj: 无", "warnings": [],
                "root_dir": base_dir,
            }

    def _load_mesh():
        try:
            return _load_mesh_gt(
                base_dir, base_name,
                z_scale=z_scale, max_points=max_points, ignore_labels=ignore_set,
            )
        except Exception as e:
            sys.stderr.write(f"Warning: mesh gt load failed: {e}\n")
            return _empty_mesh_result(base_dir)

    def _load_mesh_pred_frame():
        try:
            return _load_mesh_pred(
                base_dir, base_name,
                z_scale=z_scale, max_points=max_points, ignore_labels=ignore_set,
            )
        except Exception as e:
            sys.stderr.write(f"Warning: mesh pred load failed: {e}\n")
            return _empty_mesh_result(base_dir)

    with ThreadPoolExecutor(max_workers=6) as pool:
        f_gt    = pool.submit(_load_gt)
        f_pred  = pool.submit(_load_pred)
        f_lidar = pool.submit(_load_lidar)
        f_traj  = pool.submit(_load_traj)
        f_mesh  = pool.submit(_load_mesh)
        f_mesh_pred = pool.submit(_load_mesh_pred_frame)
        gt_result    = f_gt.result()
        pred_result  = f_pred.result()
        lidar_result = f_lidar.result()
        traj_result  = f_traj.result()
        mesh_result  = f_mesh.result()
        mesh_pred_result = f_mesh_pred.result()

    # Derive presence flags from file-system (works for both fast and slow paths)
    scene_name = _get_scene_name(base_name, base_dir)
    has_gt      = os.path.isfile(gt_fp)
    has_pred    = os.path.isfile(pred_fp)
    has_lidar   = os.path.isfile(lidar_fp)
    has_gaussian = os.path.isfile(os.path.join(base_dir, base_name + "_gaussian.pkl"))
    has_traj = bool(traj_result and traj_result.get("hasTraj"))
    has_mesh = bool(mesh_result and mesh_result.get("hasMesh"))
    has_mesh_pred = bool(mesh_pred_result and mesh_pred_result.get("hasMesh"))

    # Build info string
    info_parts = [f"Frame: {full_base}"]
    if scene_name:
        info_parts.append(f"Scene: {scene_name}")
    if gt_result:
        info_parts.append(f"GT points: {gt_result['count']}")
    if pred_result:
        info_parts.append(f"Pred points: {pred_result['count']}")
    if lidar_result:
        info_parts.append(f"Lidar points: {lidar_result['count']}")
    if has_traj:
        info_parts.append(traj_result.get("info") or "traj: yes")
    if has_mesh:
        info_parts.append(mesh_result.get("info") or "mesh: yes")
    if has_mesh_pred:
        info_parts.append(mesh_pred_result.get("info") or "mesh_pred: yes")
    info = " | ".join(info_parts)

    # Build frameInfo string (detailed)
    frame_info_parts = [f"Index: {idx}", f"Base: {full_base}"]
    if scene_name:
        frame_info_parts.append(f"Scene: {scene_name}")
    frame_info_parts.append(f"HasGT: {has_gt}")
    frame_info_parts.append(f"HasPred: {has_pred}")
    frame_info_parts.append(f"HasLidar: {has_lidar}")
    frame_info_parts.append(f"HasGaussian: {has_gaussian}")
    frame_info_parts.append(f"HasTrajTransformer: {has_traj}")
    frame_info_parts.append(f"HasMeshGt: {has_mesh}")
    frame_info_parts.append(f"HasMeshPred: {has_mesh_pred}")
    if gt_result:
        frame_info_parts.append(f"GT labels: {gt_result['label_info']}")
    if pred_result:
        frame_info_parts.append(f"Pred labels: {pred_result['label_info']}")
    if lidar_result:
        frame_info_parts.append(f"Lidar: {lidar_result['label_info']}")
    if traj_result and traj_result.get("hasTraj"):
        frame_info_parts.append(f"TrajTransformer: {traj_result.get('info', '')}")
    if mesh_result and mesh_result.get("hasMesh"):
        frame_info_parts.append(f"MeshGt: {mesh_result.get('info', '')}")
    if mesh_pred_result and mesh_pred_result.get("hasMesh"):
        frame_info_parts.append(f"MeshPred: {mesh_pred_result.get('info', '')}")
    frame_info = "\n".join(frame_info_parts)

    paths_info = _load_paths_json(base_dir, base_name)
    sensor_calib = _load_sensor_calib(base_dir, base_name)

    return {
        "images": image_paths,
        "gt": gt_result,
        "pred": pred_result,
        "lidar": lidar_result,
        "trajTransformer": traj_result,
        "meshGt": mesh_result,
        "meshPred": mesh_pred_result,
        "info": info,
        "frameInfo": frame_info,
        "paths": paths_info,
        "sensorCalib": sensor_calib,
        "zScaleApplied": bool(z_scale),
        "sceneName": scene_name,
    }


# ---------------------------------------------------------------------------
# Gaussian loading
# ---------------------------------------------------------------------------


def _load_gaussian(pkl_path: str, z_scale_factor: float = 1.0) -> Dict[str, Any]:
    """
    Load Gaussian features from a .pkl file.
    Expected keys: means(N,3), scales(N,3), rots(N,4)[w,x,y,z], opas(N,1), semantics(N,27).
    """
    with open(pkl_path, "rb") as f:
        data = pickle.load(f)

    means: np.ndarray = np.array(data["means"], dtype=np.float32)
    scales: np.ndarray = np.array(data["scales"], dtype=np.float32)
    rots: np.ndarray = np.array(data["rots"], dtype=np.float32)
    opas: np.ndarray = np.array(data["opas"], dtype=np.float32).reshape(-1)
    semantics: np.ndarray = np.array(data["semantics"], dtype=np.float32)

    # Filter by opacity > 0
    mask = opas > 0
    means = means[mask]
    scales = scales[mask]
    rots = rots[mask]
    opas = opas[mask]
    semantics = semantics[mask]

    n = means.shape[0]

    if n == 0:
        # Return empty arrays
        empty = _encode_f32(np.zeros((0, 3), dtype=np.float32))
        empty1 = _encode_f32(np.zeros((0,), dtype=np.float32))
        return {
            "centers_b64": empty,
            "colors_b64": empty,
            "scales_b64": empty,
            "quats_b64": _encode_f32(np.zeros((0, 4), dtype=np.float32)),
            "opas_b64": empty1,
            "count": 0,
            "label_info": "No Gaussians after opacity filter",
            "label_counts": [],
        }

    # Get label from argmax of semantics
    labels = np.argmax(semantics, axis=1).astype(np.int32)

    # Stretch centers in world-Z only. Do NOT scale scales[:,2]: that stretches the
    # local ellipsoid axis, which after rotation leaks into XY and makes the road look wider.
    if z_scale_factor != 1.0:
        means[:, 2] = means[:, 2] * z_scale_factor

    # Build colors from label
    color_lut = np.array(
        [LABEL_COLORS.get(i, (0.5, 0.5, 0.5)) for i in range(max(LABEL_COLORS.keys()) + 1)],
        dtype=np.float32,
    )
    clamped = np.clip(labels, 0, len(color_lut) - 1)
    colors = color_lut[clamped]

    label_info = _build_label_info(labels)
    label_counts = _build_label_counts(labels)

    return {
        "centers_b64": _encode_f32(means),
        "colors_b64": _encode_f32(colors),
        "scales_b64": _encode_f32(scales),
        "quats_b64": _encode_f32(rots),
        "opas_b64": _encode_f32(np.ascontiguousarray(opas, dtype=np.float32)),
        "count": int(n),
        "label_info": label_info,
        "label_counts": label_counts,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_ignore_labels(s: str) -> List[int]:
    """Parse comma-separated label indices."""
    if not s:
        return []
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def _dispatch(args_dict: dict) -> dict:
    """Dispatch a single request dict, return result dict (no subprocess overhead)."""
    mode = args_dict.get("mode")
    if mode == "ping":
        # Immediate echo — used by extension to verify stdin pipe works before real requests
        import platform as _platform
        return {
            "pong": True,
            "python": sys.version,
            "platform": _platform.system(),
        }
    if mode == "scan":
        directory = args_dict["dir"]
        if not os.path.isdir(directory):
            raise ValueError(f"Directory not found: {directory}")
        return _scan_directory(directory)

    elif mode == "frame":
        directory = args_dict["dir"]
        if not os.path.isdir(directory):
            raise ValueError(f"Directory not found: {directory}")
        il_str = args_dict.get("ignore_labels", "")
        ignore_labels = _parse_ignore_labels(il_str) if il_str else list(DEFAULT_IGNORE)
        return _load_frame(
            directory=directory,
            idx=int(args_dict.get("idx", 0)),
            z_scale=bool(args_dict.get("z_scale", False)),
            max_points=int(args_dict["max_points"]) if args_dict.get("max_points") else None,
            ignore_labels=ignore_labels,
            base_key=args_dict.get("base_key"),
        )

    elif mode == "gaussian":
        pkl_path = args_dict["pkl"]
        if not os.path.isfile(pkl_path):
            raise ValueError(f"PKL file not found: {pkl_path}")
        return _load_gaussian(
            pkl_path=pkl_path,
            z_scale_factor=float(args_dict.get("z_scale_factor", 1.0)),
        )
    else:
        raise ValueError(f"Unknown mode: {mode}")


def _daemon_loop() -> None:
    """
    Persistent daemon mode: read newline-delimited JSON requests from stdin,
    write newline-delimited JSON responses to stdout.
    Eliminates Python startup cost (~300ms) for every frame switch.
    Protocol:
      stdin:  {"id":1,"mode":"frame","dir":"...","idx":0,...}\n
      stdout: {"id":1,"result":{...}}\n   or   {"id":1,"error":"..."}\n

    IMPORTANT: use sys.stdin.readline() not "for line in stdin" — the iterator
    uses a 8KB read-ahead buffer on pipes which causes requests to be silently
    buffered until the buffer fills (→ timeout on SSH / code-server).
    Also set PYTHONUNBUFFERED=1 or use python -u to keep stdout unbuffered.
    """
    # Ensure stdout is line-buffered (critical on SSH/code-server pipes)
    try:
        sys.stdout.reconfigure(line_buffering=True)  # Python 3.7+
    except AttributeError:
        pass  # fallback: rely on flush() calls
    try:
        sys.stdin.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    # Belt-and-suspenders: reopen stdin in unbuffered text mode if reconfigure failed.
    # This matters when code-server / SSH wraps the pipe in a way that -u flag doesn't reach.
    _stdin = sys.stdin
    try:
        import io as _io
        _stdin = _io.TextIOWrapper(
            sys.stdin.buffer if hasattr(sys.stdin, 'buffer') else sys.stdin,
            encoding='utf-8',
            errors='replace',
            line_buffering=True,
        )
    except Exception:
        pass  # use original sys.stdin

    sys.stderr.write("vis_helper daemon ready\n")
    sys.stderr.flush()

    while True:
        line = _stdin.readline()
        if not line:  # EOF — parent closed stdin, exit cleanly
            break
        line = line.strip()
        if not line:
            continue
        req_id = 0
        try:
            req = json.loads(line)
            req_id = req.get("id", 0)
            result = _dispatch(req)
            sys.stdout.write(json.dumps({"id": req_id, "result": result}) + "\n")
            sys.stdout.flush()
        except Exception as exc:
            sys.stdout.write(json.dumps({"id": req_id, "error": str(exc)}) + "\n")
            sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="GaussianFormer visualization helper")
    parser.add_argument("--mode", required=False, choices=["scan", "frame", "gaussian", "daemon"],
                        help="Operation mode. Omit for daemon mode (reads JSON from stdin).")
    parser.add_argument("--dir", help="Directory containing frame files")
    parser.add_argument("--idx", type=int, default=0, help="Frame index")
    parser.add_argument("--z-scale", action="store_true", help="Apply Z-axis scaling")
    parser.add_argument("--max-points", type=int, default=None, help="Maximum points to return")
    parser.add_argument(
        "--ignore-labels",
        type=str,
        default="",
        help="Comma-separated label indices to ignore",
    )
    parser.add_argument("--base-key", type=str, default=None, help="Frame base key (skips rescan)")
    parser.add_argument("--pkl", help="Path to Gaussian .pkl file")
    parser.add_argument(
        "--z-scale-factor", type=float, default=1.0, help="Z-axis scale factor for Gaussians"
    )

    args = parser.parse_args()

    # No mode → daemon
    if args.mode is None or args.mode == "daemon":
        _daemon_loop()
        return

    try:
        if args.mode == "scan":
            if not args.dir:
                raise ValueError("--dir is required for scan mode")
            if not os.path.isdir(args.dir):
                raise ValueError(f"Directory not found: {args.dir}")
            result = _scan_directory(args.dir)
            print(json.dumps(result), flush=True)

        elif args.mode == "frame":
            if not args.dir:
                raise ValueError("--dir is required for frame mode")
            if not os.path.isdir(args.dir):
                raise ValueError(f"Directory not found: {args.dir}")
            ignore_labels = _parse_ignore_labels(args.ignore_labels) if args.ignore_labels else list(DEFAULT_IGNORE)
            result = _load_frame(
                directory=args.dir,
                idx=args.idx,
                z_scale=args.z_scale,
                max_points=args.max_points,
                ignore_labels=ignore_labels,
                base_key=args.base_key if hasattr(args, "base_key") else None,
            )
            print(json.dumps(result), flush=True)

        elif args.mode == "gaussian":
            if not args.pkl:
                raise ValueError("--pkl is required for gaussian mode")
            if not os.path.isfile(args.pkl):
                raise ValueError(f"PKL file not found: {args.pkl}")
            result = _load_gaussian(pkl_path=args.pkl, z_scale_factor=args.z_scale_factor)
            print(json.dumps(result), flush=True)

    except Exception as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
