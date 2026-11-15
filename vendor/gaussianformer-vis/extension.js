// extension.js  –  GaussianFormer Visualizer VS Code Extension
'use strict';

const vscode = require('vscode');
const path   = require('path');
const cp     = require('child_process');

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function getNonce() {
  let text = '';
  const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}

// ── Output channel for debug logging ─────────────────────────────────────────
let _outputChannel = null;
function getOutput() {
  if (!_outputChannel) {
    _outputChannel = vscode.window.createOutputChannel('GaussianFormer Vis');
  }
  return _outputChannel;
}
function log(msg, show) {
  const ch = getOutput();
  ch.appendLine('[' + new Date().toLocaleTimeString() + '] ' + msg);
  if (show) ch.show(true);
}

/** Detect working python binary. Returns the first one that exists. */
function resolvePython(context) {
  const fs = require('fs');
  const configured = vscode.workspace.getConfiguration('gaussianVis').get('pythonPath');
  if (configured) return configured;
  for (const folder of vscode.workspace.workspaceFolders || []) {
    const candidate = path.join(folder.uri.fsPath, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
    if (fs.existsSync(candidate)) return candidate;
  }
  return process.platform === 'win32' ? 'python' : 'python3';
}

// ─────────────────────────────────────────────────────────────────────────────
// VisPanel  –  multi-instance WebView panels (side-by-side comparison)
// ─────────────────────────────────────────────────────────────────────────────

class VisPanel {
  /** @type {Set<VisPanel>} */
  static panels = new Set();
  static _nextId = 1;

  static _titleFor(dir) {
    if (!dir) return 'GaussianFormer Visualizer';
    const name = path.basename(dir);
    // Prefer parent/name when parent looks like a run folder (…/2-1-0/vis)
    const parent = path.basename(path.dirname(dir));
    if (parent && parent !== '.' && parent !== '/' && name === 'vis') {
      return 'Vis: ' + parent;
    }
    return 'Vis: ' + name;
  }

  static _normDir(dir) {
    if (!dir) return '';
    try { return path.resolve(dir); } catch (_) { return String(dir); }
  }

  static _findPanelForDir(initialDir) {
    const want = VisPanel._normDir(initialDir);
    if (!want) return undefined;
    for (const inst of VisPanel.panels) {
      if (VisPanel._normDir(inst._dataDir) === want) return inst;
    }
    return undefined;
  }

  static _pickExistingPanel() {
    let chosen;
    for (const inst of VisPanel.panels) chosen = inst;
    return chosen;
  }

  static _promptFolder(inst) {
    vscode.window.showOpenDialog({
      canSelectFolders: true,
      canSelectFiles: false,
      canSelectMany: false,
      openLabel: '打开可视化文件夹',
    }).then(uris => {
      if (uris && uris.length > 0) {
        inst.loadDirectory(uris[0].fsPath);
      }
    });
  }

  /**
   * Open or reveal a visualizer panel.
   * Same folder → reuse/reveal. Command palette with a panel already open → reveal it.
   * Right-click a different folder → new panel beside the existing one.
   * @param {vscode.ExtensionContext} context
   * @param {string | undefined} initialDir
   */
  static createOrShow(context, initialDir) {
    const existingSame = VisPanel._findPanelForDir(initialDir);
    if (existingSame) {
      log('Revealing existing visualizer for ' + initialDir);
      existingSame._panel.reveal(existingSame._panel.viewColumn || vscode.ViewColumn.One, false);
      return;
    }

    if (!initialDir && VisPanel.panels.size > 0) {
      const last = VisPanel._pickExistingPanel();
      log('Revealing last visualizer panel (no new folder given)');
      last._panel.reveal(last._panel.viewColumn || vscode.ViewColumn.One, false);
      return;
    }

    const column = vscode.window.activeTextEditor
      ? vscode.window.activeTextEditor.viewColumn
      : undefined;

    // Prefer Beside when another visualizer is already open (side-by-side compare)
    const viewColumn = VisPanel.panels.size > 0
      ? vscode.ViewColumn.Beside
      : (column || vscode.ViewColumn.One);

    log('Opening visualizer panel, dir=' + (initialDir || '(pick folder)'));
    const panel = vscode.window.createWebviewPanel(
      'gaussianVisPanel',
      VisPanel._titleFor(initialDir),
      { viewColumn, preserveFocus: false },
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.file(path.join(context.extensionPath, 'media')),
          vscode.Uri.file(context.extensionPath),
        ],
      }
    );

    const inst = new VisPanel(panel, context, initialDir);
    panel.reveal(viewColumn, false);
    if (!initialDir) {
      VisPanel._promptFolder(inst);
    }
  }

  /**
   * Revive a webview restored after Reload Window.
   * Without this, VS Code recreates an empty panel shell → blank UI.
   * @param {vscode.WebviewPanel} panel
   * @param {vscode.ExtensionContext} context
   * @param {{ dataDir?: string } | undefined} state
   */
  static revive(panel, context, state) {
    const initialDir = state && state.dataDir ? state.dataDir : undefined;
    log('Reviving webview panel, dataDir=' + (initialDir || '(none)'));
    panel.title = VisPanel._titleFor(initialDir);
    new VisPanel(panel, context, initialDir);
  }

  /**
   * @param {vscode.WebviewPanel} panel
   * @param {vscode.ExtensionContext} context
   * @param {string | undefined} initialDir
   */
  constructor(panel, context, initialDir) {
    this._panel    = panel;
    this._context  = context;
    this._dataDir  = initialDir || null;
    this._frames   = [];
    this._disposables = [];
    // Performance: cancel stale requests, prefetch, cache images
    this._loadSeq       = 0;          // incremented on each loadFrame; stale responses ignored
    this._gaussSeq      = 0;          // incremented on each loadGaussian; stale responses ignored
    this._imgCache      = new Map();  // path → base64 data URL (in-memory, up to 20 images)
    this._prefetchTimer = null;
    // Persistent Python daemon (avoids ~300ms startup cost per request)
    this._daemon        = null;
    this._daemonBuf     = '';
    this._daemonCbs     = new Map();
    this._daemonNextId  = 1;
    this._panelId       = VisPanel._nextId++;
    this._disposed      = false;

    VisPanel.panels.add(this);
    this._panel.title = VisPanel._titleFor(this._dataDir);

    this._panel.webview.html = this._getWebviewContent(this._panel.webview);

    this._panel.webview.onDidReceiveMessage(
      msg => this._handleMessage(msg),
      null,
      this._disposables
    );

    this._panel.onDidDispose(
      () => this.dispose(),
      null,
      this._disposables
    );
  }

  dispose() {
    if (this._disposed) return;
    this._disposed = true;
    VisPanel.panels.delete(this);
    if (this._daemon) { try { this._daemon.kill(); } catch(_) {} this._daemon = null; }
    if (this._prefetchTimer) clearTimeout(this._prefetchTimer);
    while (this._disposables.length) {
      this._disposables.pop().dispose();
    }
  }

  /** Close this panel (triggers onDidDispose → dispose). */
  close() {
    try { this._panel.dispose(); } catch (_) {}
  }

  // ── Python daemon bridge ──────────────────────────────────────────────────
  // Keeps one Python process alive for the session — eliminates ~300ms startup
  // cost per request.  Requests are newline-delimited JSON over stdin/stdout.

  _ensureDaemon() {
    if (this._daemon && !this._daemon.killed) return;
    const python  = resolvePython(this._context);
    const helper  = path.join(this._context.extensionPath, 'vis_helper.py');
    log('Starting Python daemon: ' + python + ' ' + helper);
    // -u = unbuffered stdin/stdout (critical on SSH/code-server pipes)
    // PYTHONUNBUFFERED=1 is a belt-and-suspenders backup for environments
    // where -u is ignored or a wrapper script is used.
    const env = Object.assign({}, process.env, { PYTHONUNBUFFERED: '1' });
    this._daemon = cp.spawn(python, ['-u', helper, '--mode', 'daemon'],
                            { stdio: ['pipe','pipe','pipe'], env });
    this._daemonBuf    = '';
    this._daemonCbs    = new Map();  // id → { resolve, reject, timer }
    this._daemonNextId = 1;

    this._daemon.stdout.on('data', chunk => {
      this._daemonBuf += chunk.toString();
      let nl;
      while ((nl = this._daemonBuf.indexOf('\n')) !== -1) {
        const line = this._daemonBuf.slice(0, nl).trim();
        this._daemonBuf = this._daemonBuf.slice(nl + 1);
        if (!line) continue;
        try {
          const msg = JSON.parse(line);
          const cb  = this._daemonCbs.get(msg.id);
          if (!cb) continue;
          clearTimeout(cb.timer);
          this._daemonCbs.delete(msg.id);
          if (msg.error) cb.reject(new Error(msg.error));
          else           cb.resolve(msg.result);
        } catch (e) {
          log('Daemon parse error: ' + e.message + '  line: ' + line.slice(0,200), true);
        }
      }
    });

    this._daemon.stderr.on('data', chunk => {
      const s = chunk.toString().trim();
      if (s) log('py-daemon: ' + s);
    });

    this._daemon.on('close', code => {
      log('Python daemon exited (code=' + code + ')', code !== 0);
      this._daemon = null;
      // Reject all pending
      for (const cb of this._daemonCbs.values()) {
        clearTimeout(cb.timer);
        cb.reject(new Error('Python daemon exited with code ' + code));
      }
      this._daemonCbs.clear();
    });

    this._daemon.on('error', err => {
      log('Daemon spawn error: ' + err.message, true);
      this._daemon = null;
    });

    // Send a ping immediately after start to verify stdin pipe works
    // This distinguishes "stdin buffering" from "operation hanging"
    setTimeout(() => {
      if (!this._daemon) return;
      this._daemonRequest({ mode: 'ping' }).then(r => {
        log('Daemon ping OK: Python ' + (r.python||'').slice(0,20) + ' on ' + (r.platform||'?'));
      }).catch(e => {
        log('Daemon ping FAILED: ' + e.message +
          '\n  → stdin pipe is blocked. Check: python -u vis_helper.py --mode daemon (then type {"id":1,"mode":"ping"} + Enter)', true);
      });
    }, 800);
  }

  _daemonRequest(reqObj) {
    return new Promise((resolve, reject) => {
      this._ensureDaemon();
      if (!this._daemon) { reject(new Error('Daemon not running')); return; }
      const id  = this._daemonNextId++;
      reqObj.id = id;
      const timer = setTimeout(() => {
        this._daemonCbs.delete(id);
        reject(new Error('Daemon request timed out (300s)'));
      }, 300000);
      this._daemonCbs.set(id, { resolve, reject, timer });
      try {
        this._daemon.stdin.write(JSON.stringify(reqObj) + '\n');
      } catch (e) {
        clearTimeout(timer);
        this._daemonCbs.delete(id);
        reject(new Error('Daemon stdin write failed: ' + e.message));
      }
    });
  }

  /**
   * Run vis_helper.py with the given CLI arguments.
   * Falls back to subprocess if daemon is unavailable.
   * @param {string[]} args
   * @returns {Promise<any>}
   */
  _runPython(args) {
    // Convert CLI args array → daemon request object
    const req = {};
    for (let i = 0; i < args.length; i++) {
      const a = args[i];
      if (a === '--mode')          { req.mode        = args[++i]; }
      else if (a === '--dir')      { req.dir         = args[++i]; }
      else if (a === '--idx')      { req.idx         = parseInt(args[++i]); }
      else if (a === '--z-scale')  { req.z_scale     = true; }
      else if (a === '--max-points'){ req.max_points = parseInt(args[++i]); }
      else if (a === '--ignore-labels'){ req.ignore_labels = args[++i]; }
      else if (a === '--base-key') { req.base_key    = args[++i]; }
      else if (a === '--pkl')      { req.pkl         = args[++i]; }
      else if (a === '--z-scale-factor'){ req.z_scale_factor = parseFloat(args[++i]); }
    }
    log('Daemon req: mode=' + req.mode + (req.base_key ? ' key='+req.base_key : ' idx='+req.idx));
    return this._daemonRequest(req);
  }

  // ── Directory / frame loading ─────────────────────────────────────────────

  async loadDirectory(dir) {
    this._dataDir = dir;
    this._panel.title = VisPanel._titleFor(dir);
    this._post({ type: 'loading', isLoading: true });
    try {
      const result = await this._runPython(['--mode', 'scan', '--dir', dir]);
      this._frames = result.frames || [];
      this._post({ type: 'initFrameList', frames: this._frames, dataDir: dir });
    } catch (e) {
      log('Scan ERROR: ' + e.message, true);
      this._post({ type: 'error', message: `Scan failed: ${e.message}` });
    } finally {
      this._post({ type: 'loading', isLoading: false });
    }
  }

  /**
   * @param {number} frameIdx
   * @param {boolean} zScale
   * @param {number} maxPoints
   * @param {number[]} ignoreLabels
   */
  async loadFrame(frameIdx, zScale, maxPoints, ignoreLabels) {
    if (!this._dataDir) { return; }

    // Cancel-stale: each request gets a sequence number; drop results if newer request started
    const seq = ++this._loadSeq;
    this._post({ type: 'loading', isLoading: true });

    const args = [
      '--mode', 'frame',
      '--dir', this._dataDir,
      '--idx', String(frameIdx),
    ];
    // Pass base-key to skip rescan (saves 400ms per frame)
    const frame = this._frames[frameIdx];
    if (frame && frame.base) {
      args.push('--base-key', frame.base);
    }
    if (zScale)    { args.push('--z-scale'); }
    if (maxPoints) { args.push('--max-points', String(maxPoints)); }
    if (ignoreLabels && ignoreLabels.length) {
      args.push('--ignore-labels', ignoreLabels.join(','));
    }

    try {
      const data = await this._runPython(args);

      // Drop stale response (user navigated away)
      if (seq !== this._loadSeq) {
        log('Dropped stale frame response seq=' + seq + ' (current=' + this._loadSeq + ')');
        return;
      }

      // Send PC data FIRST so point clouds render immediately (no waiting for image)
      this._post({
        type: 'frameData', frameIdx,
        imageUris: [],   // image arrives separately below
        gt:    data.gt    || null,
        pred:  data.pred  || null,
        lidar: data.lidar || null,
        trajTransformer: data.trajTransformer || null,
        meshGt: data.meshGt || null,
        meshPred: data.meshPred || null,
        info:      data.info      || '',
        frameInfo: data.frameInfo || '',
        paths:       data.paths       || null,
        sensorCalib: data.sensorCalib || null,
        zScaleApplied: !!data.zScaleApplied,
        sceneName:   data.sceneName   || '',
      });

      // Send image asynchronously — does not block point cloud rendering
      const currentSeq = seq;
      setImmediate(() => {
        if (currentSeq !== this._loadSeq) return;  // user moved to next frame
        const fs = require('fs'), pathMod = require('path');
        const imageUris = (data.images || []).map(p => {
          if (!p) return null;
          if (this._imgCache.has(p)) {
            log('Image cache hit: ' + pathMod.basename(p));
            return this._imgCache.get(p);
          }
          try {
            if (!fs.existsSync(p)) { log('Image not found: ' + p); return null; }
            const buf  = fs.readFileSync(p);
            const ext  = pathMod.extname(p).slice(1).toLowerCase();
            const mime = ext === 'png' ? 'image/png' : 'image/jpeg';
            const uri  = 'data:' + mime + ';base64,' + buf.toString('base64');
            log('Image loaded: ' + pathMod.basename(p) + ' (' + buf.length + ' bytes)');
            if (this._imgCache.size >= 20) this._imgCache.delete(this._imgCache.keys().next().value);
            this._imgCache.set(p, uri);
            return uri;
          } catch (e) { log('Image read error: ' + e.message, true); return null; }
        }).filter(Boolean);
        if (currentSeq === this._loadSeq && imageUris.length > 0) {
          this._post({ type: 'imageData', frameIdx, imageUris });
        }
      });

      // Prefetch adjacent frames in background (fire and forget)
      this._schedulePrefetch(frameIdx, zScale, maxPoints, ignoreLabels);

    } catch (e) {
      if (seq === this._loadSeq) {
        this._post({ type: 'error', message: `Frame load failed: ${e.message}` });
      }
    } finally {
      if (seq === this._loadSeq) {
        this._post({ type: 'loading', isLoading: false });
      }
    }
  }

  /** Prefetch next+prev frame images in background to warm cache. */
  _schedulePrefetch(frameIdx, zScale, maxPoints, ignoreLabels) {
    if (this._prefetchTimer) clearTimeout(this._prefetchTimer);
    this._prefetchTimer = setTimeout(() => {
      const fs = require('fs'), pathMod = require('path');
      for (const delta of [1, -1]) {
        const nextIdx = frameIdx + delta;
        if (nextIdx < 0 || nextIdx >= this._frames.length) continue;
        const nextFrame = this._frames[nextIdx];
        if (!nextFrame) continue;
        // Only prefetch images (cheap, ~10ms) — skip point cloud prefetch to avoid overloading
        const base  = nextFrame.base || '';
        const slash = base.lastIndexOf('/');
        const baseDir  = slash >= 0 ? require('path').join(this._dataDir, base.slice(0, slash)) : this._dataDir;
        const baseName = slash >= 0 ? base.slice(slash + 1) : base;
        for (const suffix of ['_image.jpg','_image_cam0.jpg','_image.png']) {
          const p = require('path').join(baseDir, baseName + suffix);
          if (!this._imgCache.has(p) && fs.existsSync(p)) {
            try {
              const buf  = fs.readFileSync(p);
              const ext  = pathMod.extname(p).slice(1).toLowerCase();
              const mime = ext === 'png' ? 'image/png' : 'image/jpeg';
              const uri  = 'data:' + mime + ';base64,' + buf.toString('base64');
              if (this._imgCache.size >= 20) this._imgCache.delete(this._imgCache.keys().next().value);
              this._imgCache.set(p, uri);
              log('Prefetched image: ' + pathMod.basename(p));
            } catch(_) {}
          }
        }
      }
    }, 300);  // 300ms delay so we don't prefetch during rapid navigation
  }

  /**
   * @param {number} frameIdx
   * @param {number} zScaleFactor
   */
  async loadGaussian(frameIdx, zScaleFactor) {
    const frame = this._frames[frameIdx];
    if (!frame) { return; }

    const seq = ++this._gaussSeq;
    const pklPath = frame.gaussian;
    if (!pklPath) {
      this._post({ type: 'gaussianClear', frameIdx, message: '当前帧没有高斯文件' });
      return;
    }

    this._post({ type: 'loading', isLoading: true });
    try {
      const data = await this._runPython([
        '--mode', 'gaussian',
        '--pkl', pklPath,
        '--z-scale-factor', String(zScaleFactor),
      ]);
      if (seq !== this._gaussSeq) {
        log('Dropped stale gaussian response seq=' + seq + ' (current=' + this._gaussSeq + ')');
        return;
      }
      this._post({ type: 'gaussianData', frameIdx, zScaleFactor: zScaleFactor, ...data });
    } catch (e) {
      if (seq === this._gaussSeq) {
        this._post({ type: 'error', message: `Gaussian load failed: ${e.message}` });
      }
    } finally {
      if (seq === this._gaussSeq) {
        this._post({ type: 'loading', isLoading: false });
      }
    }
  }

  // ── Message handler ───────────────────────────────────────────────────────

  _handleMessage(msg) {
    switch (msg.cmd) {
      case 'ready':
        if (this._dataDir) { this.loadDirectory(this._dataDir); }
        break;

      case 'openFolder': {
        vscode.window.showOpenDialog({
          canSelectFolders: true,
          canSelectFiles: false,
          canSelectMany: false,
          openLabel: '打开可视化文件夹',
        }).then(uris => {
          if (uris && uris.length > 0) {
            this.loadDirectory(uris[0].fsPath);
          }
        });
        break;
      }

      case 'loadFrame':
        this.loadFrame(msg.frameIdx, msg.zScale, msg.maxPoints, msg.ignoreLabels);
        break;

      case 'loadGaussian':
        this.loadGaussian(msg.frameIdx, msg.zScaleFactor || 1.0);
        break;

      case 'log':
        log('[WebView] ' + msg.message, msg.level === 'error');
        break;

      case 'openPath': {
        const fs = require('fs');
        const p = msg.path;
        if (!p || !fs.existsSync(p)) {
          vscode.window.showWarningMessage('文件不存在: ' + p);
          break;
        }
        const uri = vscode.Uri.file(p);
        if (msg.action === 'reveal') {
          vscode.commands.executeCommand('revealInExplorer', uri);
        } else if (/\.(jpg|jpeg|png|gif|webp|bmp)$/i.test(p)) {
          vscode.commands.executeCommand('vscode.open', uri);
        } else {
          vscode.env.openExternal(uri);
        }
        break;
      }

      default:
        console.warn('[GaussianVis] Unknown message cmd:', msg.cmd);
    }
  }

  // ── Internal helpers ──────────────────────────────────────────────────────

  _post(message) {
    try { this._panel.webview.postMessage(message); } catch (_) {}
  }

  // ── HTML generation ───────────────────────────────────────────────────────

  _getWebviewContent(webview) {
    const nonce = getNonce();

    // Local panel.js
    const panelJsUri = webview.asWebviewUri(
      vscode.Uri.file(path.join(this._context.extensionPath, 'media', 'panel.js'))
    );

    const csp = [
      `default-src 'none'`,
      `img-src ${webview.cspSource} blob: data: https: vscode-resource: vscode-file:`,
      `script-src 'nonce-${nonce}' ${webview.cspSource}`,
      `style-src 'unsafe-inline' ${webview.cspSource}`,
      `connect-src ${webview.cspSource}`,
    ].join('; ');

    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<title>GaussianFormer Visualizer</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0;}
  body{
    background:var(--vscode-editor-background,#1e1e1e);
    color:var(--vscode-editor-foreground,#d4d4d4);
    font-family:var(--vscode-font-family,'Segoe UI',sans-serif);
    font-size:13px;
    overflow:hidden;
    height:100vh;
    width:100vw;
  }
  #app{display:flex;height:100vh;width:100vw;overflow:hidden;}

  /* ── Sidebar ── */
  #sidebar{
    width:220px;min-width:160px;
    display:flex;flex-direction:column;
    background:var(--vscode-sideBar-background,#252526);
    border-right:1px solid var(--vscode-panel-border,#3a3a3a);
    overflow:hidden;
  }
  #sidebarHeader{padding:8px 6px 4px;display:flex;flex-direction:column;gap:4px;}
  #btnOpenFolder{
    width:100%;padding:5px 8px;cursor:pointer;
    background:var(--vscode-button-background,#0e639c);
    color:var(--vscode-button-foreground,#fff);
    border:none;border-radius:3px;font-size:12px;
  }
  #btnOpenFolder:hover{background:var(--vscode-button-hoverBackground,#1177bb);}
  #folderName{
    font-size:10px;color:var(--vscode-descriptionForeground,#888);
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:0 2px;
  }
  #frameList{flex:1;overflow-y:auto;padding:2px;}
  #pathsPanel{
    max-height:140px;overflow-y:auto;padding:4px 6px;
    border-top:1px solid var(--vscode-panel-border,#3a3a3a);
    font-size:10px;display:none;
  }
  #pathsPanel.visible{display:block;}
  #pathsPanel summary{cursor:pointer;padding:2px 0;color:var(--vscode-descriptionForeground,#aaa);}
  .path-entry{
    display:block;padding:2px 0 2px 8px;color:var(--vscode-textLink-foreground,#3794ff);
    cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  }
  .path-entry:hover{text-decoration:underline;}
  .path-entry .path-key{opacity:0.75;margin-right:4px;}
  .frame-item{
    padding:5px 8px;cursor:pointer;border-radius:3px;
    font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
    line-height:1.4;
  }
  .frame-item:hover{background:var(--vscode-list-hoverBackground,#2a2d2e);}
  .frame-item.active{
    background:var(--vscode-list-activeSelectionBackground,#094771);
    color:var(--vscode-list-activeSelectionForeground,#fff);
  }
  .frame-badges{font-size:9px;opacity:0.7;margin-left:4px;}
  #navBar{
    display:flex;align-items:center;gap:4px;padding:6px;
    border-top:1px solid var(--vscode-panel-border,#3a3a3a);
  }
  #navBar button{
    background:var(--vscode-button-secondaryBackground,#3a3a3a);
    color:var(--vscode-button-secondaryForeground,#ccc);
    border:none;border-radius:3px;padding:3px 7px;cursor:pointer;font-size:12px;
  }
  #navBar button:hover{background:var(--vscode-button-secondaryHoverBackground,#444);}
  #frameIndexLabel{font-size:11px;white-space:nowrap;flex:1;text-align:center;}

  /* ── Main Content ── */
  #mainContent{flex:1;display:flex;flex-direction:column;overflow:hidden;gap:0;min-width:0;}

  /* ── Controls row ── */
  #controlsRow{
    display:flex;flex-wrap:wrap;align-items:center;gap:6px;
    padding:5px 8px;
    background:var(--vscode-editorGroupHeader-tabsBackground,#1e1e1e);
    border-bottom:1px solid var(--vscode-panel-border,#3a3a3a);
    flex-shrink:0;
  }
  #controlsRow label{display:flex;align-items:center;gap:3px;font-size:12px;cursor:pointer;}
  #controlsRow input[type=range]{width:70px;cursor:pointer;}
  #controlsRow input[type=number]{
    width:88px;padding:2px 4px;
    background:var(--vscode-input-background,#3c3c3c);
    color:var(--vscode-input-foreground,#ccc);
    border:1px solid var(--vscode-input-border,#555);
    border-radius:3px;font-size:12px;
  }
  #controlsRow select{
    padding:2px 6px;
    background:var(--vscode-dropdown-background,#3c3c3c);
    color:var(--vscode-dropdown-foreground,#ccc);
    border:1px solid var(--vscode-dropdown-border,#555);
    border-radius:3px;font-size:12px;cursor:pointer;
  }
  #leftViewModeWrap{margin-left:auto;display:flex;align-items:center;gap:6px;}
  #rightViewModeWrap{display:flex;align-items:center;gap:6px;}
  #trajLegend, #predLegend{
    position:absolute;top:30px;left:8px;z-index:20;
    font-size:11px;line-height:1.5;padding:4px 8px;border-radius:4px;
    background:rgba(0,0,0,0.65);color:#eee;display:none;pointer-events:none;
  }
  .ctrl-btn{
    background:var(--vscode-button-secondaryBackground,#3a3a3a);
    color:var(--vscode-button-secondaryForeground,#ccc);
    border:none;border-radius:3px;padding:3px 8px;cursor:pointer;font-size:12px;
  }
  .ctrl-btn:hover{background:var(--vscode-button-secondaryHoverBackground,#4a4a4a);}
  .ctrl-btn.primary{
    background:var(--vscode-button-background,#0e639c);
    color:var(--vscode-button-foreground,#fff);
  }
  .ctrl-btn.primary:hover{background:var(--vscode-button-hoverBackground,#1177bb);}
  #loadingIndicator{font-size:12px;color:var(--vscode-charts-yellow,#e2b72f);}

  /* ── Label filter ── */
  #labelFilterDetails{
    padding:0 8px;
    border-bottom:1px solid var(--vscode-panel-border,#3a3a3a);
    flex-shrink:0;font-size:11px;
  }
  #labelFilterDetails summary{cursor:pointer;padding:3px 0;}
  #labelFilterGrid{display:flex;flex-wrap:wrap;gap:3px;padding:4px 0 6px;max-height:90px;overflow-y:auto;}
  .lbl-cb{display:flex;align-items:center;gap:2px;font-size:10px;cursor:pointer;padding:1px 3px;border-radius:2px;background:var(--vscode-badge-background,#3a3a3a);}
  .lbl-dot{width:8px;height:8px;border-radius:50%;display:inline-block;flex-shrink:0;}

  /* ── Views Area ── */
  /* Layout: GT | Pred | [Camera/Lidar column]  (3 equal columns) */
  #viewsArea{flex:1;display:flex;flex-direction:row;gap:4px;padding:4px;overflow:hidden;min-height:0;}
  #rightColumn{flex:1;display:flex;flex-direction:column;gap:4px;overflow:hidden;min-height:0;}
  .img-pane{
    flex:1;background:#111;min-height:0;
    border:1px solid var(--vscode-panel-border,#3a3a3a);border-radius:4px;
    position:relative;overflow:hidden;cursor:grab;
  }
  .img-pane.grabbing{cursor:grabbing;}
  .img-pane img{
    position:absolute;top:0;left:0;width:100%;height:100%;
    object-fit:contain;user-select:none;pointer-events:none;
  }
  .img-transform-layer{
    position:absolute;top:0;left:0;width:100%;height:100%;
    transform-origin:center center;
  }
  .img-marker{
    position:absolute;pointer-events:none;display:none;z-index:60;
    width:0;height:0;transform:translate(-50%,-50%);
  }
  .img-marker::before,.img-marker::after{
    content:'';position:absolute;background:rgba(255,0,0,0.65);border-radius:0.5px;
  }
  .img-marker::before{width:12px;height:1px;left:-6px;top:-0.5px;}
  .img-marker::after{width:1px;height:12px;left:-0.5px;top:-6px;}
  .img-coord-tag{
    position:absolute;pointer-events:none;display:none;z-index:61;
    background:rgba(0,0,0,0.78);color:#ffe078;font-size:10px;font-family:monospace;
    padding:2px 6px;border-radius:3px;white-space:nowrap;
  }
  .pc-pane{
    flex:1;position:relative;
    background:#080808;
    border:1px solid var(--vscode-panel-border,#3a3a3a);border-radius:4px;
    overflow:hidden;
  }
  .pc-pane canvas{width:100%!important;height:100%!important;display:block;}
  .view-label{
    position:absolute;top:6px;left:8px;
    font-size:12px;font-weight:600;pointer-events:none;
    padding:2px 8px;border-radius:4px;background:rgba(0,0,0,0.6);
  }
  .gt-label{color:#65ff65;}
  .pred-label{color:#ff5c5c;}
  .lidar-label{color:#ff5cff;}
  .gauss-label{color:#5caaff;}
  #gaussOverlayPanel{
    position:absolute;top:28px;left:8px;right:8px;z-index:45;
    display:flex;flex-direction:column;gap:6px;
    pointer-events:none;max-height:calc(100% - 40px);
  }
  #gaussControls{
    pointer-events:auto;align-self:flex-start;
    display:flex;align-items:center;gap:6px;flex-wrap:wrap;
    background:rgba(0,0,0,0.72);border:1px solid rgba(92,170,255,0.35);
    border-radius:4px;padding:4px 8px;
    font-size:11px;color:#dcefff;
  }
  #gaussControls label{display:flex;align-items:center;gap:4px;cursor:pointer;user-select:none;}
  #gaussControls input[type=number]{
    width:52px;background:rgba(255,255,255,0.08);color:#eee;
    border:1px solid rgba(255,255,255,0.2);border-radius:3px;padding:1px 4px;
  }
  #gaussStats{
    pointer-events:auto;align-self:flex-start;
    background:rgba(0,0,0,0.72);border:1px solid rgba(92,170,255,0.35);
    border-radius:4px;padding:6px 8px;
    font-size:11px;color:#e8e8e8;line-height:1.45;
    max-width:min(280px,90%);max-height:55%;overflow-y:auto;
    font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  }
  #gaussStats .gs-title{font-weight:700;color:#5caaff;margin-bottom:4px;}
  #gaussStats .gs-row{display:flex;align-items:center;gap:6px;white-space:nowrap;}
  #gaussStats .gs-dot{width:8px;height:8px;border-radius:2px;flex-shrink:0;}
  #gaussStats .gs-name{flex:1;overflow:hidden;text-overflow:ellipsis;}
  #gaussStats .gs-cnt{color:#ffe078;font-weight:600;}
  #gaussStats .gs-empty{color:#888;}

  /* ── Info Bar ── */
  #infoBar{
    padding:4px 10px;
    background:var(--vscode-statusBar-background,#007acc);
    color:var(--vscode-statusBar-foreground,#fff);
    border-top:1px solid var(--vscode-panel-border,#3a3a3a);
    flex-shrink:0;font-size:11px;
    display:flex;gap:12px;align-items:center;min-height:24px;
  }
  #sceneName{font-weight:600;white-space:nowrap;}
  #infoText{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}

  /* hover tooltip */
  #hoverTooltip{
    position:fixed;pointer-events:none;display:none;
    background:rgba(0,0,0,0.85);color:#eee;
    padding:3px 8px;border-radius:4px;font-size:11px;z-index:9999;
    white-space:pre;
  }
</style>
</head>
<body>
<div id="app">
  <!-- Sidebar -->
  <div id="sidebar">
    <div id="sidebarHeader">
      <button id="btnOpenFolder">📁 打开文件夹</button>
      <div id="folderName" title=""></div>
    </div>
    <div id="frameList"></div>
    <details id="pathsPanel">
      <summary>文件路径</summary>
      <div id="pathsList"></div>
    </details>
    <div id="navBar">
      <button id="btnPrev">◀</button>
      <span id="frameIndexLabel">-/-</span>
      <button id="btnNext">▶</button>
      <button id="btnPlay" title="Play/Stop (Space)">▶▶</button>
    </div>
  </div>

  <!-- Main -->
  <div id="mainContent">
    <div id="controlsRow">
      <label title="Z轴坐标放大10倍，便于观察路面细节">
        <input type="checkbox" id="chkZScale"> Z轴×5
      </label>
      <label title="Lidar点云按强度着色(灰度)">
        <input type="checkbox" id="chkLidarIntensity"> 雷达强度
      </label>
      <label title="点云大小">
        点大小: <input type="range" id="pointSizeSlider" min="1" max="10" value="2">
        <span id="pointSizeVal">2</span>px
      </label>
      <button id="btnGaussian" class="ctrl-btn primary" title="加载并显示高斯椭球 (3D instanced mesh)">🔵 查看高斯</button>
      <button id="btnCloseGaussian" class="ctrl-btn" style="display:none">✕ 关闭高斯</button>
      <span id="loadingIndicator" style="display:none">⏳ 加载中...</span>
      <label id="leftViewModeWrap" title="切换左侧窗口：OCC真值 / 轨迹transformer / mesh路面真值">
        左侧视图:
        <select id="leftViewModeSelect">
          <option value="真值" selected>真值</option>
          <option value="轨迹transformer">轨迹transformer</option>
          <option value="mesh真值">mesh真值</option>
        </select>
      </label>
      <label id="rightViewModeWrap" title="切换右侧窗口：OCC预测 / mesh路面预测">
        右侧视图:
        <select id="rightViewModeSelect">
          <option value="预测" selected>预测</option>
          <option value="mesh预测">mesh预测</option>
        </select>
      </label>
    </div>
    <div id="currentDirPath" title="" style="
      padding:2px 8px;flex-shrink:0;
      font-size:11px;color:var(--vscode-descriptionForeground,#888);
      background:var(--vscode-editorGroupHeader-tabsBackground,#1e1e1e);
      border-bottom:1px solid var(--vscode-panel-border,#3a3a3a);
      white-space:nowrap;overflow-x:auto;word-break:break-all;
      display:none;
    ">
    </div>

    <details id="labelFilterDetails">
      <summary>忽略标签 (点击展开/折叠)</summary>
      <div id="labelFilterGrid"></div>
    </details>

    <div id="viewsArea">
      <div class="pc-pane" id="gtPane">
        <canvas id="gtCanvas"></canvas>
        <span class="view-label gt-label" id="gtViewLabel">GT</span>
        <div id="trajLegend"></div>
      </div>
      <div class="pc-pane" id="predPane">
        <canvas id="predCanvas"></canvas>
        <span class="view-label pred-label" id="predViewLabel">Prediction</span>
        <div id="predLegend"></div>
      </div>
      <div id="rightColumn">
        <div class="img-pane" id="imagePane1">
          <div class="img-transform-layer" id="imgTransformLayer">
            <img id="img1" alt="">
          </div>
          <div class="img-marker" id="imgMarker"></div>
          <div class="img-coord-tag" id="imgCoordTag"></div>
          <span class="view-label" style="color:#ccc">Camera</span>
        </div>
        <div class="pc-pane" id="lidarPane"><canvas id="lidarCanvas"></canvas><span class="view-label lidar-label">Lidar</span></div>
      </div>
      <div class="pc-pane" id="gaussianPane" style="display:none">
        <canvas id="gaussianCanvas"></canvas>
        <span class="view-label gauss-label">Gaussian</span>
        <div id="gaussOverlayPanel">
          <div id="gaussControls" title="用红色长方体包络框标出 opacity 低于阈值的高斯">
            <label>
              <input type="checkbox" id="chkLowOpaBox"> 低opacity框
            </label>
            <label>
              阈值
              <input type="number" id="lowOpaThrInput" value="0.05" min="0" max="1" step="0.01">
            </label>
          </div>
          <div id="gaussStats"><div class="gs-empty">加载后显示类别统计</div></div>
        </div>
      </div>
    </div>

    <div id="infoBar">
      <div id="sceneName">—</div>
      <div id="infoText">请打开文件夹加载数据</div>
    </div>
  </div>
</div>
<div id="hoverTooltip"></div>

<!-- THREE.js + OrbitControls bundled via esbuild into a single IIFE (no UMD/CJS detection) -->
<script nonce="${nonce}" src="${webview.asWebviewUri(vscode.Uri.file(path.join(this._context.extensionPath, "media", "three-bundle.js")))}"></script>
<!-- Panel logic -->
<script nonce="${nonce}" src="${panelJsUri}"></script>
</body>
</html>`;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Extension lifecycle
// ─────────────────────────────────────────────────────────────────────────────

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
  context.subscriptions.push(getOutput());
  log('GaussianFormer Visualizer activated, python=' + resolvePython(context));
  context.subscriptions.push(
    vscode.commands.registerCommand('gaussianVis.openVisualizer', (uri) => {
      // If invoked from explorer context menu, uri is the folder URI
      let initialDir = undefined;
      try {
        if (uri && uri.fsPath) {
          const st = require('fs').statSync(uri.fsPath);
          if (st.isDirectory()) initialDir = uri.fsPath;
        }
      } catch (e) {
        log('openVisualizer uri resolve failed: ' + e.message);
      }
      log('Command gaussianVis.openVisualizer dir=' + (initialDir || '(none)'));
      VisPanel.createOrShow(context, initialDir);
    })
  );

  // Reload Window restores open webviews; must re-bind HTML/scripts or panel stays blank.
  context.subscriptions.push(
    vscode.window.registerWebviewPanelSerializer('gaussianVisPanel', {
      async deserializeWebviewPanel(panel, state) {
        VisPanel.revive(panel, context, state || {});
      }
    })
  );
}

function deactivate() {
  for (const panel of Array.from(VisPanel.panels)) {
    try { panel.close(); } catch (_) {}
  }
}

const originalActivate = activate;
activate = function(context) {
  originalActivate(context);
  context.subscriptions.push(vscode.commands.registerCommand('meshProject.renderFixedTen', async () => {
    const source = await vscode.window.showOpenDialog({canSelectFolders:true,canSelectFiles:false,canSelectMany:false,openLabel:'选择已完成评价的 vis 目录'});
    if (!source || !source.length) return;
    const identity = await vscode.window.showOpenDialog({canSelectFolders:false,canSelectFiles:true,canSelectMany:false,filters:{JSON:['json']},openLabel:'选择本轮 identity.json'});
    if (!identity || !identity.length) return;
    const target = await vscode.window.showOpenDialog({canSelectFolders:true,canSelectFiles:false,canSelectMany:false,openLabel:'选择输出父目录（将在下面新建本轮目录）'});
    if (!target || !target.length) return;
    const out = path.join(target[0].fsPath, 'mesh-review-' + Date.now());
    const runtime = path.join(context.extensionPath, 'runtime', 'mesh_visualize.py');
    const child = cp.spawn(resolvePython(context), [runtime,'--vis',source[0].fsPath,'--identity',identity[0].fsPath,'--out',out], {shell:false,windowsHide:true});
    child.stdout.on('data', chunk => log(chunk.toString(),true));
    child.stderr.on('data', chunk => log(chunk.toString(),true));
    child.on('error', error => vscode.window.showErrorMessage('Mesh评价启动失败：'+error.message));
    child.on('close', code => {
      if (code === 0) vscode.env.openExternal(vscode.Uri.file(path.join(out,'index.html')));
      else vscode.window.showErrorMessage('Mesh评价未完成，退出码 '+code+'。请查看 GaussianFormer Vis 输出。');
    });
  }));
};

module.exports = { activate, deactivate };
