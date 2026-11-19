# GaussianFormer Visualizer - VS Code Extension

A VS Code / Cursor extension for visualizing GaussianFormer road model outputs directly in your editor. Inspect ground-truth annotations, model predictions, LiDAR point clouds, and intermediate Gaussian features—all without leaving your IDE.

---

## Features

### Camera Image Display
View up to 2 synchronized camera images per frame. The image panel supports mouse-driven zoom and pan so you can inspect fine-grained road-surface detail at any scale.

> *Screenshot: dual-camera panel with zoom/pan controls*

### 3D Point Cloud Views — GT / Prediction / LiDAR
Three independent 3D viewports render ground-truth labels, model predictions, and raw LiDAR returns side-by-side. Every point is colored by its semantic class using a consistent palette, making it easy to compare annotation quality against model output at a glance.

> *Screenshot: GT (left) vs Pred (right) 3D scatter with semantic color coding*

### Gaussian Feature Visualization
The extension decodes the `_gaussian.pkl` intermediate features and renders up to **5 000 ellipsoids** as instanced 3D spheres in a WebGL viewport, each colored by its dominant semantic class. This gives an intuitive view of how the model distributes Gaussian primitives across the scene.

> *Screenshot: Gaussian ellipsoid cloud over a road scene*

### Frame Navigation
- Click any entry in the frame list panel to jump directly to that frame.
- Use **← / →** arrow keys for single-step navigation.
- Press **Space** to start/stop automatic playback and scrub through a sequence hands-free.

> *Screenshot: frame list sidebar with playback controls*

### Z-Axis ×10 Scaling
Road-surface features are compressed vertically in real-world coordinates. A dedicated Z ×10 toggle stretches the vertical axis by a factor of 10, revealing fine-grained height variation in ground labels and predictions that would otherwise be invisible.

### Label Filtering
Select any combination of semantic classes to exclude from all 3D views simultaneously. Filtering out irrelevant classes (e.g., sky, background) reduces visual clutter and lets you focus on the road categories that matter for your analysis.

### GT ↔ Pred Synchronized Camera View
Toggling the sync mode links the GT and Prediction 3D viewports so that orbit, pan, and zoom actions in one viewport are mirrored in the other. This makes direct visual comparison of annotation vs prediction trivial.

---

## Data Structure

The extension expects one directory per dataset or evaluation run. Each frame is identified by a numeric or string **base name** (e.g. `0`, `1`, `42`). The following files must follow this naming convention:

| File | Required | Description |
|------|----------|-------------|
| `{base}_gt.pcd.bin.npy` | Yes | Ground-truth semantic point cloud (NumPy array) |
| `{base}_pred.pcd.bin.npy` | Yes | Model prediction point cloud (NumPy array) |
| `{base}_lidar.pcd.bin.npy` | Yes | Raw LiDAR returns (NumPy array) |
| `{base}_gaussian.pkl` | Yes | Serialized Gaussian feature parameters (pickle) |
| `{base}_image.jpg` | Yes* | Single camera image |
| `{base}_image_cam0.jpg` | Yes* | Camera 0 image (multi-camera mode) |
| `{base}_image_cam1.jpg` | No | Camera 1 image (optional second camera) |
| `{base}_paths.json` | No | Optional metadata; used to display the scene name |

\* Provide either `{base}_image.jpg` (single-camera) **or** `{base}_image_cam0.jpg` / `{base}_image_cam1.jpg` (multi-camera). Both patterns are auto-detected.

**Example directory layout:**

```
vis_data/
├── 0_gt.pcd.bin.npy
├── 0_pred.pcd.bin.npy
├── 0_lidar.pcd.bin.npy
├── 0_gaussian.pkl
├── 0_image_cam0.jpg
├── 0_image_cam1.jpg
├── 0_paths.json
├── 1_gt.pcd.bin.npy
├── 1_pred.pcd.bin.npy
...
```

---

## Installation

### Prerequisites

- **VS Code** 1.75+ or **Cursor**
- **Node.js** 16+ and **npm** (for building from source)
- **Python 3.8+** with `numpy` installed:

  ```bash
  pip install numpy
  ```

### Run in Development Mode (recommended for contributors)

1. **Install Node dependencies:**

   ```bash
   cd vis-extension
   npm install
   ```

2. **Open the extension folder in VS Code:**

   ```bash
   code vis-extension
   ```

3. **Press `F5`** to launch the Extension Development Host. A new VS Code window opens with the extension active.

### Package and Install as `.vsix`

1. Install the VS Code Extension Manager globally if you have not already:

   ```bash
   npm install -g @vscode/vsce
   ```

2. Build the installable package:

   ```bash
   cd vis-extension
   vsce package
   ```

   This produces a file such as `gaussianformer-visualizer-x.y.z.vsix`.

3. Install the package in VS Code:

   - Open the Extensions panel (`Ctrl+Shift+X`).
   - Click the **`···`** menu → **Install from VSIX…**
   - Select the `.vsix` file.

---

## Usage

### Open the Visualizer

**Option A — Command Palette:**

1. Press `Ctrl+Shift+P` (macOS: `Cmd+Shift+P`) to open the Command Palette.
2. Type and select **`GaussianFormer: Open Visualizer`**.

**Option B — Explorer Context Menu:**

1. In the VS Code Explorer sidebar, right-click any folder.
2. Select **`GaussianFormer: Open Visualizer`**.

### Load a Data Directory

1. In the Visualizer panel that opens, click **📁 打开文件夹** ("Open Folder").
2. Navigate to a directory that contains your `*_gt.pcd.bin.npy` / `*_pred.pcd.bin.npy` / `*_gaussian.pkl` files.
3. The extension scans the folder, populates the frame list, and loads the first frame automatically.

---

## Configuration

The following settings are available under **File → Preferences → Settings** (search for `gaussianVis`):

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `gaussianVis.pythonPath` | `string` | `"python"` | Path to the Python executable used for reading `.npy` and `.pkl` files. Override this if your environment requires a virtualenv or conda Python (e.g. `/home/user/.venv/bin/python`). |
| `gaussianVis.defaultMaxPoints` | `number` | `100000` | Default maximum number of points rendered per point-cloud viewport. Lower this value on machines with limited GPU memory. |

**Example `settings.json` snippet:**

```json
{
  "gaussianVis.pythonPath": "/opt/conda/envs/gaussianformer/bin/python",
  "gaussianVis.defaultMaxPoints": 50000
}
```

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `←` | Navigate to the previous frame |
| `→` | Navigate to the next frame |
| `Space` | Toggle automatic playback on / off |

Shortcuts are active when the Visualizer panel has focus.

---

## Notes

- **Gaussian visualization** renders up to **5 000 ellipsoids** as instanced 3D spheres using Three.js WebGL. This is intentionally different from the standalone Qt/Open3D tool, which draws true ellipsoid meshes; the instanced-sphere approach prioritises interactive frame rates inside the VS Code webview sandbox.
- **Point clouds** are rendered as colored scatter plots using Three.js `Points` geometry with WebGL, keeping the dependency footprint minimal (no native bindings required).
- Large scenes with dense LiDAR returns may benefit from reducing `gaussianVis.defaultMaxPoints` to maintain smooth interaction.
- The Z ×10 scaling applies to all three 3D viewports simultaneously and does not modify the underlying data.
