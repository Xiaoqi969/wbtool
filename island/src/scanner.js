#!/usr/bin/env node
'use strict';
// ============================================================================
// scanner.js — wbtool 灵动岛的 jsonl 增量扫描器（Node 版）
// ----------------------------------------------------------------------------
// 口径严格对齐 wb_usage_app.py / wbtool_island.py：
//   - 时间戳：>1e11 视为毫秒，否则秒；本地时间（非 UTC），与 HTML 报告一致
//   - Token：来自 usage，经 norm_usage 拆出 input/output/total
//   - 积分：来自 providerData.rawUsage.credit（LLM 调用行）+ type==="credit-usage" 事件
//   - 会话名：aiTitle（取不到回落到 cwd / "会话"）
//   - 进行中：会话最后一次活动在 ACTIVE_WINDOW_MIN 分钟内
// 增量扫描：按文件记录「已读字节偏移」，每分钟只读新增行，与日志大小解耦。
// ============================================================================
const fs = require('fs');
const path = require('path');
const os = require('os');

const ACTIVE_WINDOW_MIN = 5; // 5 分钟内有活动算「进行中」

function defaultProjectsDir() {
  if (process.env.WORKBUDDY_PROJECTS_DIR) return process.env.WORKBUDDY_PROJECTS_DIR;
  return path.join(os.homedir(), '.workbuddy', 'projects');
}

function num(v) {
  return (typeof v === 'number' && !Number.isNaN(v)) ? v : 0;
}

function normUsage(u) {
  if (!u || typeof u !== 'object') return null;
  const inp = u.input_tokens ?? u.inputTokens ?? 0;
  const out = u.output_tokens ?? u.outputTokens ?? 0;
  const tot = u.total_tokens ?? u.totalTokens ?? 0;
  let cache = u.cache_read_input_tokens ?? 0;
  if (!cache) {
    const det = u.inputTokensDetails ?? u.input_tokens_details ?? [];
    if (Array.isArray(det)) {
      cache = det.reduce((s, d) => s + (d && d.cached_tokens ? d.cached_tokens : 0), 0);
    }
  }
  const total = (!tot && (inp || out)) ? (inp + out) : tot;
  return { input: inp | 0, output: out | 0, total: total | 0, cache: cache | 0 };
}

// 本地日期（年-月-日），与 Python datetime.fromtimestamp(...).strftime("%Y-%m-%d") 对齐
function localDay(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function localClock(d) {
  if (!d) return '--:--';
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

class Scanner {
  constructor(projectsDir) {
    this.root = projectsDir || defaultProjectsDir();
    this.files = {};            // path -> { offset, buf }
    this.totals = {};           // day  -> { t, cr, in, out }
    this.sessionTokens = {};    // sid  -> { day: tokens }
    this.active = {};           // sid  -> { last(Date), title, proj }
  }

  scanOnce() {
    const now = new Date();
    if (fs.existsSync(this.root)) {
      const stat = fs.statSync(this.root);
      if (stat.isDirectory()) this._walk(this.root, now);
    }
    const cutoff = new Date(now.getTime() - ACTIVE_WINDOW_MIN * 60000);
    for (const s of Object.keys(this.active)) {
      if (this.active[s].last < cutoff) delete this.active[s];
    }
    return this;
  }

  _walk(dir, now) {
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); }
    catch { return; }
    for (const e of entries) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) this._walk(p, now);
      else if (e.name.endsWith('.jsonl')) this._scanFile(p, now);
    }
  }

  _recomputeAll(now) {
    this.totals = {};
    this.sessionTokens = {};
    this.active = {};
    this.files = {};
    this._walk(this.root, now);
  }

  _scanFile(p, now) {
    let size;
    try { size = fs.statSync(p).size; } catch { return; }
    let f = this.files[p];
    if (!f) { f = { offset: 0, buf: Buffer.alloc(0) }; this.files[p] = f; }
    if (size < f.offset) { this._recomputeAll(now); return; }
    if (size === f.offset) return;

    let raw;
    try {
      const fh = fs.openSync(p, 'r');
      raw = Buffer.alloc(size - f.offset);
      fs.readSync(fh, raw, 0, raw.length, f.offset);
      fs.closeSync(fh);
    } catch { return; }

    f.offset = size;
    const nl = raw.lastIndexOf(0x0a);
    if (nl === -1) { f.buf = Buffer.concat([f.buf, raw]); return; }
    const complete = Buffer.concat([f.buf, raw.subarray(0, nl + 1)]);
    f.buf = raw.subarray(nl + 1);
    f.offset = size - raw.length + complete.length;

    const text = complete.toString('utf8');
    for (const line of text.split('\n')) {
      const ln = line.trim();
      if (ln) this._processLine(ln, now);
    }
  }

  _addDay(day, inT, outT, tokens, credit, sid) {
    const td = this.totals[day] || (this.totals[day] = { t: 0, cr: 0, in: 0, out: 0 });
    td.t += tokens; td.cr += credit; td.in += inT; td.out += outT;
    if (sid) {
      const st = this.sessionTokens[sid] || (this.sessionTokens[sid] = {});
      st[day] = (st[day] || 0) + tokens;
    }
  }

  _processLine(line, now) {
    let o;
    try { o = JSON.parse(line); } catch { return; }
    if (!o || typeof o !== 'object') return;

    let ts = o.timestamp;
    let moment = null;
    // 注意单位：Python 的 fromtimestamp 收「秒」，JS 的 Date 收「毫秒」
    if (typeof ts === 'number') {
      moment = ts > 1e11 ? new Date(ts) : new Date(ts * 1000);
    }
    const day = moment ? localDay(moment) : 'unknown';

    const typ = typeof o.type === 'string' ? o.type : 'unknown';
    const sid = typeof o.sessionId === 'string' ? o.sessionId : '';
    const pd = (o.providerData && typeof o.providerData === 'object') ? o.providerData : {};

    if (typ === 'credit-usage') {
      const amt = pd.credit;
      if (typeof amt === 'number') this._addDay(day, 0, 0, 0, amt, sid);
    }

    const msg = (o.message && typeof o.message === 'object') ? o.message : {};
    const usage = msg.usage || pd.usage;
    const nu = normUsage(usage);
    if (nu) {
      const ru = (pd.rawUsage && typeof pd.rawUsage === 'object') ? pd.rawUsage : {};
      const credit = parseFloat(num(ru.credit));
      this._addDay(day, nu.input, nu.output, nu.total, credit, sid);
    }

    if (sid) {
      const title = typeof o.aiTitle === 'string' ? o.aiTitle : '';
      const cwd = typeof o.cwd === 'string' ? o.cwd : '';
      const s = this.active[sid] || (this.active[sid] = { last: moment || now, title: '', proj: '' });
      if (moment && s.last < moment) s.last = moment;
      if (title) s.title = title;
      if (cwd && !s.proj) s.proj = cwd;
    }
  }

  today() {
    const d = localDay(new Date());
    return this.totals[d] || { t: 0, cr: 0, in: 0, out: 0 };
  }

  activeList() {
    const d = localDay(new Date());
    const out = [];
    for (const sid of Object.keys(this.active)) {
      const v = this.active[sid];
      const tok = (this.sessionTokens[sid] && this.sessionTokens[sid][d]) || 0;
      out.push({ name: v.title || v.proj || '会话', last: v.last, tokens: tok });
    }
    out.sort((a, b) => b.last - a.last);
    return out;
  }

  // 供渲染层使用的精简摘要
  summary() {
    const t = this.today();
    const active = this.activeList().map(a => ({
      name: a.name,
      tokens: a.tokens,
      last: localClock(a.last),
    }));
    return {
      today: { token: t.t, credit: t.cr, in: t.in, out: t.out },
      active,
      files: Object.keys(this.files).length,
      updated: new Date().toTimeString().slice(0, 8),
    };
  }
}

module.exports = { Scanner, defaultProjectsDir, normUsage };

// 独立运行：node scanner.js  （便于校验扫描口径，无需 GUI）
if (require.main === module) {
  const s = new Scanner(process.env.WORKBUDDY_PROJECTS_DIR || undefined);
  s.scanOnce();
  const t = s.today();
  console.log(JSON.stringify({
    version: '1.2.0',
    today: localDay(new Date()),
    tokens: t.t,
    credit: Math.round(t.cr * 1000) / 1000,
    in: t.in,
    out: t.out,
    activeCount: s.activeList().length,
    active: s.activeList().map(a => ({ name: a.name, tokens: a.tokens, last: a.last.toISOString() })),
    files: Object.keys(s.files).length,
  }, null, 2));
}
