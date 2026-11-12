'use strict';
// ============================================================================
// main.js — Electron 主进程（小米超级岛同款形变引擎）
// ----------------------------------------------------------------------------
// 与 wbtool 原版（时间分段曲线）的核心区别：
//   · 真·弹簧物理：宽度 / 高度 / 内容进度 m 是三根独立弹簧，
//     每帧半隐式欧拉积分，不按总时长插值。
//   · 速度连续：动画中途反向打断时，当前位置与速度原样续接、只换目标 ——
//     这正是小米超级岛 / iOS 灵动岛「怎么打断都不闪跳」的物理本质。
//   · 三段式时序由弹簧参数天然涌现，不再手写分段曲线：
//     展开时宽度弹簧更硬（先横向铺开）、高度弹簧更软（随后向下落下）；
//     收起时反过来（先收高、再收宽）。
//
// 沿用 wbtool v1.3.0 的全部铁律：
//   1) 只有两个合法终态尺寸：390×52 / 620×H，绝不反推当前窗口尺寸当目标。
//   2) 屏幕中心只测一次；每帧 X = 固定中心 - 当前宽/2（绝对值），不累积漂移。
//   3) 一次 setBounds 原子设定位置与尺寸；显式关闭系统窗口阴影。
//   4) 窗口几何由主进程「单一时钟」驱动，每帧把 {m,w,h,r} 推给渲染层；
//      渲染层用同一帧数据画圆角与内容淡入淡出 —— 窗口与内容永不撕裂。
//   5) 形变期间不推扫描数据，避免 DOM 重排让文字抽搐；结束后补发。
//   6) IPC 契约与 preload API 和 wbtool 完全同名 —— 渲染层可直接互换。
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

let win = null;
let tray = null;
let scanner = new Scanner(PROJECTS);
const singleInstance = app.requestSingleInstanceLock();
if (!singleInstance) app.quit();

// ---------- 置顶偏好（userData 下的小 JSON，跨启动记忆）----------
let pinned = true;
let prefsPath = '';
function loadPinned() {
  try {
    return JSON.parse(fs.readFileSync(prefsPath, 'utf8')).pinned !== false;
  } catch (_) { return true; }
}
function savePinned() {
  try { fs.writeFileSync(prefsPath, JSON.stringify({ pinned }), 'utf8'); } catch (_) {}
}

// ---------- 屏幕与定位 ----------
let centerX = 0;
let topY = TOP_Y;
function measureScreen() {
  const wa = screen.getPrimaryDisplay().workArea;
  centerX = wa.x + wa.width / 2;
  topY = wa.y + TOP_Y;
}
function xFor(w) { return Math.max(0, Math.round(centerX - w / 2)); }
function place(w, h) {
  if (!win) return;
  win.setBounds({ x: xFor(w), y: topY, width: w, height: h });
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
// 与 wbtool 同函数 —— 渲染层对 r 的消费完全一致。
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
  const wasActive = spring.active;
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
  win = new BrowserWindow({
    width: PILL_W,
    height: PILL_H,
    title: 'wbtool 灵动岛',
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
    movable: false,
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
  // 页面加载完成后再推一次扫描（增量，几乎零开销），避免启动后干等 60s
  win.webContents.once('did-finish-load', () => refresh());
  win.loadFile(path.join(__dirname, 'renderer', 'island.html'));
  win.once('ready-to-show', () => {
    place(PILL_W, PILL_H);
    win.showInactive();           // 不抢焦点
    emit(0, 0, PILL_W, PILL_H);   // 给渲染层一个确定的初始几何
  });
  win.on('closed', () => { win = null; });
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
    ? 'wbtool 灵动岛 · 已锁定置顶'
    : 'wbtool 灵动岛 · 未锁定（任务栏或托盘可唤回）');
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
    ? 'wbtool 灵动岛 · 已锁定置顶'
    : 'wbtool 灵动岛 · 未锁定（任务栏或托盘可唤回）');
  tray.on('click', toggleVisible);
}

// ---------- IPC ----------
// 渲染层只传「是否展开 + 明细自然高度」；两个宽度与收起高度一律用主进程常量
ipcMain.on('resize', (e, { expanded: ex, h }) => startMorph(!!ex, h));
ipcMain.on('reduced-motion', (e, v) => { reducedMotion = !!v; });

app.whenReady().then(() => {
  prefsPath = path.join(app.getPath('userData'), 'island-prefs.json');
  pinned = loadPinned();
  createWindow();
  createTray();
  refresh();
  setInterval(refresh, SCAN_MS);
  app.on('second-instance', () => bringToFront());
  app.on('before-quit', () => { if (tray) tray.destroy(); });
  screen.on('display-metrics-changed', () => {
    measureScreen();
    if (win) place(win.getSize()[0], win.getSize()[1]);
  });
});

app.on('window-all-closed', () => { /* 保持托盘常驻 */ });
