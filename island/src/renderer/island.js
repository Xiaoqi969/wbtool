'use strict';
// ============================================================================
// island.js — 渲染层（小米超级岛质感）
//   · 接收主进程推送的扫描摘要，渲染收起态摘要 / 展开态明细
//   · 形变由主进程弹簧引擎每帧下发的 {m,w,h,r} 驱动：
//       --h / --r 画外形，--m 控制两层内容交叉淡入淡出，
//       --de 驱动明细各区块错落浮入（CSS calc 消费，同一帧数据）
//   · 弹簧的 m 带轻微过冲，明细浮现会有一次「放大回坐」——超级岛的内容弹性
//   · 点击只传「是否展开 + 明细自然高度」，动画中途反向打断不闪跳（速度连续）
// ============================================================================
const api = window.island;

const PILL_H = 52;
const clamp01 = t => Math.max(0, Math.min(1, t));

let data = {
  today: { token: 0, credit: 0, in: 0, out: 0, ratePerSec: 0 },
  active: [],
  files: 0,
  updated: '',
};
let names = [];
let idx = 0;
let expanded = false;
let m = 0;                 // 当前展开程度（弹簧值，可能略过冲 >1），由 frame 驱动
let lastDetailH = 0;       // 上一次同步给主进程的明细高度
let mqX = 0;
let mqRAF = null;

function fmt(n) {
  n = Math.round(Number(n) || 0);
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return String(n);
}
function fmtC(c) {
  c = Math.round((Number(c) || 0) * 100) / 100;
  if (c >= 1e3) return (c / 1e3).toFixed(1) + 'k';
  return c.toFixed(2);
}
function fmtRate(n) {
  n = Math.round(Number(n) || 0);
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k/s';
  return n + '/s';
}
function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// ---------- 数据 ----------
// 主进程保证形变期间不推数据，所以这里可以安全地重建 DOM
function render() {
  document.getElementById('tok').textContent = fmt(data.today.token);
  document.getElementById('cr').textContent = fmtC(data.today.credit);
  document.getElementById('din').textContent = fmt(data.today.in);
  document.getElementById('dout').textContent = fmt(data.today.out);
  document.getElementById('dtot').textContent = fmt(data.today.token);
  document.getElementById('dcr').textContent = fmtC(data.today.credit);
  document.getElementById('rate').textContent = fmtRate(data.today.ratePerSec);
  document.getElementById('drate').textContent = fmtRate(data.today.ratePerSec);
  document.getElementById('acount').textContent = data.active.length;
  document.getElementById('files').textContent = data.files;
  document.getElementById('upd').textContent = data.updated;

  const al = document.getElementById('alist');
  al.innerHTML = '';
  data.active.slice(0, 8).forEach(a => {
    const row = document.createElement('div');
    row.className = 'item';
    const left = document.createElement('span');
    left.className = 'nm';
    left.textContent = '• ' + a.name;
    const right = document.createElement('span');
    right.className = 'mt';
    right.textContent = fmt(a.tokens) + '  ' + a.last;
    row.appendChild(left);
    row.appendChild(right);
    al.appendChild(row);
  });

  names = data.active.map(a => a.name);
  idx = 0;
  buildMarquee();
  syncMarquee();
}

// ---------- 收起态走马灯 ----------
function buildMarquee() {
  const track = document.getElementById('mqTrack');
  mqX = 0;
  if (!names.length) {
    track.innerHTML = '<span class="empty">当前无进行中的对话</span>';
    track.style.transform = 'translateX(0)';
    return;
  }
  track.innerHTML = '<span class="label">对话</span>' + esc(names[idx % names.length]);
  const c = document.getElementById('content');
  mqX = c.clientWidth - 24;
  track.style.transform = `translateX(${mqX}px)`;
}

function shouldMarquee() {
  return m < 0.02 && !expanded && names.length > 0;
}

function stepMarquee() {
  mqRAF = null;
  if (!shouldMarquee()) return;
  const track = document.getElementById('mqTrack');
  mqX -= 0.6;
  if (mqX + track.scrollWidth < 0) {
    idx = (idx + 1) % names.length;
    buildMarquee();                 // 重置到右侧，播下一条
  } else {
    track.style.transform = `translateX(${mqX}px)`;
  }
  mqRAF = requestAnimationFrame(stepMarquee);
}

function syncMarquee() {
  if (mqRAF) { cancelAnimationFrame(mqRAF); mqRAF = null; }
  if (shouldMarquee()) mqRAF = requestAnimationFrame(stepMarquee);
}

// ---------- 形变：一帧数据同时驱动外形与内容 ----------
function applyMorph(f) {
  m = f.m;
  const root = document.documentElement;
  root.style.setProperty('--h', f.h + 'px');
  root.style.setProperty('--r', f.r.toFixed(1) + 'px');
  root.style.setProperty('--m', m.toFixed(4));
  // de：明细浮现进度 = m 的后段归一化；弹簧过冲时 de 会略 >1，
  // 让 .stg 的 translateY 轻微反向回坐 —— 即「放大回坐」的内容弹性
  const de = (m - 0.58) / 0.42;
  root.style.setProperty('--de', de.toFixed(4));

  // 摘要层在前段快速淡出并轻微上移收缩；明细层在后段淡入。
  // 注意终态：展开时摘要 opacity=0 + visibility:hidden —— 用户看到的只有明细。
  const co = clamp01(1 - m / 0.28);
  const deo = clamp01(de);
  const compact = document.getElementById('compact');
  const detail = document.getElementById('detail');

  compact.style.opacity = co.toFixed(3);
  compact.style.visibility = co < 0.01 ? 'hidden' : 'visible';
  compact.style.transform = `translateY(${(-5 * (1 - co)).toFixed(2)}px) scale(${(1 - 0.03 * (1 - co)).toFixed(4)})`;

  detail.style.opacity = deo.toFixed(3);
  detail.style.visibility = deo < 0.01 ? 'hidden' : 'visible';

  syncMarquee();
}

// #detail 是绝对定位、高度由内容自然撑开，测量值与当前窗口尺寸无关
function measureDetailH() {
  const d = document.getElementById('detail');
  return Math.max(PILL_H, Math.ceil(d.getBoundingClientRect().height) + 2);
}

// ---------- 点击：支持动画中途反向打断（位置与速度都从当前值续上）----------
function toggle() {
  expanded = !expanded;
  const h = expanded ? measureDetailH() : PILL_H;
  if (expanded) lastDetailH = h;
  api.requestResize(expanded, h);
}
document.getElementById('content').addEventListener('click', toggle);

// ---------- IPC ----------
api.onFrame(applyMorph);
api.onMorphEnd(d => {
  if (!d.expanded) buildMarquee();   // 收起完成后，走马灯从右侧重新开始
  syncMarquee();
});

api.onData(d => {
  data = d;
  render();
  // 展开态会话数变化会改变明细高度：只换高度弹簧的目标，其余弹簧不受影响
  if (expanded) {
    const h = measureDetailH();
    if (Math.abs(h - lastDetailH) > 1) {
      lastDetailH = h;
      api.requestResize(true, h);
    }
  }
});

// 系统「减弱动效」偏好 -> 主进程把弹簧直接压到终态
const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
api.setReducedMotion(reduce.matches);
if (reduce.addEventListener) {
  reduce.addEventListener('change', e => api.setReducedMotion(e.matches));
}

// 确定的初始几何（主进程 ready-to-show 也会再发一帧）
applyMorph({ p: 0, m: 0, w: 390, h: 52, r: 26, expanded: false });
