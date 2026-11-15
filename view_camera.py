"""Project display camera: rotation only, always equal physical XYZ scale."""
import math
import numpy as np

DEFAULT_ELEVATION=30.0
DEFAULT_AZIMUTH=8.0

def settings(elevation_deg=DEFAULT_ELEVATION,azimuth_deg=DEFAULT_AZIMUTH):
    elevation_deg=float(elevation_deg);azimuth_deg=float(azimuth_deg)
    if not math.isfinite(elevation_deg) or not math.isfinite(azimuth_deg):
        raise ValueError('Camera angles must be finite')
    if not 0<=elevation_deg<=90:
        raise ValueError('elevation_deg must be 0 (horizontal) through 90 (top-down)')
    return {'projection':'orthographic','elevation_deg':elevation_deg,
            'azimuth_deg':azimuth_deg%360.0,'axis_scale_xyz':[1.0,1.0,1.0],
            'z_display_scale':1.0,'angle_convention':'azimuth 0 looks along +X; elevation measured down from horizontal'}

def require_equal_axes(zscale):
    if not math.isfinite(float(zscale)) or float(zscale)!=1.0:
        raise ValueError('Equal XYZ scale required: zscale must be 1; change camera angles instead')

def basis(elevation_deg=DEFAULT_ELEVATION,azimuth_deg=DEFAULT_AZIMUTH):
    camera=settings(elevation_deg,azimuth_deg)
    e,a=np.radians([camera['elevation_deg'],camera['azimuth_deg']])
    forward=np.array([np.cos(e)*np.cos(a),np.cos(e)*np.sin(a),-np.sin(e)])
    # Analytic right vector is well defined even at the exact top-down endpoint.
    right=np.array([np.sin(a),-np.cos(a),0.])
    return np.stack([right,np.cross(right,forward),forward],axis=1)
