/**
 * panel.js  –  WebView client for GaussianFormer Visualizer
 * Requires three-bundle.js (IIFE) loaded before this script.
 */
'use strict';

const vscode = acquireVsCodeApi();
function vscodeLog(msg, level) {
  vscode.postMessage({ cmd:'log', message:String(msg), level:level||'info' });
  if (level==='error') console.error('[GVis]',msg); else console.log('[GVis]',msg);
}
window.onerror = (msg,src,line)=>vscodeLog('Uncaught: '+msg+' @'+src+':'+line,'error');
window.addEventListener('unhandledrejection',e=>vscodeLog('UnhandledRejection: '+(e.reason||e),'error'));

// ── Label definitions ─────────────────────────────────────────────────────────
const LABEL_COLORS = {
  0:[1,0,0],1:[0,1,0],2:[0,0,1],3:[1,1,0],4:[1,0,1],5:[0,1,1],
  6:[.5,.5,.5],7:[1,.5,0],8:[.5,0,1],9:[0,.5,0],10:[1,0,.5],
  11:[.5,1,0],12:[0,.5,1],13:[.5,0,.5],14:[1,.5,.5],15:[.5,1,.5],
  16:[.5,.5,1],17:[1,1,.5],18:[.8,.2,.2],19:[.2,.8,.2],20:[.2,.2,.8],
  21:[.8,.8,.2],22:[.8,.2,.8],23:[.2,.8,.8],24:[.3,.3,.3],
  25:[.7,.3,0],26:[0,0,0],
};
const LABEL_NAMES = {
  0:'ignore',1:'asphalt',2:'cement',3:'epoxy_floor',4:'brick_road',
  5:'gravel',6:'cobbles',7:'grass',8:'dirt',9:'hard_sand',10:'soft_sand',
  11:'water',12:'ice',13:'snow',14:'other_surface',15:'road_noise',
  16:'bumper',17:'manhole_cover',18:'steel_plate',19:'drain',20:'road_beam',
  21:'railway',22:'step',23:'other_bump',24:'moving_obstacle',
  25:'fixed_obstacle',26:'ignore',
};

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  frames:[], currentFrameIdx:-1, dataDir:null,
  ignoreLabels:[26], isPlaying:false, playInterval:null,
  threeReady:false, pendingFrameData:null,
  loadDebounceTimer: null,
  sensorCalib: null,
  pathsInfo: null,
  zScaleApplied: false,
  gaussianZScaleFactor: 1,
  leftViewMode: '真值',       // 真值 | 轨迹transformer | mesh真值
  rightViewMode: '预测',      // 预测 | mesh预测
  lastFrameData: null,        // cache for instant left/right-view mode switch
};
const Z_SCALE_FACTOR = 5.0;  // must match vis_helper.py
const imgPaneState = { scale: 1, tx: 0, ty: 0 };
const scenes = [null,null,null,null];
// Per-scene flag: auto-fit camera only on first cloud render (not on frame switch)
const cameraInitialized = [false,false,false,false];
const CANVAS_IDS = ['gtCanvas','predCanvas','lidarCanvas','gaussianCanvas'];
const rawPts  = [null,null,null];
const rawLbls = [null,null,null];
let gaussianCenters = null;
let lastGaussianGeom = null;  // {centers,scales,quats,opas,n} for low-opacity boxes
let syncViews=true, syncLock=false;

// ── Pins: array per scene of { world:THREE.Vector3, el:HTMLElement } ──────────
const pinStore = [[],[],[],[]];

// ── Tooltip ───────────────────────────────────────────────────────────────────
let _tip = null;
function tip() {
  if (!_tip) {
    _tip = document.createElement('div');
    _tip.style.cssText='position:fixed;pointer-events:none;display:none;'+
      'background:rgba(0,0,0,0.85);color:#fff;font-size:12px;font-family:monospace;'+
      'padding:4px 10px;border-radius:4px;z-index:9999;white-space:pre;line-height:1.6;';
    document.body.appendChild(_tip);
  }
  return _tip;
}
function showTip(x,y,html) {
  const t=tip(); t.innerHTML=html; t.style.display='block';
  const vw=window.innerWidth,vh=window.innerHeight;
  t.style.left=((x+14+160>vw)?x-170:x+14)+'px';
  t.style.top=((y+14+90>vh)?y-100:y+14)+'px';
}
function hideTip() { tip().style.display='none'; clearImageProjection(); }

// ── Sensor calib / image reprojection ────────────────────────────────────────
function displayToVcs(x, y, z, sceneIdx) {
  if (sceneIdx === 3 && state.gaussianZScaleFactor && state.gaussianZScaleFactor !== 1) {
    return { x, y, z: z / state.gaussianZScaleFactor };
  }
  if (state.zScaleApplied) {
    return { x, y, z: z / Z_SCALE_FACTOR };
  }
  return { x, y, z };
}

function projectDisplayPointToImage(displayPt, sceneIdx) {
  if (!state.sensorCalib) return null;
  const vcs = displayToVcs(displayPt.x, displayPt.y, displayPt.z, sceneIdx);
  return projectVcsPointToImage(vcs, state.sensorCalib);
}

function projectVcsPointToImage(pt, cache) {
  if (!cache || !cache.T_cam_vcs) return null;
  const T = cache.T_cam_vcs;
  const fu = cache.fu, fv = cache.fv, cu = cache.cu, cv = cache.cv;
  const ru = cache.ru, rv = cache.rv;
  const k1 = cache.k1, k2 = cache.k2, k3 = cache.k3, k4 = cache.k4;

  const px = pt.x, py = pt.y, pz = pt.z;
  const X = T[0][0]*px + T[0][1]*py + T[0][2]*pz + T[0][3];
  const Y = T[1][0]*px + T[1][1]*py + T[1][2]*pz + T[1][3];
  const Z = T[2][0]*px + T[2][1]*py + T[2][2]*pz + T[2][3];
  if (Z <= 0.1) return null;

  const x = X / Z, y = Y / Z;
  const r = Math.sqrt(x*x + y*y);
  const theta = Math.atan(r);
  const theta2 = theta * theta;
  const theta4 = theta2 * theta2;
  const theta6 = theta4 * theta2;
  const theta8 = theta4 * theta4;
  const theta_d = theta * (1 + k1*theta2 + k2*theta4 + k3*theta6 + k4*theta8);
  let x_d, y_d;
  if (r < 1e-8) { x_d = 0; y_d = 0; }
  else {
    const scale = theta_d / r;
    x_d = x * scale;
    y_d = y * scale;
  }
  const u = fu * x_d + cu;
  const v = fv * y_d + cv;
  if (u < 0 || u >= ru || v < 0 || v >= rv) return null;
  return { u, v };
}

function imagePixelToLayerXY(u, v) {
  const layer = document.getElementById('imgTransformLayer');
  const img  = document.getElementById('img1');
  if (!layer || !img) return null;
  // Use layout size (unaffected by layer pan/zoom transform), not getBoundingClientRect().
  const paneW = layer.offsetWidth, paneH = layer.offsetHeight;
  if (paneW <= 0 || paneH <= 0) return null;
  const nw = img.naturalWidth || state.sensorCalib?.ru || 1;
  const nh = img.naturalHeight || state.sensorCalib?.rv || 1;
  const baseScale = Math.min(paneW / nw, paneH / nh);
  const dispW = nw * baseScale;
  const dispH = nh * baseScale;
  const offX = (paneW - dispW) / 2;
  const offY = (paneH - dispH) / 2;
  return {
    x: offX + (u / nw) * dispW,
    y: offY + (v / nh) * dispH,
  };
}

// Map layer-local letterbox coords to pane coords (marker lives outside transform layer).
function layerXYToPaneXY(layerX, layerY) {
  const pane = document.getElementById('imagePane1');
  if (!pane) return null;
  const paneW = pane.offsetWidth, paneH = pane.offsetHeight;
  if (paneW <= 0 || paneH <= 0) return null;
  const { scale, tx, ty } = imgPaneState;
  const cx = paneW / 2, cy = paneH / 2;
  return {
    x: cx + (layerX - cx) * scale + tx,
    y: cy + (layerY - cy) * scale + ty,
  };
}

function showImageProjection(displayPt, extraText, sceneIdx) {
  if (!state.sensorCalib) { clearImageProjection(); return; }
  const uv = projectDisplayPointToImage(displayPt, sceneIdx ?? hoverSync.srcIdx);
  const marker = document.getElementById('imgMarker');
  const tag = document.getElementById('imgCoordTag');
  if (!uv || !marker || !tag) { clearImageProjection(); return; }
  const layerXY = imagePixelToLayerXY(uv.u, uv.v);
  if (!layerXY) { clearImageProjection(); return; }
  const paneXY = layerXYToPaneXY(layerXY.x, layerXY.y);
  if (!paneXY) { clearImageProjection(); return; }
  marker.style.display = 'block';
  marker.style.left = paneXY.x + 'px';
  marker.style.top  = paneXY.y + 'px';
  tag.style.display = 'block';
  tag.textContent = 'u=' + Math.round(uv.u) + ', v=' + Math.round(uv.v) +
    (extraText ? ' | ' + extraText : '');
  tag.style.left = (paneXY.x + 10) + 'px';
  tag.style.top  = (paneXY.y - 8) + 'px';
}

function clearImageProjection() {
  const marker = document.getElementById('imgMarker');
  const tag = document.getElementById('imgCoordTag');
  if (marker) marker.style.display = 'none';
  if (tag) tag.style.display = 'none';
}

function refreshImageProjectionMarker() {
  if (!hoverSync.active || hoverSync.srcIdx < 0) return;
  showImageProjection(
    { x: hoverSync.world.x, y: hoverSync.world.y, z: hoverSync.world.z },
    hoverSync.extraText || '',
    hoverSync.srcIdx
  );
}

// ── paths.json sidebar ────────────────────────────────────────────────────────
function renderPathsPanel(pathsInfo) {
  const panel = document.getElementById('pathsPanel');
  const list  = document.getElementById('pathsList');
  if (!panel || !list) return;
  list.innerHTML = '';
  if (!pathsInfo || !pathsInfo.entries || !pathsInfo.entries.length) {
    panel.classList.remove('visible');
    return;
  }
  panel.classList.add('visible');
  if (pathsInfo.scene_name) {
    const sn = document.createElement('div');
    sn.style.cssText = 'padding:2px 0 4px;color:var(--vscode-descriptionForeground,#aaa);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
    sn.title = pathsInfo.scene_name;
    sn.textContent = pathsInfo.scene_name;
    list.appendChild(sn);
  }
  pathsInfo.entries.forEach((entry, idx) => {
    const el = document.createElement('span');
    el.className = 'path-entry';
    el.title = entry.path + '\n单击：在资源管理器中定位\nShift+单击：尝试打开';
    el.innerHTML = '<span class="path-key">' + (idx + 1) + '. ' + escapeHtml(entry.label) + '</span>' +
      escapeHtml(basenamePath(entry.path));
    el.addEventListener('click', ev => {
      vscode.postMessage({
        cmd: 'openPath',
        path: entry.path,
        action: ev.shiftKey ? 'open' : 'reveal',
      });
    });
    list.appendChild(el);
  });
}

function basenamePath(p) {
  const s = String(p).replace(/\\/g, '/');
  const parts = s.split('/');
  return parts[parts.length - 1] || s;
}

// ── Decode base64 float32 ─────────────────────────────────────────────────────
function decodeF32(b64) {
  const bin=atob(b64),buf=new ArrayBuffer(bin.length),v=new Uint8Array(buf);
  for(let i=0;i<bin.length;i++) v[i]=bin.charCodeAt(i);
  return new Float32Array(buf);
}

// ── Canvas real size ──────────────────────────────────────────────────────────
function getElSize(el) {
  if(!el) return {w:400,h:300};
  const r=el.getBoundingClientRect();
  const w=r.width||el.offsetWidth||(el.parentElement&&el.parentElement.offsetWidth)||400;
  const h=r.height||el.offsetHeight||(el.parentElement&&el.parentElement.offsetHeight)||300;
  return {w:Math.max(w,1),h:Math.max(h,1)};
}

// ── Scene creation ────────────────────────────────────────────────────────────
function createScene(canvasId) {
  const canvas=document.getElementById(canvasId);
  if(!canvas){vscodeLog('canvas not found: '+canvasId,'error');return null;}
  const par=canvas.parentElement||canvas;
  const {w,h}=getElSize(par);
  const sw=(w>1)?w:400,sh=(h>1)?h:300;
  const renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:false});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
  renderer.setClearColor(0x0d0d0d,1);
  renderer.setSize(sw,sh,false);
  const camera=new THREE.PerspectiveCamera(60,sw/sh,0.01,100000);
  camera.position.set(0,-60,40); camera.up.set(0,0,1);
  const scene=new THREE.Scene(); scene.background=new THREE.Color(0x0d0d0d);
  const controls=new THREE.OrbitControls(camera,renderer.domElement);
  controls.target.set(0,0,0); controls.enableDamping=true;
  controls.dampingFactor=0.08; controls.screenSpacePanning=true; controls.update();
  scene.add(new THREE.AxesHelper(5));
  vscodeLog('scene: '+canvasId+' '+sw+'x'+sh);
  return {renderer,camera,scene,controls,currentPoints:null};
}

// ── Cross-scene hover sync ────────────────────────────────────────────────────
// When mouse hovers a point in scene i, project that world coord into scenes j≠i
// and show a ghost crosshair there every animation frame.
const hoverSync = {
  active: false,
  srcIdx: -1,
  world: new THREE.Vector3(),
  extraText: '',
};

// One ghost crosshair overlay per scene (0=GT, 1=Pred, 2=Lidar, 3=Gaussian)
// Created lazily when first needed, always attached to the pc-pane
const ghostCrosshairs = [null, null, null, null];

function getGhostCrosshair(sceneIdx) {
  if (ghostCrosshairs[sceneIdx]) return ghostCrosshairs[sceneIdx];
  const paneIds = ['gtPane','predPane','lidarPane','gaussianPane'];
  const colors  = ['#65ff65','#ff5c5c','#ff5cff','#ffcc33'];
  const pane = document.getElementById(paneIds[sceneIdx]);
  if (!pane) return null;

  const el = document.createElement('div');
  el.style.cssText = 'position:absolute;pointer-events:none;display:none;z-index:50;transform:translate(-50%,-50%);';
  // SVG crosshair — two 20px lines crossing at center, dashed
  const c = colors[sceneIdx];
  el.innerHTML =
    '<svg width="24" height="24" viewBox="-12 -12 24 24" style="overflow:visible">' +
      '<line x1="-10" y1="0" x2="10" y2="0" stroke="'+c+'" stroke-width="1.5" stroke-dasharray="3,2" opacity="0.85"/>' +
      '<line x1="0" y1="-10" x2="0" y2="10" stroke="'+c+'" stroke-width="1.5" stroke-dasharray="3,2" opacity="0.85"/>' +
      '<circle cx="0" cy="0" r="2.5" fill="none" stroke="'+c+'" stroke-width="1.2" opacity="0.85"/>' +
    '</svg>';
  pane.appendChild(el);
  ghostCrosshairs[sceneIdx] = el;
  return el;
}

// Called every frame from updatePins()
function updateGhostCrosshairs() {
  const vec = new THREE.Vector3();
  for (let si = 0; si < 4; si++) {
    const el = getGhostCrosshair(si);
    if (!el) continue;

    // Show ghost in scenes OTHER than the hover source; hide in the source
    if (!hoverSync.active || hoverSync.srcIdx === si) {
      el.style.display = 'none';
      continue;
    }

    const s = scenes[si];
    if (!s) { el.style.display = 'none'; continue; }

    // Skip hidden panes (e.g. gaussian closed)
    const pane = document.getElementById(['gtPane','predPane','lidarPane','gaussianPane'][si]);
    if (pane && pane.style.display === 'none') { el.style.display = 'none'; continue; }

    vec.copy(hoverSync.world).project(s.camera);
    if (vec.z > 1.0) { el.style.display = 'none'; continue; }  // behind camera

    const canvas = s.renderer.domElement;
    const { w, h } = getElSize(canvas.parentElement || canvas);
    const sx = (vec.x + 1) / 2 * w;
    const sy = (-vec.y + 1) / 2 * h;

    el.style.display = '';
    el.style.left    = sx + 'px';
    el.style.top     = sy + 'px';
  }
}

// ── Pin position update (called every frame) ──────────────────────────────────
function updatePins() {
  for(let si=0;si<4;si++) {
    const s=scenes[si]; if(!s||!pinStore[si].length) continue;
    const canvas=s.renderer.domElement;
    const {w,h}=getElSize(canvas.parentElement||canvas);
    const vec=new THREE.Vector3();
    for(const pin of pinStore[si]) {
      vec.copy(pin.world);
      vec.project(s.camera);
      if(vec.z>1.0) { pin.el.style.display='none'; continue; }
      pin.el.style.display='';
      const sx=(vec.x+1)/2*w;
      const sy=(-vec.y+1)/2*h;
      pin.el.style.left=sx+'px';
      pin.el.style.top=sy+'px';
    }
  }
}

// ── Animation loop ────────────────────────────────────────────────────────────
function animate() {
  requestAnimationFrame(animate);
  for(const s of scenes) {
    if(!s||!s.renderer) continue;
    const {w,h}=getElSize(s.renderer.domElement.parentElement||s.renderer.domElement);
    if(w>1&&h>1) {
      s.renderer.setSize(w,h,false);
      s.camera.aspect=w/h; s.camera.updateProjectionMatrix();
    }
    s.controls.update();
    s.renderer.render(s.scene,s.camera);
  }
  updatePins();
  updateGhostCrosshairs();
}

// ── Camera fit ────────────────────────────────────────────────────────────────
function fitCameraToScene(s) {
  if(!s) return;
  const box=new THREE.Box3();
  s.scene.traverse(o=>{if(o.isPoints||o.isInstancedMesh||o.isMesh)box.expandByObject(o);});
  if(box.isEmpty()) return;
  const center=box.getCenter(new THREE.Vector3());
  const size=box.getSize(new THREE.Vector3());
  const maxDim=Math.max(size.x,size.y,size.z);
  if(!isFinite(maxDim)||maxDim<0.001) return;
  s.camera.near=maxDim/2000; s.camera.far=maxDim*300; s.camera.updateProjectionMatrix();
  const dist=(maxDim/2/Math.tan(s.camera.fov*Math.PI/360))*2.0;
  s.controls.target.copy(center);
  s.camera.position.set(center.x,center.y-dist*0.5,center.z+dist*0.4);
  s.camera.up.set(0,0,1); s.camera.lookAt(center); s.controls.update();
}

/** Fit camera from Gaussian centers only (InstancedMesh bbox is unreliable / unit-sphere sized). */
function fitCameraToCenters(s, centers, n) {
  if (!s || !centers || !n) return;
  let minX=Infinity,minY=Infinity,minZ=Infinity,maxX=-Infinity,maxY=-Infinity,maxZ=-Infinity;
  for (let i=0;i<n;i++) {
    const x=centers[i*3], y=centers[i*3+1], z=centers[i*3+2];
    if (!isFinite(x)||!isFinite(y)||!isFinite(z)) continue;
    if (x<minX)minX=x; if (x>maxX)maxX=x;
    if (y<minY)minY=y; if (y>maxY)maxY=y;
    if (z<minZ)minZ=z; if (z>maxZ)maxZ=z;
  }
  if (!isFinite(minX)) return;
  const center = new THREE.Vector3((minX+maxX)/2, (minY+maxY)/2, (minZ+maxZ)/2);
  const sizeX = Math.max(maxX-minX, 0.5);
  const sizeY = Math.max(maxY-minY, 0.5);
  const sizeZ = Math.max(maxZ-minZ, 0.5);
  const maxDim = Math.max(sizeX, sizeY, sizeZ);
  s.camera.near=maxDim/2000; s.camera.far=maxDim*300; s.camera.updateProjectionMatrix();
  const dist=(maxDim/2/Math.tan(s.camera.fov*Math.PI/360))*2.0;
  s.controls.target.copy(center);
  s.camera.position.set(center.x, center.y-dist*0.5, center.z+dist*0.4);
  s.camera.up.set(0,0,1); s.camera.lookAt(center); s.controls.update();
}

function copyCameraView(src, dst) {
  if (!src || !dst) return;
  dst.camera.position.copy(src.camera.position);
  dst.camera.quaternion.copy(src.camera.quaternion);
  dst.camera.near = src.camera.near;
  dst.camera.far = src.camera.far;
  dst.camera.updateProjectionMatrix();
  dst.controls.target.copy(src.controls.target);
  dst.controls.update();
}

// ── Clear scene objects ───────────────────────────────────────────────────────
function clearPointsFromScene(s) {
  if(!s) return;
  const rem=[];
  s.scene.traverse(o=>{
    // Keep AxesHelper / GridHelper — they are LineSegments too.
    if (o.isAxesHelper || o.isGridHelper || o.type === 'AxesHelper' || o.type === 'GridHelper') return;
    if (o.isPoints || o.isInstancedMesh) { rem.push(o); return; }
    // Only remove mesh wireframe lines we tagged; never wipe the coordinate axes.
    if ((o.isLineSegments || o.isLine) && o.userData && (o.userData.meshWire || o.userData.lowOpaBox)) rem.push(o);
  });
  rem.forEach(o=>{s.scene.remove(o);o.geometry&&o.geometry.dispose();o.material&&o.material.dispose();});
  s.currentPoints=null;
  s.wireLines=null;
}
function clearPins(sceneIdx) {
  for(const p of pinStore[sceneIdx]) p.el.remove();
  pinStore[sceneIdx]=[];
}

// ── Decode base64 int32 ───────────────────────────────────────────────────────
function decodeI32(b64) {
  if (!b64) return null;
  const bin=atob(b64),buf=new ArrayBuffer(bin.length),v=new Uint8Array(buf);
  for(let i=0;i<bin.length;i++) v[i]=bin.charCodeAt(i);
  return new Int32Array(buf);
}
// ── Decode base64 uint8 ───────────────────────────────────────────────────────
function decodeU8(b64) {
  if (!b64) return null;
  const bin=atob(b64),buf=new ArrayBuffer(bin.length),v=new Uint8Array(buf);
  for(let i=0;i<bin.length;i++) v[i]=bin.charCodeAt(i);
  return new Uint8Array(buf);
}
// ── Decode base64 uint16 (raw float16 bits) ───────────────────────────────────
function decodeU16(b64) {
  if (!b64) return null;
  const bin=atob(b64),buf=new ArrayBuffer(bin.length),v=new Uint8Array(buf);
  for(let i=0;i<bin.length;i++) v[i]=bin.charCodeAt(i);
  return new Uint16Array(buf);
}
// ── Build Float32Array colors from uint8 label array ─────────────────────────
const LABEL_COLOR_LUT_F32 = (()=>{
  const lut = new Float32Array(27*3);
  const cols = [
    [1,0,0],[0,1,0],[0,0,1],[1,1,0],[1,0,1],[0,1,1],
    [.5,.5,.5],[1,.5,0],[.5,0,1],[0,.5,0],[1,0,.5],[.5,1,0],
    [0,.5,1],[.5,0,.5],[1,.5,.5],[.5,1,.5],[.5,.5,1],[1,1,.5],
    [.8,.2,.2],[.2,.8,.2],[.2,.2,.8],[.8,.8,.2],[.8,.2,.8],[.2,.8,.8],
    [.3,.3,.3],[.7,.3,0],[0,0,0],
  ];
  for(let i=0;i<27;i++){ lut[i*3]=cols[i][0]; lut[i*3+1]=cols[i][1]; lut[i*3+2]=cols[i][2]; }
  return lut;
})();
function computeColorsFromLabels(lblU8, n) {
  const out = new Float32Array(n*3);
  for(let i=0;i<n;i++) {
    const c = Math.min(lblU8[i],26)*3;
    out[i*3]=LABEL_COLOR_LUT_F32[c]; out[i*3+1]=LABEL_COLOR_LUT_F32[c+1]; out[i*3+2]=LABEL_COLOR_LUT_F32[c+2];
  }
  return out;
}
function computeColorsFromIntensity(u8, n) {
  // Turbo colormap: maps 0-255 → vivid blue→cyan→green→yellow→orange→red
  // Matches the original Qt5 tool's pyqtgraph 'turbo' colormap
  const out = new Float32Array(n*3);
  for(let i=0;i<n;i++) {
    const t = u8[i] / 255;
    // Turbo colormap approximation (4-piece polynomial, matches matplotlib turbo closely)
    let r, g, b;
    if (t < 0.25) {
      const s = t / 0.25;
      r = 0.18 + 0.22*s;
      g = 0.18 + 0.62*s;
      b = 0.56 + 0.41*s;
    } else if (t < 0.5) {
      const s = (t - 0.25) / 0.25;
      r = 0.40 + 0.55*s;
      g = 0.80 + 0.10*s;
      b = 0.97 - 0.54*s;
    } else if (t < 0.75) {
      const s = (t - 0.5) / 0.25;
      r = 0.95 + 0.00*s;
      g = 0.90 - 0.42*s;
      b = 0.43 - 0.36*s;
    } else {
      const s = (t - 0.75) / 0.25;
      r = 0.95 - 0.30*s;
      g = 0.48 - 0.45*s;
      b = 0.07 - 0.04*s;
    }
    out[i*3]   = Math.max(0, Math.min(1, r));
    out[i*3+1] = Math.max(0, Math.min(1, g));
    out[i*3+2] = Math.max(0, Math.min(1, b));
  }
  return out;
}

// ── Point cloud render ────────────────────────────────────────────────────────
function getPointSize(){const sl=document.getElementById('pointSizeSlider');return sl?parseFloat(sl.value):2;}

/**
 * Render a point cloud. Accepts the new compact wire format:
 *   xyzB64     : base64 float16 (Uint16 raw bits) – 2× smaller than float32
 *   lblB64     : base64 uint8  – semantic labels (0-26) or intensity (0-255)
 *   cloudType  : "semantic" | "intensity"
 *   fitCam     : bool – auto-fit camera on first render only (frame switches preserve view)
 */
function f16BitsToF32(u16) {
  const n = u16.length;
  const posF32 = new Float32Array(n);
  if (THREE.DataUtils && THREE.DataUtils.fromHalfFloat) {
    for (let i = 0; i < n; i++) posF32[i] = THREE.DataUtils.fromHalfFloat(u16[i]);
  } else {
    for (let i = 0; i < n; i++) {
      const h = u16[i], exp = (h >> 10) & 0x1f, frac = h & 0x3ff, sign = (h >> 15) ? -1 : 1;
      if (exp === 0) posF32[i] = sign * 5.96e-8 * frac;
      else if (exp === 31) posF32[i] = frac ? NaN : (sign * Infinity);
      else posF32[i] = sign * Math.pow(2, exp - 15) * (1 + frac / 1024);
    }
  }
  return posF32;
}

function renderPointCloud(sceneIdx, xyzB64, lblB64, cloudType, fitCam, opts) {
  const s=scenes[sceneIdx];
  if(!s){vscodeLog('scene['+sceneIdx+'] not ready','error');return;}
  const append = !!(opts && opts.append);
  if (!append) { clearPointsFromScene(s); clearPins(sceneIdx); }

  const u16  = decodeU16(xyzB64);
  const lblU8 = decodeU8(lblB64);
  const n = u16 ? u16.length/3 : 0;
  if(!n){vscodeLog('renderPC['+sceneIdx+'] empty');return;}
  vscodeLog('renderPC['+sceneIdx+'] n='+n+' type='+cloudType+(append?' append':''));

  const posF32 = f16BitsToF32(u16);

  if (append && rawPts[sceneIdx] && rawPts[sceneIdx].length) {
    const prev = rawPts[sceneIdx];
    const merged = new Float32Array(prev.length + posF32.length);
    merged.set(prev, 0); merged.set(posF32, prev.length);
    rawPts[sceneIdx] = merged;
    if (lblU8) {
      const prevL = rawLbls[sceneIdx] || new Int32Array(prev.length / 3);
      const mergedL = new Int32Array(prevL.length + lblU8.length);
      mergedL.set(prevL, 0);
      for (let i = 0; i < lblU8.length; i++) mergedL[prevL.length + i] = lblU8[i];
      rawLbls[sceneIdx] = mergedL;
    }
  } else {
    rawPts[sceneIdx] = posF32;
    rawLbls[sceneIdx] = lblU8 ? new Int32Array(lblU8) : null;
  }
  vscodeLog('rawLbls['+sceneIdx+'] length='+(rawLbls[sceneIdx]?rawLbls[sceneIdx].length:0));

  const colors = (cloudType==='intensity')
    ? computeColorsFromIntensity(lblU8||new Uint8Array(n), n)
    : computeColorsFromLabels(lblU8||new Uint8Array(n), n);

  const geo=new THREE.BufferGeometry();
  if(THREE.Float16BufferAttribute) {
    geo.setAttribute('position', new THREE.Float16BufferAttribute(u16, 3));
  } else {
    geo.setAttribute('position', new THREE.BufferAttribute(posF32, 3));
  }
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));

  const mat=new THREE.PointsMaterial({size:getPointSize(),sizeAttenuation:false,vertexColors:true});
  const pts=new THREE.Points(geo,mat);
  s.scene.add(pts); s.currentPoints=pts;
  // Raycast uses concatenated f32 positions when layers are appended
  s._posF32 = rawPts[sceneIdx];
  if(fitCam && !cameraInitialized[sceneIdx]) {
    fitCameraToScene(s);
    cameraInitialized[sceneIdx] = true;
  }
}

function setGtViewLabel(text) {
  const el = document.getElementById('gtViewLabel');
  if (el) el.textContent = text;
}

function updateLeftLegend(mode, payload) {
  const el = document.getElementById('trajLegend');
  if (!el) return;
  if (mode === '轨迹transformer') {
    const traj = payload || {};
    const gtN = traj.gt ? traj.gt.count : 0;
    const predN = traj.pred ? traj.pred.count : 0;
    el.innerHTML =
      '<b>Legend</b><br>' +
      '<span style="color:#4dd599">■</span> traj_gt (' + gtN + ')<br>' +
      '<span style="color:#ff6b6b">■</span> traj_pred (' + predN + ')';
    el.style.display = 'block';
    return;
  }
  if (mode === 'mesh真值') {
    const mg = payload || {};
    const meshN = mg.mesh ? mg.mesh.count : 0;
    const edgeN = mg.mesh ? (mg.mesh.edge_count || 0) : 0;
    const trajN = mg.trajMesh ? mg.trajMesh.count : 0;
    el.innerHTML =
      '<b>Legend</b><br>' +
      '<span style="color:#65ff65">■</span> mesh_gt (' + meshN + ')<br>' +
      '<span style="color:#9ec9ff">─</span> mesh edges (' + edgeN + ')<br>' +
      '<span style="color:#ffd166">■</span> traj_gt_mesh (' + trajN + ')';
    el.style.display = 'block';
    return;
  }
  el.style.display = 'none';
  el.innerHTML = '';
}

/** Merge multiple semantic clouds into one wire payload (single Points = correct hover). */
function mergeSemanticClouds(clouds) {
  const parts = (clouds || []).filter(c => c && c.count > 0 && c.xyz_b64);
  if (!parts.length) return null;
  if (parts.length === 1) return parts[0];
  let total = 0;
  const decoded = parts.map(c => {
    const u16 = decodeU16(c.xyz_b64);
    const lbl = decodeU8(c.lbl_b64) || new Uint8Array((u16.length / 3) | 0);
    total += (u16.length / 3) | 0;
    return { u16, lbl };
  });
  const u16All = new Uint16Array(total * 3);
  const lblAll = new Uint8Array(total);
  let o = 0;
  for (const p of decoded) {
    u16All.set(p.u16, o * 3);
    lblAll.set(p.lbl, o);
    o += p.lbl.length;
  }
  // Re-encode as base64 for renderPointCloud
  const u16Bytes = new Uint8Array(u16All.buffer);
  const lblBytes = lblAll;
  let u16Bin = '', lblBin = '';
  for (let i = 0; i < u16Bytes.length; i++) u16Bin += String.fromCharCode(u16Bytes[i]);
  for (let i = 0; i < lblBytes.length; i++) lblBin += String.fromCharCode(lblBytes[i]);
  return {
    xyz_b64: btoa(u16Bin),
    lbl_b64: btoa(lblBin),
    cloud_type: 'semantic',
    count: total,
  };
}

/** Render mesh wireframe edges (THREE.LineSegments) in a scene. */
function renderMeshWireframe(sceneIdx, edgesB64) {
  try {
    const s = scenes[sceneIdx];
    if (!s || !edgesB64) return;
    const u16 = decodeU16(edgesB64);
    if (!u16 || u16.length < 6) return;
    const posF32 = f16BitsToF32(u16);
    const nVert = (posF32.length / 3) | 0;
    if (nVert < 2) return;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(posF32, 3));
    const mat = new THREE.LineBasicMaterial({
      color: 0x9ec9ff,
      transparent: true,
      opacity: 0.55,
      depthWrite: false,
    });
    const lines = new THREE.LineSegments(geo, mat);
    lines.userData.meshWire = true;  // so clearPointsFromScene won't remove AxesHelper
    s.scene.add(lines);
    s.wireLines = lines;
    vscodeLog('mesh wireframe edges=' + ((nVert / 2) | 0));
  } catch (e) {
    if (typeof console !== 'undefined' && console.debug) console.debug('[GVis] mesh wireframe skipped', e);
    vscodeLog('mesh wireframe skipped: ' + e);
  }
}

/** Render left (GT) pane according to dropdown mode — mirrors v6 update_gt_view_mode. */
function renderLeftView(fitCam) {
  const d = state.lastFrameData;
  const s0 = scenes[0];
  if (!d || !s0) return;
  const mode = state.leftViewMode || '真值';
  clearPointsFromScene(s0); clearPins(0);
  rawPts[0] = null; rawLbls[0] = null; s0._posF32 = null;

  if (mode === '轨迹transformer') {
    const tt = d.trajTransformer || {};
    const merged = mergeSemanticClouds([tt.gt, tt.pred]);
    if (merged) {
      renderPointCloud(0, merged.xyz_b64, merged.lbl_b64, 'semantic', !!fitCam);
    }
    setGtViewLabel('Trajectory Transformer');
    updateLeftLegend(mode, tt);
    if (!merged) setInfo('当前帧无 traj_gt / traj_pred', d.sceneName || '');
    return;
  }

  if (mode === 'mesh真值') {
    const mg = d.meshGt || {};
    // 顶点（mesh + 可选 traj_gt_mesh）+ mesh 网格细线
    const merged = mergeSemanticClouds([mg.mesh, mg.trajMesh]);
    if (merged) {
      renderPointCloud(0, merged.xyz_b64, merged.lbl_b64, 'semantic', !!fitCam);
      if (s0.currentPoints && s0.currentPoints.material) {
        s0.currentPoints.material.size = Math.max(1, getPointSize() * 0.7);
      }
    }
    if (mg.mesh && mg.mesh.edges_b64) {
      renderMeshWireframe(0, mg.mesh.edges_b64);
    }
    setGtViewLabel('Mesh GT');
    updateLeftLegend(mode, mg);
    if (!merged && !(mg.mesh && mg.mesh.edges_b64)) {
      setInfo('当前帧无 mesh_gt / traj_gt_mesh', d.sceneName || '');
    }
    return;
  }

  if (d.gt && d.gt.count > 0) {
    renderPointCloud(0, d.gt.xyz_b64, d.gt.lbl_b64, d.gt.cloud_type || 'semantic', !!fitCam);
  }
  setGtViewLabel('GT');
  updateLeftLegend('真值', null);
}

function leftViewInfoText(d) {
  if (!d) return '';
  if (state.leftViewMode === '轨迹transformer' && d.trajTransformer) {
    return d.trajTransformer.info || d.info || '';
  }
  if (state.leftViewMode === 'mesh真值' && d.meshGt) {
    return d.meshGt.info || d.info || '';
  }
  return d.info || '';
}

function composeInfoText(d) {
  if (!d) return '';
  const parts = [];
  const left = leftViewInfoText(d);
  if (left) parts.push(left);
  if (state.rightViewMode === 'mesh预测' && d.meshPred && d.meshPred.hasMesh) {
    parts.push(d.meshPred.info || '');
  }
  return parts.filter(Boolean).join(' | ');
}

function setPredViewLabel(text) {
  const el = document.getElementById('predViewLabel');
  if (el) el.textContent = text;
}

function updatePredLegend(mode, payload) {
  const el = document.getElementById('predLegend');
  if (!el) return;
  if (mode === 'mesh预测') {
    const mp = payload || {};
    const meshN = mp.mesh ? mp.mesh.count : 0;
    const edgeN = mp.mesh ? (mp.mesh.edge_count || 0) : 0;
    const trajN = mp.trajMesh ? mp.trajMesh.count : 0;
    el.innerHTML =
      '<b>Legend</b><br>' +
      '<span style="color:#ff8a8a">■</span> mesh_pred (' + meshN + ')<br>' +
      '<span style="color:#9ec9ff">─</span> mesh edges (' + edgeN + ')<br>' +
      '<span style="color:#ffd166">■</span> traj_pred_mesh (' + trajN + ')';
    el.style.display = 'block';
    return;
  }
  el.style.display = 'none';
  el.innerHTML = '';
}

/** Render right (Pred) pane — OCC prediction or mesh预测, mirroring left mesh真值. */
function renderRightView(fitCam) {
  const d = state.lastFrameData;
  const s1 = scenes[1];
  if (!d || !s1) return;
  const mode = state.rightViewMode || '预测';
  try {
    clearPointsFromScene(s1); clearPins(1);
    rawPts[1] = null; rawLbls[1] = null; s1._posF32 = null;

    if (mode === 'mesh预测') {
      const mp = d.meshPred || {};
      const merged = mergeSemanticClouds([mp.mesh, mp.trajMesh]);
      if (merged) {
        renderPointCloud(1, merged.xyz_b64, merged.lbl_b64, 'semantic', !!fitCam);
        if (s1.currentPoints && s1.currentPoints.material) {
          s1.currentPoints.material.size = Math.max(1, getPointSize() * 0.7);
        }
      }
      if (mp.mesh && mp.mesh.edges_b64) {
        renderMeshWireframe(1, mp.mesh.edges_b64);
      }
      setPredViewLabel('Mesh Pred');
      updatePredLegend(mode, mp);
      if (!merged && !(mp.mesh && mp.mesh.edges_b64)) {
        if (typeof console !== 'undefined' && console.debug) {
          console.debug('[GVis] pred mesh missing or empty, skip display');
        }
        vscodeLog('pred mesh skipped (missing/empty)');
      }
      return;
    }

    if (d.pred && d.pred.count > 0) {
      renderPointCloud(1, d.pred.xyz_b64, d.pred.lbl_b64, d.pred.cloud_type || 'semantic', !!fitCam);
    }
    setPredViewLabel('Prediction');
    updatePredLegend('预测', null);
  } catch (e) {
    if (typeof console !== 'undefined' && console.debug) console.debug('[GVis] pred view skip', e);
    vscodeLog('pred view skipped: ' + e);
    try { clearPointsFromScene(s1); } catch (_) {}
    setPredViewLabel(mode === 'mesh预测' ? 'Mesh Pred' : 'Prediction');
    updatePredLegend(mode, d.meshPred || null);
  }
}

// ── Gaussian render ───────────────────────────────────────────────────────────
function clearLowOpaBoxes(s) {
  if (!s) return;
  const rem = [];
  s.scene.traverse(o => { if (o.userData && o.userData.lowOpaBox) rem.push(o); });
  rem.forEach(o => {
    s.scene.remove(o);
    if (o.geometry) o.geometry.dispose();
    if (o.material) o.material.dispose();
  });
}

/** Instance matrix for one Gaussian ellipsoid.
 *  When zFactor≠1, apply world-Z stretch only: T * Scale(1,1,f) * R * S
 *  (centers.z are already multiplied by f in Python).
 */
function setOrientedGaussianMatrix(outMat, x, y, z, qw, qx, qy, qz, sx, sy, sz, zFactor) {
  const t = _gMatT.makeTranslation(x, y, z);
  const r = _gMatR.makeRotationFromQuaternion(_gQuat.set(qx, qy, qz, qw));
  const s = _gMatS.makeScale(sx, sy, sz);
  const f = (zFactor && zFactor !== 1) ? zFactor : 1;
  if (f === 1) {
    outMat.copy(t).multiply(r).multiply(s);
  } else {
    outMat.copy(t).multiply(_gMatZ.makeScale(1, 1, f)).multiply(r).multiply(s);
  }
  return outMat;
}
const _gMatT = new THREE.Matrix4();
const _gMatR = new THREE.Matrix4();
const _gMatS = new THREE.Matrix4();
const _gMatZ = new THREE.Matrix4();
const _gQuat = new THREE.Quaternion();
const _gInstMat = new THREE.Matrix4();

/** Draw red oriented AABB wireframes for Gaussians with opacity < threshold. */
function updateLowOpacityBoxes() {
  const s = scenes[3];
  if (!s) return;
  clearLowOpaBoxes(s);

  const chk = document.getElementById('chkLowOpaBox');
  if (!chk || !chk.checked || !lastGaussianGeom) return;

  const thr = parseFloat(document.getElementById('lowOpaThrInput')?.value || '0.05');
  const thrSafe = isFinite(thr) ? thr : 0.05;
  const { centers, scales, quats, opas, n } = lastGaussianGeom;
  if (!opas || !n) return;

  const idxs = [];
  for (let i = 0; i < n; i++) {
    if (opas[i] < thrSafe) idxs.push(i);
  }
  if (!idxs.length) {
    vscodeLog('lowOpaBoxes: 0 / ' + n + ' below thr=' + thrSafe);
    return;
  }

  // Unit box [-1,1]^3 matches SphereGeometry(radius=1) extents → same scale = OBB of ellipsoid
  const boxGeo = new THREE.BoxGeometry(2, 2, 2);
  const mat = new THREE.MeshBasicMaterial({
    color: 0xff2222,
    wireframe: true,
    transparent: true,
    opacity: 0.95,
    depthTest: true,
  });
  const mesh = new THREE.InstancedMesh(boxGeo, mat, idxs.length);
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  mesh.userData.lowOpaBox = true;
  mesh.frustumCulled = false;

  const zf = state.gaussianZScaleFactor || 1;
  for (let k = 0; k < idxs.length; k++) {
    const i = idxs[k];
    const sx = Math.min(Math.max(Math.abs(scales[i * 3]), 0.01), 5.0);
    const sy = Math.min(Math.max(Math.abs(scales[i * 3 + 1]), 0.01), 5.0);
    const sz = Math.min(Math.max(Math.abs(scales[i * 3 + 2]), 0.01), 5.0);
    setOrientedGaussianMatrix(
      _gInstMat,
      centers[i * 3], centers[i * 3 + 1], centers[i * 3 + 2],
      quats[i * 4], quats[i * 4 + 1], quats[i * 4 + 2], quats[i * 4 + 3],
      sx, sy, sz, zf
    );
    mesh.setMatrixAt(k, _gInstMat);
  }
  mesh.instanceMatrix.needsUpdate = true;
  s.scene.add(mesh);
  vscodeLog('lowOpaBoxes: ' + idxs.length + ' / ' + n + ' below thr=' + thrSafe);
}

function setLowOpaControlsVisible(vis) {
  // Controls live inside #gaussianPane; visibility follows the pane.
}

function renderGaussianStats(data) {
  const el = document.getElementById('gaussStats');
  if (!el) return;
  const counts = data && Array.isArray(data.label_counts) ? data.label_counts : null;
  const total = (data && data.count) || 0;
  if (!counts || !counts.length) {
    el.innerHTML = '<div class="gs-empty">' + (total ? ('共 ' + total + ' 个') : '无高斯 / 无类别') + '</div>';
    return;
  }
  let html = '<div class="gs-title">类别统计 · 共 ' + total + '</div>';
  for (const c of counts) {
    const id = c.id|0;
    const rgb = LABEL_COLORS[id] || [0.5, 0.5, 0.5];
    const color = 'rgb(' + Math.round(rgb[0]*255) + ',' + Math.round(rgb[1]*255) + ',' + Math.round(rgb[2]*255) + ')';
    const name = c.name || LABEL_NAMES[id] || ('label_' + id);
    html += '<div class="gs-row">' +
      '<span class="gs-dot" style="background:' + color + '"></span>' +
      '<span class="gs-name" title="' + name + '">[' + id + '] ' + name + '</span>' +
      '<span class="gs-cnt">' + c.count + '</span>' +
      '</div>';
  }
  el.innerHTML = html;
}

function clearGaussianStats() {
  const el = document.getElementById('gaussStats');
  if (el) el.innerHTML = '<div class="gs-empty">加载后显示类别统计</div>';
}

function renderGaussians(data) {
  const s=scenes[3];
  if(!s){vscodeLog('Gaussian scene[3] not ready','error');return;}
  clearPointsFromScene(s);

  const centers=decodeF32(data.centers_b64);
  const colors =decodeF32(data.colors_b64);
  const scales =decodeF32(data.scales_b64);
  const quats  =decodeF32(data.quats_b64);
  const opas   = data.opas_b64 ? decodeF32(data.opas_b64) : null;
  const n=Math.min(data.count,10000);
  if(!n){vscodeLog('Gaussian n=0'); lastGaussianGeom=null; return;}
  vscodeLog('renderGaussians n='+n+' sample colors[0..2]='+colors[0].toFixed(3)+','+colors[1].toFixed(3)+','+colors[2].toFixed(3));

  // ── InstancedMesh approach ──
  // KEY FIX: vertexColors:false so instanceColor attribute is used instead of geometry vertex colors
  const geo=new THREE.SphereGeometry(1,6,4);
  const mat=new THREE.MeshBasicMaterial({vertexColors:false,transparent:true,opacity:0.85});
  const mesh=new THREE.InstancedMesh(geo,mat,n);
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);

  const col=new THREE.Color();
  const zf = state.gaussianZScaleFactor || 1;
  for(let i=0;i<n;i++) {
    // Scales: use absolute value and clamp to reasonable range (do NOT bake z-scale into sz)
    const sx=Math.min(Math.max(Math.abs(scales[i*3]),  0.01), 5.0);
    const sy=Math.min(Math.max(Math.abs(scales[i*3+1]),0.01), 5.0);
    const sz=Math.min(Math.max(Math.abs(scales[i*3+2]),0.01), 5.0);
    // quats from python: [w,x,y,z]
    setOrientedGaussianMatrix(
      _gInstMat,
      centers[i*3], centers[i*3+1], centers[i*3+2],
      quats[i*4], quats[i*4+1], quats[i*4+2], quats[i*4+3],
      sx, sy, sz, zf
    );
    mesh.setMatrixAt(i, _gInstMat);
    col.setRGB(colors[i*3],colors[i*3+1],colors[i*3+2]);
    mesh.setColorAt(i,col);
  }
  mesh.instanceMatrix.needsUpdate=true;
  if(mesh.instanceColor) mesh.instanceColor.needsUpdate=true;

  s.scene.add(mesh); s.currentPoints=mesh;
  gaussianCenters = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    gaussianCenters[i*3]   = centers[i*3];
    gaussianCenters[i*3+1] = centers[i*3+1];
    gaussianCenters[i*3+2] = centers[i*3+2];
  }
  lastGaussianGeom = { centers, scales, quats, opas, n };
  updateLowOpacityBoxes();
  vscodeLog('Gaussian InstancedMesh added, instanceColor exists='+(!!mesh.instanceColor));
  // Prefer GT camera so road X/Y aspect matches GT/Pred; InstancedMesh bbox fit is wrong.
  if (scenes[0]) {
    copyCameraView(scenes[0], s);
    cameraInitialized[3] = true;
  } else if (!cameraInitialized[3]) {
    fitCameraToCenters(s, centers, n);
    cameraInitialized[3] = true;
  }
}

// ── Point size update ─────────────────────────────────────────────────────────
function updateAllPointSizes(size) {
  for(const s of scenes) {
    if(!s)continue;
    s.scene.traverse(o=>{if(o.isPoints&&o.material){o.material.size=size;o.material.needsUpdate=true;}});
  }
  if (state.leftViewMode === 'mesh真值' && scenes[0] && scenes[0].currentPoints && scenes[0].currentPoints.material) {
    scenes[0].currentPoints.material.size = Math.max(1, size * 0.7);
  }
  if (state.rightViewMode === 'mesh预测' && scenes[1] && scenes[1].currentPoints && scenes[1].currentPoints.material) {
    scenes[1].currentPoints.material.size = Math.max(1, size * 0.7);
  }
}

// ── GT↔Pred↔Gaussian camera sync ─────────────────────────────────────────────
function setupViewSync() {
  const syncIdxs = [0, 1, 3]; // GT, Pred, Gaussian
  for (const i of syncIdxs) {
    const src = scenes[i];
    if (!src) continue;
    src.controls.addEventListener('change', () => {
      if (!syncViews || syncLock) return;
      syncLock = true;
      for (const j of syncIdxs) {
        if (j === i) continue;
        if (j === 3 && !isGaussianOpen()) continue;
        const dst = scenes[j];
        if (!dst) continue;
        dst.camera.position.copy(src.camera.position);
        dst.camera.quaternion.copy(src.camera.quaternion);
        dst.controls.target.copy(src.controls.target);
        dst.controls.update();
      }
      syncLock = false;
    });
  }
}

// ── Hover + Click with 3D-tracked crosshair pin ───────────────────────────────
// Screen-space nearest-point search:
//   Because points are rendered with sizeAttenuation:false (pixel size),
//   raycaster world-space threshold is unreliable and produces large errors.
//   Instead we project all points to screen coords and find the nearest one
//   within PICK_RADIUS pixels — this is pixel-accurate regardless of zoom.
const PICK_RADIUS_PX = 12;  // pixels — tune if needed

function setupPointHover(canvasId,sceneIdx,labelName) {
  const canvas=document.getElementById(canvasId); if(!canvas)return;

  // Reusable projected-point cache: rebuilt only when points change
  // { ndc: Float32Array[n*2], count: n }
  let _projCache = null;
  let _projCacheForPoints = null;  // reference to currentPoints when cache was built

  function buildProjCache(s) {
    const pts = s.currentPoints;
    if (!pts || !pts.isPoints) { _projCache=null; _projCacheForPoints=null; return; }

    const pos = pts.geometry.attributes.position;
    const n   = pos.count;
    if (!_projCache || _projCount !== n || _projCacheForPoints !== pts) {
      _projCache = new Float32Array(n * 2);
      _projCount = n;
      _projCacheForPoints = pts;
    }
    const ndc = _projCache;
    const v   = new THREE.Vector3();
    // Rebuild MVP every call — camera moves every frame when damping
    const mvp = new THREE.Matrix4().multiplyMatrices(
      s.camera.projectionMatrix,
      s.camera.matrixWorldInverse
    ).multiply(pts.matrixWorld);

    for (let i=0; i<n; i++) {
      v.fromBufferAttribute(pos, i).applyMatrix4(mvp);
      ndc[i*2]   = (v.z > 1) ? Infinity : v.x;
      ndc[i*2+1] = v.y;
    }
  }
  let _projCount = 0;

  function nearestPt(e) {
    const s=scenes[sceneIdx];
    if(!s||!s.currentPoints)return null;

    const rect = canvas.getBoundingClientRect();
    const cw = rect.width, ch = rect.height;
    const mx = ((e.clientX-rect.left)/cw)*2-1;
    const my = ((e.clientY-rect.top)/ch)*-2+1;
    const rx = PICK_RADIUS_PX / cw * 2;
    const ry = PICK_RADIUS_PX / ch * 2;
    const r2 = rx*rx + ry*ry;

    // Gaussian InstancedMesh pick
    if (s.currentPoints.isInstancedMesh && gaussianCenters) {
      const n = gaussianCenters.length / 3;
      const v = new THREE.Vector3();
      const mvp = new THREE.Matrix4().multiplyMatrices(
        s.camera.projectionMatrix,
        s.camera.matrixWorldInverse
      ).multiply(s.currentPoints.matrixWorld);
      let bestIdx = -1, bestDist2 = r2;
      for (let i = 0; i < n; i++) {
        v.set(gaussianCenters[i*3], gaussianCenters[i*3+1], gaussianCenters[i*3+2]).applyMatrix4(mvp);
        if (v.z > 1) continue;
        const dx = v.x - mx, dy = v.y - my;
        const d2 = dx*dx + dy*dy;
        if (d2 < bestDist2) { bestDist2 = d2; bestIdx = i; }
      }
      if (bestIdx < 0) return null;
      return {
        x: gaussianCenters[bestIdx*3],
        y: gaussianCenters[bestIdx*3+1],
        z: gaussianCenters[bestIdx*3+2],
        idx: bestIdx,
        lbl: -1,
      };
    }

    if(!s.currentPoints.isPoints)return null;

    buildProjCache(s);
    if(!_projCache) return null;

    let bestIdx=-1, bestDist2=r2;
    const ndc=_projCache, n=_projCount;
    for (let i=0; i<n; i++) {
      const dx=ndc[i*2]-mx, dy=ndc[i*2+1]-my;
      const d2=dx*dx+dy*dy;
      if(d2<bestDist2){ bestDist2=d2; bestIdx=i; }
    }
    if(bestIdx<0) return null;

    const pos = s.currentPoints.geometry.attributes.position;
    return {
      x: pos.getX(bestIdx), y: pos.getY(bestIdx), z: pos.getZ(bestIdx),
      idx: bestIdx,
      lbl: (rawLbls[sceneIdx]&&bestIdx<rawLbls[sceneIdx].length)?rawLbls[sceneIdx][bestIdx]:-1,
    };
  }

  // NDC cache is invalidated automatically because buildProjCache checks s.currentPoints reference

  // ── Hover: floating tooltip + cross-scene ghost crosshair ──
  canvas.addEventListener('mousemove',e=>{
    const pt=nearestPt(e);
    if(pt) {
      const ls=pt.lbl>=0?' | '+pt.lbl+' '+(LABEL_NAMES[pt.lbl]||'?'):'';
      showTip(e.clientX,e.clientY,
        '<b>'+labelName+'</b>\nx: <b>'+pt.x.toFixed(3)+'</b>\ny: <b>'+pt.y.toFixed(3)+
        '</b>\nz: <b>'+pt.z.toFixed(3)+'</b>'+ls);
      hoverSync.active = true;
      hoverSync.srcIdx = sceneIdx;
      hoverSync.world.set(pt.x, pt.y, pt.z);
      hoverSync.extraText = labelName + ' (' + pt.x.toFixed(2) + ',' + pt.y.toFixed(2) + ',' + pt.z.toFixed(2) + ')';
      showImageProjection(pt, hoverSync.extraText, sceneIdx);
    } else {
      hideTip();
      if (hoverSync.srcIdx === sceneIdx) hoverSync.active = false;
    }
  });
  canvas.addEventListener('mouseleave', () => {
    hideTip();
    if (hoverSync.srcIdx === sceneIdx) hoverSync.active = false;
  });

  // ── Click: add 3D-tracked crosshair pin ──
  canvas.addEventListener('click',e=>{
    // Ignore if it was a drag (OrbitControls moves > 3px)
    if(e._wasDrag)return;
    const pt=nearestPt(e);
    if(!pt)return;

    const pane=canvas.parentElement;
    const lblStr=pt.lbl>=0?' '+pt.lbl+' '+(LABEL_NAMES[pt.lbl]||'?'):'';
    const text=pt.x.toFixed(2)+','+pt.y.toFixed(2)+','+pt.z.toFixed(2)+lblStr;

    // Build pin element: crosshair + label
    const pin=document.createElement('div');
    pin.style.cssText='position:absolute;pointer-events:none;z-index:100;transform:translate(-50%,-50%);';
    pin.innerHTML=
      '<span style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);'+
        'color:#ffe000;font-size:22px;font-weight:900;text-shadow:0 0 3px #000;line-height:1;'+
        'font-family:monospace;">+</span>'+
      '<div style="position:absolute;left:14px;top:-8px;background:rgba(0,0,0,0.78);'+
        'color:#ffe000;font-size:10px;font-family:monospace;padding:2px 5px;border-radius:3px;'+
        'white-space:nowrap;">'+text+'</div>';
    pane.appendChild(pin);

    pinStore[sceneIdx].push({
      world:new THREE.Vector3(pt.x,pt.y,pt.z),
      el:pin,
    });
  });

  // ── Double-click: clear pins ──
  canvas.addEventListener('dblclick',e=>{
    clearPins(sceneIdx); e.stopPropagation();
  });

  // ── Track drag to avoid click-on-drag ──
  let downX=0,downY=0;
  canvas.addEventListener('mousedown',e=>{downX=e.clientX;downY=e.clientY;});
  canvas.addEventListener('mouseup',e=>{
    e._wasDrag=(Math.abs(e.clientX-downX)+Math.abs(e.clientY-downY))>5;
  });
}

// ── Image pane pan/zoom ───────────────────────────────────────────────────────
function bindImageProjectionRefresh(img) {
  if (!img || img._gvisProjBound) return;
  img._gvisProjBound = true;
  img.addEventListener('load', () => refreshImageProjectionMarker());
}

function setCameraImageSrc(uri) {
  const img1 = document.getElementById('img1');
  if (!img1) return;
  bindImageProjectionRefresh(img1);
  img1.src = uri || '';
  if (img1.complete && img1.naturalWidth > 0) refreshImageProjectionMarker();
}

function setupImagePane(paneId, layerId) {
  const pane=document.getElementById(paneId),layer=document.getElementById(layerId);
  const img=document.getElementById('img1');
  if(!pane||!layer||!img)return;
  bindImageProjectionRefresh(img);
  let scale=1,tx=0,ty=0,drag=false,lx=0,ly=0;
  const apply=()=>{
    layer.style.transform='translate('+tx+'px,'+ty+'px) scale('+scale+')';
    imgPaneState.scale=scale; imgPaneState.tx=tx; imgPaneState.ty=ty;
    refreshImageProjectionMarker();
  };
  pane.addEventListener('wheel',e=>{e.preventDefault();scale=Math.max(0.05,Math.min(20,scale*(e.deltaY<0?1.15:1/1.15)));apply();},{passive:false});
  pane.addEventListener('mousedown',e=>{drag=true;lx=e.clientX;ly=e.clientY;pane.classList.add('grabbing');});
  window.addEventListener('mouseup',()=>{drag=false;pane.classList.remove('grabbing');});
  window.addEventListener('mousemove',e=>{if(!drag)return;tx+=e.clientX-lx;ty+=e.clientY-ly;lx=e.clientX;ly=e.clientY;apply();});
  pane.addEventListener('dblclick',()=>{scale=1;tx=0;ty=0;apply();});
  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver(() => refreshImageProjectionMarker());
    ro.observe(pane);
  }
}

// ── Label filter ──────────────────────────────────────────────────────────────
function buildLabelFilter() {
  const grid=document.getElementById('labelFilterGrid');if(!grid)return;grid.innerHTML='';
  for(let id=0;id<=26;id++) {
    const c=LABEL_COLORS[id]||[.5,.5,.5];
    const hex='#'+c.map(v=>Math.round(v*255).toString(16).padStart(2,'0')).join('');
    const cb=document.createElement('input');cb.type='checkbox';cb.id='lbl-'+id;cb.dataset.labelId=String(id);
    cb.checked=state.ignoreLabels.includes(id);
    cb.addEventListener('change',()=>{
      state.ignoreLabels=Array.from(document.querySelectorAll('#labelFilterGrid input:checked')).map(el=>+el.dataset.labelId);
      if(state.currentFrameIdx>=0)requestFrameLoad();
    });
    const dot=document.createElement('span');dot.className='lbl-dot';dot.style.background=hex;
    const lbl=document.createElement('label');lbl.className='lbl-cb';lbl.htmlFor=cb.id;
    lbl.title=LABEL_NAMES[id]||'lbl_'+id;lbl.append(cb,dot,' '+id);
    grid.appendChild(lbl);
  }
}

// ── Frame list ────────────────────────────────────────────────────────────────
function escapeHtml(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function frameItemLabel(f, i) {
  const base = f.displayName || f.base || '';
  const sc = (f.sceneName || '').trim();
  return sc ? (i + 1) + '. ' + base + '  |  ' + sc : (i + 1) + '. ' + base;
}
function populateFrameList(frames) {
  const list=document.getElementById('frameList');if(!list)return;list.innerHTML='';
  frames.forEach((f,i)=>{
    const div=document.createElement('div');div.className='frame-item';div.dataset.idx=String(i);
    div.title=f.displayName||f.base;
    const badges=[f.hasGt?'G':'',f.hasPred?'P':'',f.hasLidar?'L':'',f.hasGaussian?'∿':'',f.hasTraj?'T':'',f.hasMesh?'M':'',f.hasMeshPred?'m':''].filter(Boolean).join('');
    div.innerHTML=escapeHtml(frameItemLabel(f,i))+' <span class="frame-badges">'+badges+'</span>';
    div.addEventListener('click',()=>selectFrame(i));list.appendChild(div);
  });
}
function refreshFrameListItem(idx) {
  const f = state.frames[idx];
  const el = document.querySelector('.frame-item[data-idx="'+idx+'"]');
  if (!f || !el) return;
  const badges=[f.hasGt?'G':'',f.hasPred?'P':'',f.hasLidar?'L':'',f.hasGaussian?'∿':'',f.hasTraj?'T':'',f.hasMesh?'M':'',f.hasMeshPred?'m':''].filter(Boolean).join('');
  el.innerHTML=escapeHtml(frameItemLabel(f,idx))+' <span class="frame-badges">'+badges+'</span>';
}
function updateFrameListHighlight(idx) {
  document.querySelectorAll('.frame-item').forEach((el,i)=>{el.classList.toggle('active',i===idx);if(i===idx)el.scrollIntoView({block:'nearest'});});
  const lbl=document.getElementById('frameIndexLabel');if(lbl)lbl.textContent=(idx+1)+' / '+state.frames.length;
}

// ── Frame load ────────────────────────────────────────────────────────────────
function selectFrame(idx) {
  if(idx<0||idx>=state.frames.length)return;
  state.currentFrameIdx=idx;updateFrameListHighlight(idx);requestFrameLoad();
}
function isGaussianOpen() {
  const gPane=document.getElementById('gaussianPane');
  return !!(gPane && gPane.style.display !== 'none');
}
function requestGaussianLoad() {
  if (!isGaussianOpen()) return;
  const idx=state.currentFrameIdx; if(idx<0)return;
  const f=state.frames[idx];
  if(!f||!f.hasGaussian){
    clearPointsFromScene(scenes[3]); clearPins(3);
    gaussianCenters = null;
    setInfo('当前帧没有高斯文件','');
    return;
  }
  const z=document.getElementById('chkZScale')?.checked||false;
  // Must match point-cloud Z_SCALE_FACTOR (UI label says ×10, actual factor is 5)
  vscode.postMessage({cmd:'loadGaussian',frameIdx:idx,zScaleFactor:z?Z_SCALE_FACTOR:1});
}
function requestFrameLoad(immediate) {
  // Debounce: wait 80ms after last keypress before firing (prevents spamming Python)
  if (state.loadDebounceTimer) clearTimeout(state.loadDebounceTimer);
  const delay = immediate ? 0 : 80;
  state.loadDebounceTimer = setTimeout(() => {
    const idx=state.currentFrameIdx; if(idx<0)return;
    const zScale=document.getElementById('chkZScale')?.checked||false;
    // maxPoints=0 → unlimited (no downsampling)
    vscode.postMessage({cmd:'loadFrame',frameIdx:idx,zScale,maxPoints:0,ignoreLabels:state.ignoreLabels});
    requestGaussianLoad();
  }, delay);
}

// ── Apply frame data ──────────────────────────────────────────────────────────
function applyFrameData(d) {
  vscodeLog('applyFrameData idx='+d.frameIdx+' threeReady='+state.threeReady+
    ' gt='+(d.gt?d.gt.count:'null')+' pred='+(d.pred?d.pred.count:'null')+
    ' lidar='+(d.lidar?d.lidar.count:'null')+
    ' traj='+(d.trajTransformer&&d.trajTransformer.hasTraj?'yes':'no')+
    ' mesh='+(d.meshGt&&d.meshGt.hasMesh?'yes':'no')+
    ' meshPred='+(d.meshPred&&d.meshPred.hasMesh?'yes':'no'));
  state.sensorCalib = d.sensorCalib || null;
  state.pathsInfo = d.paths || null;
  state.zScaleApplied = !!d.zScaleApplied;
  state.lastFrameData = d;
  if (state.frames[d.frameIdx]) {
    if (d.trajTransformer) state.frames[d.frameIdx].hasTraj = !!d.trajTransformer.hasTraj;
    if (d.meshGt) state.frames[d.frameIdx].hasMesh = !!d.meshGt.hasMesh;
    if (d.meshPred) state.frames[d.frameIdx].hasMeshPred = !!d.meshPred.hasMesh;
  }
  renderPathsPanel(state.pathsInfo);
  if (!state.sensorCalib) clearImageProjection();
  if (d.sceneName && state.frames[d.frameIdx]) {
    state.frames[d.frameIdx].sceneName = d.sceneName;
    refreshFrameListItem(d.frameIdx);
  }
  if(d.imageUris&&d.imageUris.length>0){
    setCameraImageSrc(d.imageUris[0]||'');
    const img2=document.getElementById('img2'),pane2=document.getElementById('imagePane2');
    if(img2&&pane2){if(d.imageUris[1]){img2.src=d.imageUris[1];pane2.style.display='';}else pane2.style.display='none';}
  }
  if(!state.threeReady){state.pendingFrameData=d;return;}
  renderLeftView(true);
  renderRightView(false);
  if(syncViews&&scenes[0]&&scenes[1]){
    copyCameraView(scenes[0], scenes[1]);
  }
  if(syncViews&&scenes[0]&&scenes[3]&&isGaussianOpen()){
    copyCameraView(scenes[0], scenes[3]);
  }
  if(d.lidar&&d.lidar.count>0)renderPointCloud(2,d.lidar.xyz_b64,d.lidar.lbl_b64,d.lidar.cloud_type||'intensity',true);else{clearPointsFromScene(scenes[2]);rawLbls[2]=null;}
  const frame=state.frames[d.frameIdx]||{};
  setInfo(composeInfoText(d), d.sceneName || frame.sceneName || frame.displayName || '');
  const ie=document.getElementById('infoText');if(ie)ie.title=d.frameInfo||'';
}

// ── Playback ──────────────────────────────────────────────────────────────────
function togglePlayback(){
  state.isPlaying=!state.isPlaying;
  const btn=document.getElementById('btnPlay');if(btn)btn.textContent=state.isPlaying?'⏸':'▶▶';
  if(state.isPlaying)state.playInterval=setInterval(()=>selectFrame((state.currentFrameIdx+1)%(state.frames.length||1)),500);
  else{clearInterval(state.playInterval);state.playInterval=null;}
}

// ── Info bar ──────────────────────────────────────────────────────────────────
function setInfo(info,sceneName){
  const ie=document.getElementById('infoText'),se=document.getElementById('sceneName');
  if(ie)ie.textContent=info||'';if(se&&sceneName)se.textContent=sceneName;
}

// ── Message handler ───────────────────────────────────────────────────────────
window.addEventListener('message',ev=>{
  const msg=ev.data;
  switch(msg.type){
    case 'initFrameList':{
      state.frames=msg.frames||[];state.dataDir=msg.dataDir||null;
      try { vscode.setState({ dataDir: state.dataDir }); } catch(_) {}
      cameraInitialized.fill(false);
      populateFrameList(state.frames);
      const ne=document.getElementById('folderName');
      if(ne&&state.dataDir){const p=state.dataDir.replace(/\\/g,'/').split('/');ne.textContent=p[p.length-1];ne.title=state.dataDir;}
      const dp=document.getElementById('currentDirPath');
      if(dp){dp.textContent=state.dataDir||'';dp.title=state.dataDir||'';dp.style.display=state.dataDir?'':'none';}
      if(state.frames.length>0)selectFrame(0);else setInfo('未找到数据文件','');
      break;
    }
    case 'frameData': applyFrameData(msg); break;
    case 'imageData': {
      setCameraImageSrc((msg.imageUris && msg.imageUris[0]) || '');
      const img2=document.getElementById('img2'),pane2=document.getElementById('imagePane2');
      if(img2&&pane2){if(msg.imageUris&&msg.imageUris[1]){img2.src=msg.imageUris[1];pane2.style.display='';}else pane2.style.display='none';}
      break;
    }
    case 'gaussianData':{
      // Ignore stale responses from previous frames during rapid navigation
      if (typeof msg.frameIdx === 'number' && msg.frameIdx !== state.currentFrameIdx) break;
      vscodeLog('gaussianData count='+msg.count+' colors sample='+msg.colors_b64.slice(0,20));
      state.gaussianZScaleFactor = msg.zScaleFactor || 1;
      const gPane=document.getElementById('gaussianPane');
      gPane.style.display='';
      setTimeout(()=>{
        const s=scenes[3];
        if(s){const {w,h}=getElSize(s.renderer.domElement.parentElement||s.renderer.domElement);
          if(w>1&&h>1){s.renderer.setSize(w,h,false);s.camera.aspect=w/h;s.camera.updateProjectionMatrix();}}
        renderGaussians(msg);
      },50);
      document.getElementById('btnCloseGaussian').style.display='';
      document.getElementById('btnGaussian').style.display='none';
      renderGaussianStats(msg);
      setInfo('高斯 '+msg.count+' 个 | '+msg.label_info,'');
      break;
    }
    case 'gaussianClear':{
      if (typeof msg.frameIdx === 'number' && msg.frameIdx !== state.currentFrameIdx) break;
      if (!isGaussianOpen()) break;
      clearPointsFromScene(scenes[3]); clearPins(3);
      gaussianCenters = null;
      lastGaussianGeom = null;
      clearGaussianStats();
      setInfo(msg.message || '当前帧没有高斯文件','');
      break;
    }
    case 'loading':{const el=document.getElementById('loadingIndicator');if(el)el.style.display=msg.isLoading?'':'none';break;}
    case 'error': vscodeLog(msg.message,'error');setInfo('❌ '+msg.message,'');break;
  }
});

// ── Controls ──────────────────────────────────────────────────────────────────
function setupControls(){
  document.getElementById('btnOpenFolder')?.addEventListener('click',()=>vscode.postMessage({cmd:'openFolder'}));
  document.getElementById('btnPrev')?.addEventListener('click',()=>selectFrame(Math.max(0,state.currentFrameIdx-1)));
  document.getElementById('btnNext')?.addEventListener('click',()=>selectFrame(Math.min(state.frames.length-1,state.currentFrameIdx+1)));
  document.getElementById('btnPlay')?.addEventListener('click',togglePlayback);
  const slider=document.getElementById('pointSizeSlider'),sv=document.getElementById('pointSizeVal');
  if(slider)slider.addEventListener('input',()=>{const v=parseFloat(slider.value);if(sv)sv.textContent=v;updateAllPointSizes(v);});
  document.getElementById('chkZScale')?.addEventListener('change',()=>{if(state.currentFrameIdx>=0)requestFrameLoad();});
  document.getElementById('leftViewModeSelect')?.addEventListener('change',(e)=>{
    state.leftViewMode = e.target.value || '真值';
    if (!state.lastFrameData) return;
    renderLeftView(false);
    if(syncViews&&scenes[0]&&scenes[1]) copyCameraView(scenes[0], scenes[1]);
    const d = state.lastFrameData;
    const frame = state.frames[d.frameIdx] || {};
    setInfo(composeInfoText(d), d.sceneName || frame.sceneName || frame.displayName || '');
  });
  document.getElementById('rightViewModeSelect')?.addEventListener('change',(e)=>{
    state.rightViewMode = e.target.value || '预测';
    if (!state.lastFrameData) return;
    renderRightView(false);
    if(syncViews&&scenes[0]&&scenes[1]) copyCameraView(scenes[0], scenes[1]);
    const d = state.lastFrameData;
    const frame = state.frames[d.frameIdx] || {};
    setInfo(composeInfoText(d), d.sceneName || frame.sceneName || frame.displayName || '');
  });
  document.getElementById('btnGaussian')?.addEventListener('click',()=>{
    if(state.currentFrameIdx<0 || !state.frames.length){
      setInfo('请先打开 vis 文件夹并等帧列表加载完成','');
      vscodeLog('查看高斯: no frame selected yet');
      return;
    }
    const f=state.frames[state.currentFrameIdx];
    if(!f||!f.hasGaussian){setInfo('当前帧没有高斯文件（需要 *_gaussian.pkl）','');return;}
    const z=document.getElementById('chkZScale')?.checked||false;
    vscodeLog('查看高斯: load frame='+state.currentFrameIdx+' pkl='+(f.gaussian||''));
    vscode.postMessage({cmd:'loadGaussian',frameIdx:state.currentFrameIdx,zScaleFactor:z?Z_SCALE_FACTOR:1});
  });
  document.getElementById('btnCloseGaussian')?.addEventListener('click',()=>{
    document.getElementById('gaussianPane').style.display='none';
    clearPointsFromScene(scenes[3]); clearPins(3);
    gaussianCenters = null;
    lastGaussianGeom = null;
    state.gaussianZScaleFactor = 1;
    clearGaussianStats();
    document.getElementById('btnCloseGaussian').style.display='none';
    document.getElementById('btnGaussian').style.display='';
  });
  document.getElementById('chkLowOpaBox')?.addEventListener('change',()=>updateLowOpacityBoxes());
  document.getElementById('lowOpaThrInput')?.addEventListener('change',()=>updateLowOpacityBoxes());
}
function setupKeyboardNav(){
  window.addEventListener('keydown',e=>{
    if(e.target.tagName==='INPUT')return;
    if(e.key==='ArrowLeft'||e.key==='b'||e.key==='B'){selectFrame(Math.max(0,state.currentFrameIdx-1));e.preventDefault();}
    else if(e.key==='ArrowRight'||e.key==='n'||e.key==='N'){selectFrame(Math.min(state.frames.length-1,state.currentFrameIdx+1));e.preventDefault();}
    else if(e.key===' '){togglePlayback();e.preventDefault();}
  });
}

// ── Init ──────────────────────────────────────────────────────────────────────
function waitForTHREE(cb,n){
  n=n||0;
  if(typeof THREE!=='undefined'){
    const OC=THREE.OrbitControls||window.OrbitControls;
    if(OC){if(!THREE.OrbitControls)THREE.OrbitControls=OC;vscodeLog('THREE r'+THREE.REVISION+' ready');cb();}
    else if(n<100)setTimeout(()=>waitForTHREE(cb,n+1),100);
    else vscodeLog('OrbitControls missing','error');
  } else if(n<100)setTimeout(()=>waitForTHREE(cb,n+1),100);
  else vscodeLog('THREE missing','error');
}
function initControls(){buildLabelFilter();setupControls();setupKeyboardNav();}
function initThree(){
  vscodeLog('initThree r'+THREE.REVISION);
  document.body.offsetHeight;
  for(let i=0;i<4;i++) scenes[i]=createScene(CANVAS_IDS[i]);
  setupViewSync();
  setupImagePane('imagePane1','imgTransformLayer');
  setupPointHover('gtCanvas',   0,'GT');
  setupPointHover('predCanvas', 1,'Prediction');
  setupPointHover('lidarCanvas',2,'Lidar');
  setupPointHover('gaussianCanvas',3,'Gaussian');
  if(typeof ResizeObserver!=='undefined'){
    const ro=new ResizeObserver(()=>{
      for(const s of scenes){if(!s||!s.renderer)continue;
        const {w,h}=getElSize(s.renderer.domElement.parentElement||s.renderer.domElement);
        if(w>1&&h>1){s.renderer.setSize(w,h,false);s.camera.aspect=w/h;s.camera.updateProjectionMatrix();}}
    });
    document.querySelectorAll('.pc-pane').forEach(el=>ro.observe(el));
  }
  animate();
  state.threeReady=true; vscodeLog('threeReady=true');
  if(state.pendingFrameData){const d=state.pendingFrameData;state.pendingFrameData=null;applyFrameData(d);}
  vscode.postMessage({cmd:'ready'});
}
if(document.readyState==='loading'){
  document.addEventListener('DOMContentLoaded',()=>{initControls();waitForTHREE(initThree);});
}else{initControls();waitForTHREE(initThree);}
