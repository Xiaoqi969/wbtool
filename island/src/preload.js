'use strict';
// 安全桥：仅暴露渲染层需要的极简 API（contextIsolation 开启）
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('island', {
  // 主进程每 60s 推送扫描摘要（形变期间不推，结束后补发）
  onData: (cb) => ipcRenderer.on('data', (e, d) => cb(d)),
  // 形变动画每帧：{p, m, w, h, r, expanded} —— 窗口几何与内容视觉同一帧
  onFrame: (cb) => ipcRenderer.on('frame', (e, f) => cb(f)),
  onMorphEnd: (cb) => ipcRenderer.on('morph-end', (e, d) => cb(d)),
  // 渲染层只告诉主进程「是否展开」与「明细自然高度」；
  // 两个状态的宽度与收起高度都是主进程的绝对常量，避免尺寸逐次漂移。
  requestResize: (expanded, h) => ipcRenderer.send('resize', { expanded, h }),
  // 系统「减弱动效」偏好：主进程把动画压缩到 1 帧
  setReducedMotion: (v) => ipcRenderer.send('reduced-motion', !!v),
});
