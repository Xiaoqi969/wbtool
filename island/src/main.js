'use strict';
// ============================================================================
// main.js — Electron 主进程（小米超级岛同款形变引擎）
// ----------------------------------------------------------------------------
// 与 WBtool 原版（时间分段曲线）的核心区别：
//   · 真·弹簧物理：宽度 / 高度 / 内容进度 m 是三根独立弹簧，
//     每帧半隐式欧拉积分，不按总时长插值。
//   · 速度连续：动画中途反向打断时，当前位置与速度原样续接、只换目标 ——
//     这正是小米超级岛 / iOS 灵动岛「怎么打断都不闪跳」的物理本质。
//   · 三段式时序由弹簧参数天然涌现，不再手写分段曲线：
//     展开时宽度弹簧更硬（先横向铺开）、高度弹簧更软（随后向下落下）；
//     收起时反过来（先收高、再收宽）。
//
// 沿用 WBtool v1.3.0 的全部铁律：
//   1) 只有两个合法终态尺寸：390×52 / 620×H，绝不反推当前窗口尺寸当目标。
//   2) 屏幕中心只测一次；每帧 X = 固定中心 - 当前宽/2（绝对值），不累积漂移。
//   3) 一次 setBounds 原子设定位置与尺寸；显式关闭系统窗口阴影。
//   4) 窗口几何由主进程「单一时钟」驱动，每帧把 {m,w,h,r} 推给渲染层；
//      渲染层用同一帧数据画圆角与内容淡入淡出 —— 窗口与内容永不撕裂。
//   5) 形变期间不推扫描数据，避免 DOM 重排让文字抽搐；结束后补发。
//   6) IPC 契约与 preload API 和 WBtool 完全同名 —— 渲染层可直接互换。
//
// 【v1.4.0 测试版】遮挡问题方案：可拖拽
//   放弃「鼠标穿透」（胶囊物理上压在标签栏上，穿透与可点击互斥，无解），
//   改为整颗胶囊可自由拖拽：想点标签页时直接把它拖开，位置写入 prefs 跨启动记忆。
//   渲染层用「按下-移动阈值」区分拖拽与点击：位移 <4px 视为点击（展开/收起），
//   否则视为拖拽并逐帧把窗口移到位。
// ============================================================================
const { app, BrowserWindow, Tray, Menu, ipcMain, screen, nativeImage } = require('electron');
const path = require('path');
const fs = require('fs');
const { Scanner } = require('./scanner');

const PROJECTS = process.env.WORKBUDDY_PROJECTS_DIR || undefined;
const SCAN_MS = 10000;

const PILL_W = 390;
const PILL_H = 52;
const EXPAND_W = 620;
const MAX_H = 900;
const TOP_Y = 10;
const FRAME_MS = 16;          // ~60fps

// ---------- 弹簧参数（每根弹簧 = 刚度 k + 阻尼比 zeta） ----------
// k 越大弹簧越硬（越快到位）；zeta<1 有轻微过冲（小米超级岛的弹性感），
// zeta=1 临界阻尼（无过冲，收起用，干脆利落）。
// 数值手感的量纲：k≈110~260 对应 0.4~0.8s 的到位时间，与布局变化 300-500ms 区间吻合。
const SPRING = {
  expand: {
    w:  { k: 190, z: 0.76 },   // 宽度：偏软 + 明显弹性 → 先横向铺开并轻微回弹
    h:  { k: 110, z: 0.94 },   // 高度：更软更稳 → 随后向下落下，几乎不弹
    m:  { k: 300, z: 0.72 },   // 内容进度：带一点过冲 → 明细浮现时轻微「放大回坐」
  },
  collapse: {
    h:  { k: 240, z: 1.00 },   // 先收高：硬、临界阻尼、不拖泥带水
    w:  { k: 150, z: 0.92 },   // 再收宽：稍软，留一丝回弹
    m:  { k: 340, z: 0.90 },   // 内容快速退场
  },
};

// ---------- 临时诊断日志（ISLAND_DEBUG=1 时写入 island-debug.log）----------
const ISLAND_DEBUG = !!process.env.ISLAND_DEBUG;
const DEBUG_LOG = path.join(__dirname, '..', 'island-debug.log');
function dlog(...a) {
  if (!ISLAND_DEBUG) return;
  try {
    fs.appendFileSync(DEBUG_LOG, new Date().toISOString().slice(11, 23) + ' ' + a.join(' ') + '\n');
  } catch (_) {}
}

let win = null;
let tray = null;
let scanner = new Scanner(PROJECTS);
const singleInstance = app.requestSingleInstanceLock();
if (!singleInstance) app.quit();

// ---------- 置顶偏好 + 位置记忆（userData 下的小 JSON，跨启动记忆）----------
let pinned = true;
let prefsPath = '';
let savedPos = null;          // {x, y} 上次拖到的位置
function readPrefs() {
  try { return JSON.parse(fs.readFileSync(prefsPath, 'utf8')); } catch (_) { return {}; }
}
function loadPinned() { return readPrefs().pinned !== false; }
function savePrefs(patch) {
  try {
    const p = readPrefs();
    Object.assign(p, patch);
    fs.writeFileSync(prefsPath, JSON.stringify(p), 'utf8');
  } catch (_) {}
}
function savePinned() { savePrefs({ pinned }); }
function savePos(x, y) { savePrefs({ x, y }); }

// ---------- 屏幕与定位 ----------
let centerX = 0;
let topY = TOP_Y;
function measureScreen() {
  const wa = screen.getPrimaryDisplay().workArea;
  centerX = wa.x + wa.width / 2;
  topY = wa.y + TOP_Y;
}
function xFor(w) { return Math.max(0, Math.round(centerX - w / 2)); }

// 【尺寸唯一真源】窗口尺寸只能来自弹簧引擎的当前值，永远不读回 getBounds()。
// 根因：Windows + 透明无边框窗口上，win.setPosition() 会把窗口尺寸一起带偏
//       （实测拖拽 40 帧从 390×52 一路涨到 418×80），所以拖拽一律用 setBounds
//       显式带上 width/height，并且加一道 resize 守卫把任何越权尺寸拉回来。
function wantSize() {
  return {
    w: Math.max(1, Math.round(spring.w.x)),
    h: Math.max(1, Math.round(spring.h.x)),
  };
}

// 形变定位：以「持久化的水平中心锚点 + 当前顶边」为锚，向下长/向上收，
// 不再跳回屏幕中心 —— 拖到哪，展开收起的中心就在哪。
// 【为什么不每帧从 getBounds() 反推中心】Windows 上 setBounds 的 DIP↔物理像素换算
// 有 ±1px 抖动，逐帧 round(cx - w/2) 会把 0.5px 误差累积成「每轮右移几十像素」的漂移。
// 锚点只在「首次创建」和「拖拽到位」两个时刻写入一次，之后全程复用 → 漂移恒为 0。
let anchorCX = null;
function place(w, h) {
  if (!win) return;
  const W = Math.round(w), H = Math.round(h);
  const b = win.getBounds();
  if (dragGrab) {
    // 拖拽中：位置由拖拽逻辑决定，这里只同步尺寸，不和拖拽抢位置
    win.setBounds({ x: b.x, y: b.y, width: W, height: H });
    return;
  }
  if (anchorCX === null) anchorCX = b.x + W / 2;   // 首次：用当前命令尺寸算一次锚点
  win.setBounds({ x: Math.round(anchorCX - W / 2), y: b.y, width: W, height: H });
}

// 拖拽位置限制：至少留一部分在屏幕内，避免拖丢
function clampPos(x, y, w, h) {
  const wa = screen.getDisplayNearestPoint({ x: Math.round(x + w / 2), y: Math.round(y + h / 2) }).workArea;
  const minX = wa.x - w + 80, maxX = wa.x + wa.width - 80;
  const minY = wa.y - 8,         maxY = wa.y + wa.height - 40;
  return {
    x: Math.min(maxX, Math.max(minX, Math.round(x))),
    y: Math.min(maxY, Math.max(minY, Math.round(y))),
  };
}

const clamp01 = t => Math.max(0, Math.min(1, t));
const smoothstep = t => { const p = clamp01(t); return p * p * (3 - 2 * p); };

// ---------- 弹簧状态机 ----------
// 每根弹簧维护 { x 当前值, v 当前速度(单位/秒) }；打断时只换 target，不重置 v。
let expanded = false;
let reducedMotion = false;
let pendingData = null;
let animTimer = null;

const spring = {
  active: false,
  m:    { x: 0, v: 0, target: 0, k: 300, z: 0.9 },
  w:    { x: PILL_W, v: 0, target: PILL_W, k: 190, z: 0.9 },
  h:    { x: PILL_H, v: 0, target: PILL_H, k: 110, z: 0.94 },
};

// 圆角：前段保持「半圆胶囊感」（随高度长到 34px 封顶），后段收敛到 20px 圆角矩形。
// 与 WBtool 同函数 —— 渲染层对 r 的消费完全一致。
function radiusFor(m, h) {
  const cap = Math.min(h / 2, 34);
  const p = clamp01((m - 0.45) / 0.55);
  return cap + (20 - cap) * smoothstep(p);
}

function emit(p, m, w, h) {
  place(w, h);
  if (win) win.webContents.send('frame', { p, m, w, h, r: radiusFor(m, h), expanded });
}

function finishMorph() {
  spring.active = false;
  spring.m.x = spring.m.target; spring.m.v = 0;
  spring.w.x = spring.w.target; spring.w.v = 0;
  spring.h.x = spring.h.target; spring.h.v = 0;
  emit(1, spring.m.x, spring.w.x, spring.h.x);
  if (win) win.webContents.send('morph-end', { expanded });
  // 形变期间到达的扫描数据在此补发（此时渲染 DOM 不会再与形变撞车）
  if (pendingData) {
    const d = pendingData;
    pendingData = null;
    if (win) win.webContents.send('data', d);
  }
}

// 半隐式欧拉积分一根弹簧（dt 单位秒）。半隐式欧拉对弹簧系统无条件稳定，
// 帧率抖动 / 掉帧不会爆炸。
function stepSpring(s, dt) {
  const c = 2 * s.z * Math.sqrt(s.k);
  const a = -s.k * (s.x - s.target) - c * s.v;
  s.v += a * dt;
  s.x += s.v * dt;
  return Math.abs(s.x - s.target) < 0.5 && Math.abs(s.v) < 12;   // 已到位
}

let lastT = 0;
function tick() {
  if (!win || !spring.active) return;
  const now = performance.now();
  const dt = Math.min(0.04, Math.max(0.004, (now - lastT) / 1000));  // 钳制防卡顿爆积分
  lastT = now;

  const doneW = stepSpring(spring.w, dt);
  const doneH = stepSpring(spring.h, dt);
  const doneM = stepSpring(spring.m, dt);

  const w = Math.round(spring.w.x);
  const h = Math.round(spring.h.x);

  // p 仅作参考进度（渲染层不依赖），取三根弹簧中「最远剩余距离」的归一化
  const p = clamp01(1 - Math.max(
    Math.abs(spring.w.x - spring.w.target) / Math.max(1, PILL_W),
    Math.abs(spring.h.x - spring.h.target) / Math.max(1, PILL_H),
  ) / 1.2);
  emit(p, spring.m.x, w, h);

  if (doneW && doneH && doneM) { finishMorph(); return; }
  animTimer = setTimeout(tick, FRAME_MS);
}

function startMorph(expand, targetH) {
  if (!win) return;
  if (animTimer) { clearTimeout(animTimer); animTimer = null; }

  const cur = win.getSize();
  const tw = expand ? EXPAND_W : PILL_W;
  const th = expand
    ? Math.max(PILL_H, Math.min(MAX_H, Math.round(Number(targetH) || PILL_H)))
    : PILL_H;

  expanded = !!expand;
  const sameW = Math.abs(cur[0] - tw) < 1;
  const sameH = Math.abs(cur[1] - th) < 1;

  // 打断续接：不重置任何 x / v，只换目标与弹簧参数。
  // 展开态明细行数变化（settle）：只有 h 的目标在变，w / m 继续保持原目标 ——
  // 弹簧引擎天然支持「只调一根」，无需专门的 settle 分支。
  const S = expanded ? SPRING.expand : SPRING.collapse;
  spring.w.target = tw;       Object.assign(spring.w, { k: S.w.k, z: S.w.z });
  spring.h.target = th;       Object.assign(spring.h, { k: S.h.k, z: S.h.z });
  spring.m.target = expanded ? 1 : 0; Object.assign(spring.m, { k: S.m.k, z: S.m.z });

  if (reducedMotion) {
    // 系统「减弱动效」：所有弹簧直接落到终态，只发一帧
    spring.w.x = tw; spring.h.x = th; spring.m.x = spring.m.target;
    finishMorph();
    return;
  }

  if (sameW && sameH && Math.abs(spring.m.x - spring.m.target) < 0.001) {
    finishMorph();
    return;
  }
  spring.active = true;
  lastT = performance.now();
  tick();
}

function refresh() {
  try {
    scanner.scanOnce();
  } catch (err) {
    console.error('[island] 扫描失败:', err);
  }
  const d = scanner.summary();
  if (spring.active) pendingData = d;               // 形变期间缓存，结束补发
  else if (win) win.webContents.send('data', d);
}

// ---------- 窗口 ----------
function iconPath() { return path.join(__dirname, '..', 'assets', 'icon.ico'); }

function createWindow() {
  measureScreen();
  // 初始位置：优先用上次拖到的位置（并夹回可见范围），否则屏幕顶部正中
  const init = savedPos
    ? clampPos(savedPos.x, savedPos.y, PILL_W, PILL_H)
    : { x: Math.round(centerX - PILL_W / 2), y: topY };
  const initX = init.x;
  const initY = init.y;
  win = new BrowserWindow({
    width: PILL_W,
    height: PILL_H,
    x: initX,
    y: initY,
    title: 'WBtool 灵动岛',
    icon: iconPath(),
    frame: false,
    // 透明合成窗口（layered）：跨平台（Win10/11、macOS、Linux 皆可），
    // 圆角外真透明、CSS 抗锯齿边缘，胶囊轮廓完美。
    // 玻璃质感由渲染层纯 CSS 模拟（见 island.css），不依赖系统版本。
    transparent: true,
    backgroundColor: '#00000000',
    alwaysOnTop: pinned,
    skipTaskbar: pinned,
    resizable: false,
    movable: false,               // 用户拖拽由渲染层 + IPC 手动实现（见 drag-*）
    hasShadow: false,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.setHasShadow(false);        // 圆角外不糊黑边
  win.setAlwaysOnTop(pinned, pinned ? 'screen-saver' : 'normal');
  // 页面加载完成后再推一次扫描（增量，几乎零开销），避免启动后干等
  win.webContents.once('did-finish-load', () => refresh());
  // 渲染层诊断：把渲染进程的 console 与加载失败转写到 island-debug.log（仅 ISLAND_DEBUG=1）
  // Electron 36+ 该事件签名变为 (event, details)，这里两种签名都兼容。
  win.webContents.on('console-message', (e, a, message, line, sourceId) => {
    if (a && typeof a === 'object') {
      dlog('[renderer]', a.level, a.message, (a.sourceId || '').split(/[\\/]/).pop() + ':' + a.lineNumber);
    } else {
      dlog('[renderer]', 'L' + a, message, (sourceId || '').split(/[\\/]/).pop() + ':' + line);
    }
  });
  win.webContents.on('did-fail-load', (e, code, desc, url) => {
    dlog('[did-fail-load]', code, desc, url);
  });
  win.webContents.on('render-process-gone', (e, details) => {
    dlog('[render-gone]', JSON.stringify(details));
  });
  win.loadFile(path.join(__dirname, 'renderer', 'island.html'));
  win.once('ready-to-show', () => {
    place(PILL_W, PILL_H);
    win.showInactive();           // 不抢焦点
    emit(0, 0, PILL_W, PILL_H);   // 给渲染层一个确定的初始几何
  });
  win.on('closed', () => { win = null; });
  // 尺寸守卫：除了弹簧引擎自己驱动的形变，任何来源的尺寸变化都立刻纠回终态尺寸。
  // （兜住 setPosition / 系统 DPI 变更 / 外部工具 等一切「悄悄改大小」的路径）
  win.on('resize', () => {
    if (!win) return;
    const b = win.getBounds();
    dlog('[resize]', JSON.stringify(b), 'expanded=' + expanded, 'spring=' + spring.active);
    if (spring.active) return;              // 形变中：尺寸由引擎逐帧驱动
    const { w, h } = wantSize();
    if (Math.abs(b.width - w) > 1 || Math.abs(b.height - h) > 1) {
      dlog('[resize-clamp]', `${b.width}x${b.height} -> ${w}x${h}`);
      win.setBounds({ x: b.x, y: b.y, width: w, height: h });
    }
  });
  win.on('move', () => { if (win) dlog('[move]', JSON.stringify(win.getBounds())); });
}

// ---------- 托盘 / 置顶 ----------
function bringToFront() {
  if (!win) return;
  if (!win.isVisible()) win.showInactive();
  win.moveTop();
}

function toggleVisible() {
  if (!win) return;
  if (win.isVisible()) win.hide();
  else bringToFront();
}

function setPinned(locked) {
  pinned = !!locked;
  savePinned();
  if (win) {
    win.setAlwaysOnTop(pinned, pinned ? 'screen-saver' : 'normal');
    win.setSkipTaskbar(pinned);
    const wasVisible = win.isVisible();
    if (wasVisible) { win.hide(); win.showInactive(); }
    win.setAlwaysOnTop(pinned, pinned ? 'screen-saver' : 'normal');
  }
  buildTrayMenu();
  if (tray) tray.setToolTip(pinned
    ? 'WBtool 灵动岛 · 已锁定置顶'
    : 'WBtool 灵动岛 · 未锁定（任务栏或托盘可唤回）');
}

function buildTrayMenu() {
  if (!tray) return;
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '显示 / 隐藏灵动岛', click: toggleVisible },
    { label: '临时提到最前', click: bringToFront },
    { type: 'separator' },
    {
      label: '锁定置顶（始终最上层）',
      type: 'checkbox',
      checked: pinned,
      click: item => setPinned(item.checked),
    },
    { type: 'separator' },
    { label: '退出灵动岛', click: () => app.quit() },
  ]));
}

function createTray() {
  let img = null;
  try { img = nativeImage.createFromPath(iconPath()); } catch (_) {}
  if (!img || img.isEmpty()) {
    try { img = nativeImage.createFromPath(path.join(__dirname, 'renderer', 'icon.png')); } catch (_) {}
  }
  tray = new Tray(img);
  buildTrayMenu();
  tray.setToolTip(pinned
    ? 'WBtool 灵动岛 · 已锁定置顶'
    : 'WBtool 灵动岛 · 未锁定（任务栏或托盘可唤回）');
  tray.on('click', toggleVisible);
}

// ---------- IPC ----------
// 渲染层只传「是否展开 + 明细自然高度」；两个宽度与收起高度一律用主进程常量
ipcMain.on('resize', (e, { expanded: ex, h }) => startMorph(!!ex, h));
ipcMain.on('reduced-motion', (e, v) => { reducedMotion = !!v; });

// ---------- 拖拽（渲染层判定「拖」还是「点」，主进程负责移窗）----------
// 位置一律用「当前真实光标位置 - 按下时光标相对窗口的偏移」算，不依赖渲染层传的
// dx/dy（渲染层只负责判定「这是拖拽而不是点击」，只作触发信号）。
let dragGrab = null;    // { dx, dy } 按下瞬间光标相对窗口左上角的偏移
ipcMain.on('drag-start', () => {
  if (!win) return;
  const b = win.getBounds();
  const p = screen.getCursorScreenPoint();
  dragGrab = { dx: p.x - b.x, dy: p.y - b.y };
  dlog('[drag-start]', JSON.stringify(b), 'cursor=' + p.x + ',' + p.y);
});
ipcMain.on('drag-move', () => {
  if (!win || !dragGrab) return;
  const p = screen.getCursorScreenPoint();
  const { w, h } = wantSize();                 // 尺寸以弹簧引擎为准，绝不带偏
  const pos = clampPos(p.x - dragGrab.dx, p.y - dragGrab.dy, w, h);
  win.setBounds({ x: pos.x, y: pos.y, width: w, height: h });
  anchorCX = pos.x + w / 2;                     // 拖到新位置后，形变中心跟着走
  dlog('[drag-move]', 'cursor=' + p.x + ',' + p.y, 'bounds=' + JSON.stringify(win.getBounds()));
});
ipcMain.on('drag-end', () => {
  dragGrab = null;
  if (win) {
    const b = win.getBounds();
    savePos(b.x, b.y);          // 记住拖到的位置
    dlog('[drag-end]', JSON.stringify(b));
  }
});

app.whenReady().then(() => {
  prefsPath = path.join(app.getPath('userData'), 'island-prefs.json');
  const prefs = readPrefs();
  pinned = prefs.pinned !== false;
  savedPos = (typeof prefs.x === 'number' && typeof prefs.y === 'number')
    ? { x: prefs.x, y: prefs.y } : null;
  createWindow();
  createTray();
  refresh();
  setInterval(refresh, SCAN_MS);
  app.on('second-instance', () => bringToFront());
  app.on('before-quit', () => {
    if (win) { const b = win.getBounds(); savePos(b.x, b.y); }   // 退出前记住位置
    if (tray) tray.destroy();
  });
  screen.on('display-metrics-changed', () => {
    measureScreen();
    if (win) place(win.getSize()[0], win.getSize()[1]);
  });
});

app.on('window-all-closed', () => { /* 保持托盘常驻 */ });
