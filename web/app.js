/* 台股羅盤 前端（不需任何外部套件） */
"use strict";

// ====================================================================== 小工具
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const HZ = ["short", "mid", "long"];
const HZ_NAME = ["短期", "中期", "長期"];
const HZ_SPAN = ["約 1 週", "約 1 個月", "約 3 個月"];
const HZ_DAYS = ["一週", "一個月", "三個月"];
const store = {
  get(k, d) { try { const v = localStorage.getItem("twc." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("twc." + k, JSON.stringify(v)); } catch { } },
};

function fmtPx(x) {
  if (x == null) return "—";
  const a = Math.abs(x);
  return x.toLocaleString("zh-TW", { minimumFractionDigits: a >= 1000 ? 0 : a >= 100 ? 1 : 2, maximumFractionDigits: a >= 1000 ? 0 : a >= 100 ? 1 : 2 });
}
function fmtPct(x, d = 2, sign = true) {
  if (x == null || isNaN(x)) return "—";
  const v = (x * 100).toFixed(d);
  return (sign && x > 0 ? "+" : "") + v + "%";
}
function fmtInt(x) {
  if (x == null) return "—";
  const a = Math.abs(x);
  if (a >= 1e8) return (x / 1e8).toFixed(1) + " 億";
  if (a >= 1e4) return (x / 1e4).toFixed(a >= 1e5 ? 0 : 1) + " 萬";
  return Math.round(x).toLocaleString("zh-TW");
}
function cls(x) { return x > 0 ? "up" : x < 0 ? "down" : "flat"; }
function arrow(x) { return x > 0 ? "▲" : x < 0 ? "▼" : ""; }
function chgHtml(x, d = 2) {
  if (x == null) return '<span class="flat">—</span>';
  return `<span class="${cls(x)}">${arrow(x)}${fmtPct(Math.abs(x), d, false)}</span>`;
}
function dayStr(d) { return d ? `${+d.slice(4, 6)}/${+d.slice(6, 8)}` : ""; }
function dayFull(d) { return d ? `${d.slice(0, 4)}/${d.slice(4, 6)}/${d.slice(6, 8)}` : ""; }
function labelOf(s) {
  if (s == null) return "資料不足";
  if (s >= 75) return "強烈看多"; if (s >= 60) return "偏多"; if (s > 40) return "中立"; if (s > 25) return "偏空"; return "強烈看空";
}
function pillClass(s) {
  if (s == null) return "p-mid";
  if (s >= 75) return "p-up2"; if (s >= 60) return "p-up1"; if (s > 40) return "p-mid"; if (s > 25) return "p-dn1"; return "p-dn2";
}
function pill(s, title) {
  return `<span class="pill ${pillClass(s)}" title="${esc(title || labelOf(s))}">${s == null ? "—" : Math.round(s)}</span>`;
}
function sbar(s) {
  if (s == null) return '<div class="sbar"><div class="track"></div><span class="v muted">—</span></div>';
  const v = Math.max(0, Math.min(100, s));
  const left = v >= 50 ? 50 : v, width = Math.abs(v - 50);
  return `<div class="sbar" title="${labelOf(s)}"><div class="track"><div class="fill ${v >= 50 ? "u" : "d"}" style="left:${left}%;width:${width}%"></div></div><span class="v">${Math.round(s)}</span></div>`;
}

// 名詞解釋
const GLOSS = {
  score: "0～100 分，50 為中立。由約 30 個技術、籌碼、基本面指標加權而成，權重每天依「這些指標過去實際預測得準不準」自動調整，並納入大盤氣氛。75 分以上為強烈看多、25 分以下為強烈看空。",
  upprob: "過去一段時間裡，分數落在同一區間的股票，在這段期間後實際上漲的比例。這是歷史統計，不是保證。",
  range: "同一分數區間的股票，過去實際報酬的中間 60%（第 20 到第 80 百分位）。",
  rec: "推薦度：綜合權證本身品質（價格是否合理、買賣價差、剩餘天數、價內外、時間價值損耗、槓桿）與標的股票的看多／看空分數。",
  quality: "權證品質分數（0～100）：只看權證條件好不好，不管標的漲跌。",
  money: "價內外程度。正數是價內（已有履約價值），負數是價外。略為價外到價平通常最有效率。",
  lev: "實質槓桿：標的股票漲 1%，權證大約漲幾 %。",
  iv: "隱含波動率：權證價格反推出的波動率。和股票實際的歷史波動率相比，越接近或越低代表定價越便宜。",
  spread: "買賣價差：委買與委賣價的差距占價格的比例。越小越好，太大代表一買一賣就先虧在價差上。",
  theta: "每天光是時間經過，權證價值大約流失的比例（其他條件不變時）。",
  days: "距離最後交易日還有幾天。少於 45 天時間價值流失很快。",
  basis: "期貨價格減現貨（加權指數）。正價差代表市場對後市較樂觀，逆價差較保守；接近結算日會趨近於零。",
  foi: "外資在台指期的多空淨留倉口數。正數為淨多單，負數為淨空單；變化方向比絕對數字更值得注意。",
  pc: "選擇權賣權未平倉量 ÷ 買權未平倉量。台灣市場上比值偏高時常被解讀為支撐較強。",
  dtscore: "當沖分數（0～100）：依今天收盤後的短線因子排名，分數越高代表下一個交易日開盤買進、收盤賣出的勝算越高；越低則越適合先賣後買。權重每天依前一天的實際結果自動調整。",
  dtwin: "過去 60 個交易日，分數落在同一區間的股票，隔天照這個方向當沖、扣掉來回成本後真的賺錢的比例。",
  dttp: "同分數區間的股票，隔天盤中從開盤算起的最大有利幅度（中位數），可當停利參考。",
  dtsl: "同分數區間的股票，隔天盤中從開盤算起的最大不利幅度（中位數），可當停損參考。",
  oi: "未平倉量：市場上還沒平倉的契約口數。價漲量增代表新資金進場。",
};
function help(k) { return `<button class="help" type="button" data-help="${k}" aria-label="說明">?</button>`; }
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-help]");
  $$(".pop").forEach((p) => p.remove());
  if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const p = document.createElement("div");
  p.className = "pop"; p.textContent = GLOSS[b.dataset.help] || "";
  document.body.appendChild(p);
  const r = b.getBoundingClientRect();
  const w = Math.min(300, innerWidth - 24);
  p.style.width = w + "px";
  p.style.left = Math.max(12, Math.min(innerWidth - w - 12, r.left + scrollX - w / 2)) + "px";
  p.style.top = (r.bottom + scrollY + 8) + "px";
});

// ====================================================================== 圖示
const ICON = {
  home: '<path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z"/><path d="m14.5 9.5-1.6 4.3-4.4 1.7 1.6-4.4 4.4-1.6Z"/>',
  list: '<path d="M4 6h16M4 12h16M4 18h10"/>',
  warrant: '<path d="M4 18 9 12l4 3 7-9"/><path d="M15 6h5v5"/>',
  fut: '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
  star: '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9L12 3Z"/>',
  model: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.6M12 17h.01"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
  bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
};
const svgI = (k, fill) => `<svg viewBox="0 0 24 24" fill="${fill ? "currentColor" : "none"}" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[k]}</svg>`;

const NAV = [
  ["#/", "總覽", "home"], ["#/stocks", "選股", "list"], ["#/daytrade", "當沖", "bolt"], ["#/warrants", "權證", "warrant"],
  ["#/futures", "期貨", "fut"], ["#/watch", "自選", "star"], ["#/model", "模型成績單", "model"], ["#/help", "使用說明", "help"],
];
$("#nav").innerHTML = NAV.map(([h, t, i]) => `<a href="${h}" data-r="${h}">${svgI(i)}<span>${t}</span></a>`).join("");
$("#tabbar").innerHTML = NAV.slice(0, 6).map(([h, t, i]) => `<a href="${h}" data-r="${h}">${svgI(i)}<span>${t}</span></a>`).join("");

// ====================================================================== 資料
const cache = {};
async function api(path, { fresh = false } = {}) {
  if (!fresh && cache[path]) return cache[path];
  const r = await fetch("api/" + path, { cache: "no-store" });
  if (!r.ok) throw new Error(r.status === 404 ? "notfound" : "HTTP " + r.status);
  const j = await r.json();
  cache[path] = j;
  return j;
}
function clearCache() { for (const k in cache) delete cache[k]; }

const S = {
  hz: store.get("hz", 1),
  latest: null,
  byCode: {},
  watch: [],
  status: null,
};
async function loadLatest(fresh) {
  try {
    S.latest = await api("latest", { fresh });
    S.byCode = {};
    for (const r of S.latest.stocks) S.byCode[r.c] = r;
  } catch (e) { S.latest = null; }
}
async function loadWatch() { if (S.status && S.status.static) { S.watch = store.get("watch", []); return; } try { S.watch = await api("watchlist", { fresh: true }); } catch { S.watch = store.get("watch", []); } }
async function saveWatch() {
  store.set("watch", S.watch);
  if (S.status && S.status.static) return;
  try { await fetch("api/watchlist", { method: "POST", body: JSON.stringify(S.watch) }); } catch { }
}
function toggleWatch(code) {
  const i = S.watch.indexOf(code);
  if (i >= 0) S.watch.splice(i, 1); else S.watch.unshift(code);
  saveWatch();
  $$(`.star[data-star="${code}"]`).forEach((b) => b.classList.toggle("on", S.watch.includes(code)));
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-star]");
  if (!b) return;
  e.preventDefault(); e.stopPropagation();
  toggleWatch(b.dataset.star);
});
const starBtn = (c) => `<button class="star ${S.watch.includes(c) ? "on" : ""}" data-star="${c}" title="加入／移除自選" aria-label="加入自選">${svgI("star", S.watch.includes(c))}</button>`;

// ====================================================================== 投資期間切換
function renderSeg() {
  $("#hzseg").innerHTML = HZ_NAME.map((n, i) => `<button role="tab" aria-selected="${i === S.hz}" class="${i === S.hz ? "on" : ""}" data-hz="${i}" title="${HZ_SPAN[i]}">${n}</button>`).join("");
}
$("#hzseg").addEventListener("click", (e) => {
  const b = e.target.closest("[data-hz]");
  if (!b) return;
  setHz(+b.dataset.hz);
});
function setHz(i) { S.hz = i; store.set("hz", i); renderSeg(); route(); }

// ====================================================================== 羅盤儀表
let dialSeq = 0;
// 儀表：黃銅外框＋深色玻璃錶面＋LED 刻度（由 50 往分數方向點亮）＋立體指針
function mixHex(a, b, t) {
  const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const x = p(a), y = p(b);
  return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join("");
}
function ledColor(v) {
  const G = "#2fe39a", N = "#8f9bb3", R = "#ff4f5e";
  const t = Math.min(1, Math.abs(v - 50) / 22);
  return v <= 50 ? mixHex(N, G, t) : mixHex(N, R, t);
}
function dial(score, { size = "md", animate = true } = {}) {
  const id = "dl" + (++dialSeq);
  const C = 120, RF = 98, RL = 84;
  const pt = (deg, r) => { const a = deg * Math.PI / 180; return [C + r * Math.sin(a), C - r * Math.cos(a)]; };
  const angOf = (v) => -120 + v * 2.4;
  const s = score == null ? 50 : Math.max(0, Math.min(100, score));
  const ang = angOf(s);
  const anim = animate && !FX.reduce;
  const startAng = anim ? angOf(50) : ang;
  const txt = score == null ? "—" : Math.round(score);
  // LED 刻度
  let leds = "";
  const N = 49;
  for (let i = 0; i < N; i++) {
    const v = i / (N - 1) * 100;
    const lit = score != null && ((v >= 50 && v <= s + 0.01) || (v <= 50 && v >= s - 0.01));
    const col = ledColor(v);
    const delay = anim ? Math.abs(v - 50) * 14 : 0;
    leds += `<rect x="${C - 2.3}" y="${C - RL - 7}" width="4.6" height="14" rx="2" fill="${col}" transform="rotate(${angOf(v).toFixed(2)} ${C} ${C})"
      class="led ${lit ? "on" : ""}" style="${lit ? `--d:${delay}ms;` : ""}" ${lit ? `filter="url(#${id}glow)"` : ""}/>`;
  }
  // 錶面刻度與數字
  let ticks = "";
  for (let v = 0; v <= 100; v += 5) {
    const major = v % 25 === 0;
    const [x1, y1] = pt(angOf(v), RL - 13), [x2, y2] = pt(angOf(v), RL - (major ? 22 : 17));
    ticks += `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="#cfd8ea" stroke-opacity="${major ? .75 : .3}" stroke-width="${major ? 1.6 : 1}" stroke-linecap="round"/>`;
    if (major) {
      const [tx, ty] = pt(angOf(v), RL - 32);
      ticks += `<text x="${tx.toFixed(1)}" y="${(ty + 3.5).toFixed(1)}" text-anchor="middle" font-size="9.5" fill="#aeb9cf" fill-opacity=".8" font-family="var(--font-num)">${v}</text>`;
    }
  }
  const [lx, ly] = pt(angOf(0), RL - 4), [rx, ry] = pt(angOf(100), RL - 4);
  const svg = `<svg class="dial gauge" viewBox="0 0 240 240" role="img" aria-label="分數 ${txt}，${labelOf(score)}">
  <defs>
    <linearGradient id="${id}bz" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#fff3d1"/><stop offset=".22" stop-color="#d7ad5e"/><stop offset=".5" stop-color="#6e5222"/>
      <stop offset=".72" stop-color="#c79a4a"/><stop offset="1" stop-color="#3c2b10"/></linearGradient>
    <linearGradient id="${id}bz2" x1="1" y1="1" x2="0" y2="0">
      <stop offset="0" stop-color="#f6e2b0"/><stop offset=".45" stop-color="#7a5b25"/><stop offset="1" stop-color="#2a1e0a"/></linearGradient>
    <filter id="${id}brush" x="0" y="0" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency=".02 1.6" numOctaves="1" seed="7" result="n"/>
      <feColorMatrix in="n" type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .22 0" result="w"/>
      <feComposite in="w" in2="SourceGraphic" operator="in" result="wt"/>
      <feBlend in="SourceGraphic" in2="wt" mode="soft-light"/></filter>
    <radialGradient id="${id}face" cx=".5" cy=".38" r=".62">
      <stop offset="0" stop-color="#22304f"/><stop offset=".55" stop-color="#0e1527"/><stop offset="1" stop-color="#04070e"/></radialGradient>
    <radialGradient id="${id}vig" cx=".5" cy=".5" r=".5">
      <stop offset=".78" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".75"/></radialGradient>
    <linearGradient id="${id}glass" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#fff" stop-opacity=".16"/><stop offset=".55" stop-color="#fff" stop-opacity=".02"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
    <linearGradient id="${id}ndl" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#fff4d6"/><stop offset=".48" stop-color="#f0c66d"/><stop offset=".52" stop-color="#b8862f"/><stop offset="1" stop-color="#7a5719"/></linearGradient>
    <radialGradient id="${id}hub" cx=".35" cy=".3" r=".8">
      <stop offset="0" stop-color="#fff7df"/><stop offset=".35" stop-color="#d9b05f"/><stop offset=".8" stop-color="#6b4d1c"/><stop offset="1" stop-color="#2d1f08"/></radialGradient>
    <linearGradient id="${id}num" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#b9c4da"/></linearGradient>
    <filter id="${id}glow" x="-200%" y="-50%" width="500%" height="200%"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <filter id="${id}sh" x="-50%" y="-50%" width="200%" height="200%"><feDropShadow dx="2.5" dy="4" stdDeviation="2.6" flood-color="#000" flood-opacity=".7"/></filter>
    <filter id="${id}inner" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="3"/></filter>
  </defs>
  <circle cx="${C}" cy="${C}" r="117" fill="#000" opacity=".45" filter="url(#${id}inner)"/>
  <circle cx="${C}" cy="${C}" r="114" fill="url(#${id}bz)" filter="url(#${id}brush)"/>
  <circle cx="${C}" cy="${C}" r="106" fill="url(#${id}bz2)"/>
  <circle cx="${C}" cy="${C}" r="${RF + 2}" fill="#05070c"/>
  <circle cx="${C}" cy="${C}" r="${RF}" fill="url(#${id}face)"/>
  <circle cx="${C}" cy="${C}" r="${RF}" fill="url(#${id}vig)"/>
  <circle cx="${C}" cy="${C}" r="${RF - 3}" fill="none" stroke="#000" stroke-opacity=".6" stroke-width="5" filter="url(#${id}inner)"/>
  <g class="leds">${leds}</g>
  ${ticks}
  <text x="${lx.toFixed(1)}" y="${(ly + 16).toFixed(1)}" text-anchor="middle" font-size="10" fill="#2fe39a" fill-opacity=".85" font-weight="700">看空</text>
  <text x="${rx.toFixed(1)}" y="${(ry + 16).toFixed(1)}" text-anchor="middle" font-size="10" fill="#ff6b77" fill-opacity=".9" font-weight="700">看多</text>
  <text class="score" x="${C}" y="${C + 58}" text-anchor="middle" font-size="${size === "lg" ? 40 : 38}" fill="url(#${id}num)" style="paint-order:stroke" stroke="#000" stroke-opacity=".35" stroke-width="3"
    ${score != null ? `data-count="${Math.round(score)}" data-from="50"` : ""}>${txt}</text>
  <g class="needle" id="${id}" style="transform-origin:${C}px ${C}px;transform:rotate(${startAng}deg)">
    <g filter="url(#${id}sh)">
      <path d="M${C - 1.2} ${C - 76} L${C + 1.2} ${C - 76} L${C + 5.5} ${C} L${C + 4} ${C + 18} L${C - 4} ${C + 18} L${C - 5.5} ${C} Z" fill="url(#${id}ndl)"/>
    </g>
    <path d="M${C} ${C - 76} L${C} ${C + 18}" stroke="#fff" stroke-opacity=".35" stroke-width=".6"/>
  </g>
  <circle cx="${C}" cy="${C}" r="11" fill="url(#${id}hub)" filter="url(#${id}sh)"/>
  <circle cx="${C}" cy="${C}" r="4.2" fill="#1a1205" stroke="#f6dfa6" stroke-opacity=".6" stroke-width=".8"/>
  <path d="M${C - 92} ${C - 18} A ${RF} ${RF} 0 0 1 ${C + 92} ${C - 18} Q ${C} ${C - 46} ${C - 92} ${C - 18} Z" fill="url(#${id}glass)" pointer-events="none"/>
</svg>`;
  if (anim) requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(() => { const g = document.getElementById(id); if (g) g.style.transform = `rotate(${ang}deg)`; }, 60)));
  return svg;
}

// ====================================================================== 圖表
function tipAt(box, html, x, y) {
  let t = $(".tip", box);
  if (!t) { t = document.createElement("div"); t.className = "tip"; box.appendChild(t); }
  t.innerHTML = html;
  t.classList.remove("hide");
  const bw = box.clientWidth, tw = t.offsetWidth;
  t.style.left = Math.max(0, Math.min(bw - tw, x + 14 > bw - tw ? x - tw - 14 : x + 14)) + "px";
  t.style.top = Math.max(0, y - 10) + "px";
}
function hideTip(box) { const t = $(".tip", box); if (t) t.classList.add("hide"); }
function niceTicks(lo, hi, n = 4) {
  const span = hi - lo || 1, step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) || mag * 10;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}
function ma(arr, n) { const out = []; let s = 0; for (let i = 0; i < arr.length; i++) { s += arr[i]; if (i >= n) s -= arr[i - n]; out.push(i >= n - 1 ? s / n : null); } return out; }

function candleChart(box, hist, n) {
  const W = Math.max(300, box.clientWidth), H1 = W < 600 ? 220 : 300, H2 = 70, PAD_R = 54, PAD_T = 8, GAP = 14;
  const all = hist;
  const closes = all.map((r) => r[4]);
  const m20 = ma(closes, 20), m60 = ma(closes, 60);
  const start = Math.max(0, all.length - n);
  const d = all.slice(start), a20 = m20.slice(start), a60 = m60.slice(start);
  if (!d.length) { box.innerHTML = '<p class="note">沒有價格資料</p>'; return; }
  const lo = Math.min(...d.map((r) => r[3] ?? r[4]), ...a60.filter((x) => x != null)), hi = Math.max(...d.map((r) => r[2] ?? r[4]), ...a60.filter((x) => x != null));
  const pw = W - PAD_R, step = pw / d.length, bw = Math.max(1, Math.min(10, step * 0.62));
  const y = (v) => PAD_T + (hi - v) / (hi - lo || 1) * (H1 - PAD_T - 6);
  const vmax = Math.max(...d.map((r) => r[5] || 0)) || 1;
  const yv = (v) => H1 + GAP + H2 - (v / vmax) * H2;
  const xi = (i) => i * step + step / 2;
  let g = "";
  for (const t of niceTicks(lo, hi, 4)) g += `<line x1="0" x2="${pw}" y1="${y(t)}" y2="${y(t)}"/><text x="${W - 4}" y="${y(t) + 4}" text-anchor="end">${fmtPx(t)}</text>`;
  let xl = "", lastM = "";
  d.forEach((r, i) => { const m = r[0].slice(4, 6); if (m !== lastM && i > 2) xl += `<text x="${xi(i)}" y="${H1 + GAP + H2 + 14}" text-anchor="middle">${+m}月</text>`; lastM = m; });
  let c = "", v = "";
  d.forEach((r, i) => {
    const [, o, h, l, cl, vol] = r;
    const up = cl >= (o ?? cl);
    const col = up ? "var(--up)" : "var(--down)";
    const x = xi(i);
    if (h != null && l != null) c += `<line x1="${x}" x2="${x}" y1="${y(h)}" y2="${y(l)}" stroke="${col}" stroke-width="1"/>`;
    const yo = y(o ?? cl), yc = y(cl);
    c += `<rect x="${x - bw / 2}" y="${Math.min(yo, yc)}" width="${bw}" height="${Math.max(1, Math.abs(yo - yc))}" fill="${col}" rx="${bw > 4 ? 1 : 0}"/>`;
    v += `<rect x="${x - bw / 2}" y="${yv(vol || 0)}" width="${bw}" height="${H1 + GAP + H2 - yv(vol || 0)}" fill="${col}" opacity=".45"/>`;
  });
  const line = (arr, col) => { let p = ""; arr.forEach((val, i) => { if (val != null) p += (p ? "L" : "M") + xi(i).toFixed(1) + " " + y(val).toFixed(1); }); return p ? `<path d="${p}" fill="none" stroke="${col}" stroke-width="2"/>` : ""; };
  const Ht = H1 + GAP + H2 + 20;
  box.innerHTML = `<svg viewBox="0 0 ${W} ${Ht}" width="${W}" height="${Ht}" role="img" aria-label="股價走勢圖">
    <g class="grid axis">${g}</g>${c}${line(a20, "var(--brass)")}${line(a60, "var(--blue)")}
    <line x1="0" x2="${pw}" y1="${H1 + GAP + H2}" y2="${H1 + GAP + H2}" stroke="var(--line)"/>${v}
    <g class="axis">${xl}<text x="${W - 4}" y="${H1 + GAP + 10}" text-anchor="end">成交量</text></g>
    <line class="xh" x1="0" x2="0" y1="0" y2="${H1 + GAP + H2}" stroke="var(--ink-2)" stroke-dasharray="3 3" opacity="0"/>
    <rect x="0" y="0" width="${pw}" height="${H1 + GAP + H2}" fill="transparent" class="hit"/></svg>
    <div class="legend"><span><i style="background:var(--brass)"></i>月線（20 日均價）</span><span><i style="background:var(--blue)"></i>季線（60 日均價）</span><span>紅K＝收盤高於開盤，綠K＝收盤低於開盤</span></div>`;
  const svg = $("svg", box), xh = $(".xh", box);
  const move = (ev) => {
    const r = svg.getBoundingClientRect();
    const px = (ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left;
    const i = Math.max(0, Math.min(d.length - 1, Math.floor(px / (r.width / W) / step)));
    const row = d[i], prev = d[i - 1] || all[start + i - 1];
    xh.setAttribute("x1", xi(i)); xh.setAttribute("x2", xi(i)); xh.setAttribute("opacity", 1);
    const ch = prev ? row[4] / prev[4] - 1 : null;
    tipAt(box, `${dayFull(row[0])}<br>收 <b>${fmtPx(row[4])}</b> ${ch != null ? chgHtml(ch).replace(/class="(up|down)"/, 'style="color:inherit"') : ""}<br>開 ${fmtPx(row[1])}　高 ${fmtPx(row[2])}　低 ${fmtPx(row[3])}<br>量 ${fmtInt(row[5])} 張${a20[i] ? `<br>月線 ${fmtPx(a20[i])}` : ""}${a60[i] ? `　季線 ${fmtPx(a60[i])}` : ""}`, xi(i) * r.width / W, 10);
  };
  const hit = $(".hit", box);
  hit.addEventListener("mousemove", move); hit.addEventListener("touchmove", move, { passive: true });
  hit.addEventListener("mouseleave", () => { xh.setAttribute("opacity", 0); hideTip(box); });
}

function lineChart(box, labels, ys, { color = "var(--blue)", fmt = (v) => v, height = 170, zero = false, ref = null, refLabel = "" } = {}) {
  const W = Math.max(260, box.clientWidth), H = height, PR = 52, PT = 8, PB = 22;
  const vals = ys.filter((v) => v != null);
  if (vals.length < 2) { box.innerHTML = '<p class="note">資料累積中</p>'; return; }
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  if (ref != null) { lo = Math.min(lo, ref); hi = Math.max(hi, ref); }
  const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
  const pw = W - PR, n = ys.length;
  const x = (i) => n === 1 ? pw / 2 : i / (n - 1) * pw;
  const y = (v) => PT + (hi - v) / (hi - lo) * (H - PT - PB);
  let g = "";
  for (const t of niceTicks(lo, hi, 3)) g += `<line x1="0" x2="${pw}" y1="${y(t)}" y2="${y(t)}"/><text x="${W - 4}" y="${y(t) + 4}" text-anchor="end">${fmt(t)}</text>`;
  let p = "";
  ys.forEach((v, i) => { if (v != null) p += (p ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); });
  let xl = "";
  const every = Math.max(1, Math.round(n / 5));
  labels.forEach((l, i) => { if (i % every === 0) xl += `<text x="${x(i)}" y="${H - 4}" text-anchor="middle">${dayStr(l) || l}</text>`; });
  const refL = ref != null ? `<line x1="0" x2="${pw}" y1="${y(ref)}" y2="${y(ref)}" stroke="var(--ink-2)" stroke-dasharray="4 4"/><text x="4" y="${y(ref) - 5}" font-size="11" fill="var(--ink-2)">${esc(refLabel)}</text>` : "";
  const gid = "lg" + Math.random().toString(36).slice(2, 8);
  const first = ys.findIndex((v) => v != null), lastI = ys.length - 1 - [...ys].reverse().findIndex((v) => v != null);
  const area = p ? `${p}L${x(lastI).toFixed(1)} ${H - PB}L${x(first).toFixed(1)} ${H - PB}Z` : "";
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><defs><linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".28"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
    <g class="grid axis">${g}${xl}</g>${refL}
    <path d="${area}" fill="url(#${gid})"/>
    <path d="${p}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>
    <circle class="dot" r="5" fill="${color}" stroke="var(--surface)" stroke-width="2" opacity="0"/>
    <rect class="hit" x="0" y="0" width="${pw}" height="${H}" fill="transparent"/></svg>`;
  const svg = $("svg", box), dot = $(".dot", box);
  const move = (ev) => {
    const r = svg.getBoundingClientRect();
    const px = ((ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left) * W / r.width;
    let i = Math.round(px / pw * (n - 1)); i = Math.max(0, Math.min(n - 1, i));
    if (ys[i] == null) return;
    dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(ys[i])); dot.setAttribute("opacity", 1);
    tipAt(box, `${dayFull(labels[i]) || labels[i]}<br><b>${fmt(ys[i])}</b>`, x(i) * r.width / W, y(ys[i]) * r.height / H - 30);
  };
  const hit = $(".hit", box);
  hit.addEventListener("mousemove", move); hit.addEventListener("touchmove", move, { passive: true });
  hit.addEventListener("mouseleave", () => { dot.setAttribute("opacity", 0); hideTip(box); });
}

function barChart(box, labels, ys, { fmt = fmtInt, height = 110, unit = "" } = {}) {
  const W = Math.max(240, box.clientWidth), H = height, PR = 48, PT = 6, PB = 18;
  const vals = ys.filter((v) => v != null);
  if (!vals.length) { box.innerHTML = '<p class="note">尚無資料</p>'; return; }
  const m = Math.max(1, ...vals.map(Math.abs));
  const pw = W - PR, n = ys.length, step = pw / n, bw = Math.max(2, step - 2);
  const y0 = PT + (H - PT - PB) / 2, sc = (H - PT - PB) / 2 / m;
  let b = "";
  ys.forEach((v, i) => {
    if (v == null) return;
    const h = Math.max(1, Math.abs(v) * sc);
    b += `<rect x="${i * step + 1}" y="${v >= 0 ? y0 - h : y0}" width="${bw}" height="${h}" rx="2" fill="${v >= 0 ? "var(--up)" : "var(--down)"}"/>`;
  });
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><g class="axis grid">
    <line x1="0" x2="${pw}" y1="${y0}" y2="${y0}"/><text x="${W - 4}" y="${PT + 9}" text-anchor="end">${fmt(m)}</text><text x="${W - 4}" y="${H - PB}" text-anchor="end">-${fmt(m)}</text>
    <text x="0" y="${H - 4}">${dayStr(labels[0])}</text><text x="${pw}" y="${H - 4}" text-anchor="end">${dayStr(labels[n - 1])}</text></g>${b}
    <rect class="hit" x="0" y="0" width="${pw}" height="${H}" fill="transparent"/></svg>`;
  const svg = $("svg", box);
  const move = (ev) => {
    const r = svg.getBoundingClientRect();
    const px = ((ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left) * W / r.width;
    const i = Math.max(0, Math.min(n - 1, Math.floor(px / step)));
    if (ys[i] == null) return;
    tipAt(box, `${dayFull(labels[i])}<br><b>${ys[i] > 0 ? "買超" : ys[i] < 0 ? "賣超" : "持平"} ${fmt(Math.abs(ys[i]))}${unit}</b>`, i * step * r.width / W, 0);
  };
  const hit = $(".hit", box);
  hit.addEventListener("mousemove", move); hit.addEventListener("touchmove", move, { passive: true });
  hit.addEventListener("mouseleave", () => hideTip(box));
}

// ====================================================================== 共用列
function stockRow(r, { mode = "one" } = {}) {
  if (!r) return "";
  const nm = `<div class="nm"><b>${esc(r.n)}</b><span>${r.c}　${esc(r.m)}${r.ind ? "・" + esc(r.ind) : ""}</span><span class="pxm small"> ${fmtPx(r.px)} ${chgHtml(r.chg)}</span></div>`;
  if (mode === "three") {
    return `<a class="row s3" href="#/stock/${r.c}">${nm}<div class="px">${fmtPx(r.px)}</div><div class="ch">${chgHtml(r.chg)}</div>
      ${r.s.map((s, i) => `<div style="text-align:center">${pill(s, HZ_NAME[i] + "：" + labelOf(s))}</div>`).join("")}${starBtn(r.c)}</a>`;
  }
  return `<a class="row" href="#/stock/${r.c}">${nm}<div class="px">${fmtPx(r.px)}</div><div class="ch">${chgHtml(r.chg)}</div><div class="sb">${sbar(r.s[S.hz])}</div><div class="pm">${pill(r.s[S.hz])}</div></a>`;
}
function rowsHead3(sortKey, dir) {
  const b = (k, t) => `<button data-sort="${k}" class="${sortKey === k ? "on" : ""}">${t}${sortKey === k ? (dir > 0 ? " ↑" : " ↓") : ""}</button>`;
  return `<div class="row head s3"><div>${b("name", "股票")}</div><div class="hpx" style="text-align:right">${b("px", "股價")}</div><div class="hpx" style="text-align:right">${b("chg", "漲跌")}</div>
    ${HZ_NAME.map((n, i) => `<div style="text-align:center">${b("s" + i, n)}</div>`).join("")}<div></div></div>`;
}

// ====================================================================== 路由
const view = $("#view");
let routeToken = 0;
async function route() {
  const tok = ++routeToken;
  const hash = location.hash || "#/";
  $$("[data-r]").forEach((a) => {
    const r = a.dataset.r;
    a.classList.toggle("on", r === "#/" ? hash === "#/" : hash.startsWith(r));
  });
  $$(".pop").forEach((p) => p.remove());
  const [, page, arg] = hash.match(/^#\/?([^/]*)\/?(.*)$/) || [];
  if (!S.latest && !["help"].includes(page)) { renderOnboarding(); return; }
  try {
    if (!page) await vHome(tok);
    else if (page === "stocks") await vStocks(tok);
    else if (page === "stock") await vStock(tok, decodeURIComponent(arg));
    else if (page === "warrants") await vWarrants(tok, decodeURIComponent(arg || ""));
    else if (page === "futures") await vFutures(tok);
    else if (page === "daytrade") await vDayTrade(tok);
    else if (page === "watch") await vWatch(tok);
    else if (page === "model") await vModel(tok);
    else if (page === "help") await vHelp(tok);
    else await vHome(tok);
  } catch (e) {
    console.error(e);
    if (tok === routeToken) view.innerHTML = `<div class="card empty"><h2>這一頁暫時無法顯示</h2><p>${esc(e.message === "notfound" ? "找不到這檔的分析資料，可能是新上市、下市，或成交太少。" : "讀取資料時發生問題：" + e.message)}</p><a class="btn" href="#/">回到總覽</a></div>`;
  }
  if (tok === routeToken) { FX.enhance(view); if (!location.hash.startsWith("#/stock/")) scrollTo(0, 0); }
}
addEventListener("hashchange", route);

const disclaimer = `<p class="disclaimer">本工具依證交所、櫃買中心、期交所公開資料自動計算，分數與機率是歷史統計，不保證未來結果，也不構成投資建議。投資前請自行判斷並控制風險。</p>`;

// ====================================================================== 總覽
async function vHome(tok) {
  const L = S.latest, M = L.market, hz = HZ[S.hz], mh = M.horizons[hz];
  const liquid = L.stocks.filter((r) => !r.etf && r.val >= 0.3 && r.s[S.hz] != null);
  const top = [...liquid].sort((a, b) => b.s[S.hz] - a.s[S.hz]).slice(0, 10);
  const bot = [...liquid].sort((a, b) => a.s[S.hz] - b.s[S.hz]).slice(0, 10);
  const facts = [];
  if (M.up != null) facts.push(`今天上市股票上漲 ${M.up} 家、下跌 ${M.down} 家`);
  if (M.foi != null) facts.push(`外資台指期${M.foi >= 0 ? "淨多單" : "淨空單"} ${fmtInt(Math.abs(M.foi))} 口${M.foi5 != null ? `，5 天來${M.foi5 >= 0 ? "偏多增加" : "偏空增加"} ${fmtInt(Math.abs(M.foi5))} 口` : ""}`);
  if (mh.pos.length) facts.push(`加分：${mh.pos.join("、")}`);
  if (mh.neg.length) facts.push(`扣分：${mh.neg.join("、")}`);
  if (mh.similar_n) facts.push(`過去 ${mh.similar_n} 次類似情況，${HZ_DAYS[S.hz]}後大盤上漲 ${mh.similar_up} 次（平均 ${mh.similar_avg > 0 ? "+" : ""}${mh.similar_avg}%）`);
  const mod = L.model[hz];
  const ind = L.industries || [];
  const w = S.watch.map((c) => S.byCode[c]).filter(Boolean).slice(0, 6);
  let picks = [];
  try { picks = (await api("warrant_picks")).picks.slice(0, 5); } catch { }
  if (tok !== routeToken) return;
  view.innerHTML = `
  <h1 class="grad">今天的台股氣氛</h1>
  <p class="lead">${dayFull(L.day)} 收盤資料・${HZ_NAME[S.hz]}（${HZ_SPAN[S.hz]}）觀點。上方可切換短期、中期、長期。</p>
  <section class="card hero glow"><span class="glow-ring"></span>
    <div class="dial-wrap">${dial(mh.score, { size: "lg" })}<div class="verdict">大盤${mh.label}</div></div>
    <div class="hero-side">
      <div class="idx"><span class="muted">加權指數</span><span class="big" data-count="${M.taiex}" data-dec="2">${fmtPx(M.taiex)}</span><span class="chg">${chgHtml(M.taiex_chg)}</span></div>
      <div class="hz3">${HZ.map((h, i) => `<button class="hzbox ${i === S.hz ? "on" : ""}" data-hz2="${i}"><div class="t">${HZ_NAME[i]}<span class="hsp">・${HZ_SPAN[i]}</span></div><div class="v" data-count="${Math.round(M.horizons[h].score)}" data-from="50">${Math.round(M.horizons[h].score)}</div><div class="l">${M.horizons[h].label}</div></button>`).join("")}</div>
      <ul class="facts">${facts.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
    </div>
  </section>
  <div class="grid g2 section">
    <section class="card flush"><div class="card-h" style="padding:18px 22px 4px"><h2>${HZ_NAME[S.hz]}看多前 10 名</h2>${help("score")}<a class="more" href="#/stocks">看全部股票</a></div><div class="list">${top.map((r) => stockRow(r)).join("")}</div></section>
    <section class="card flush"><div class="card-h" style="padding:18px 22px 4px"><h2>${HZ_NAME[S.hz]}看空前 10 名</h2><a class="more" href="#/stocks?asc">看全部股票</a></div><div class="list">${bot.map((r) => stockRow(r)).join("")}</div></section>
  </div>
  <div class="grid g2 section">
    <section class="card"><div class="card-h"><h2>產業強弱</h2><span class="note">各產業個股的平均${HZ_NAME[S.hz]}分數</span></div>
      <div class="bars" id="indbars">${indBars(ind, 12)}</div>
      ${ind.length > 12 ? `<button class="btn" style="margin-top:12px" id="indall">顯示全部 ${ind.length} 個產業</button>` : ""}</section>
    <section class="card"><div class="card-h"><h2>模型最近準不準</h2><a class="more" href="#/model">看成績單</a></div>
      ${modelSentence(mod, S.hz)}
      <div class="card-h" style="margin-top:18px"><h2>今日權證精選</h2>${help("rec")}<a class="more" href="#/warrants">看更多</a></div>
      ${picks.length ? `<div class="list" style="margin:0 -22px">${picks.map((p) => `<a class="row" href="#/warrants/${p.u}"><div class="nm"><b>${esc(p.n)}</b><span>${p.c}・標的 ${esc(p.un)}・${p.t === "C" ? "認購" : "認售"}</span></div><div class="px">${fmtPx(p.P)}</div><div class="ch"><span class="q ${p.rec >= 70 ? "hi" : "md"}">${Math.round(p.rec)}</span></div><div class="sb small muted">${esc(p.why[0] || "")}</div></a>`).join("")}</div>` : '<p class="note">權證資料準備中。</p>'}
    </section>
  </div>
  <p class="note section" style="text-align:center"><a href="#/model" style="color:var(--brass)">模型成績單</a>　·　<a href="#/help" style="color:var(--brass)">使用說明</a></p>
  ${w.length ? `<section class="card flush section"><div class="card-h" style="padding:18px 22px 4px"><h2>我的自選</h2><a class="more" href="#/watch">管理自選</a></div><div class="list">${rowsHead3("", 0)}${w.map((r) => stockRow(r, { mode: "three" })).join("")}</div></section>` : ""}
  ${disclaimer}`;
  $$("[data-hz2]").forEach((b) => b.addEventListener("click", () => setHz(+b.dataset.hz2)));
  const ia = $("#indall");
  if (ia) ia.addEventListener("click", () => { $("#indbars").innerHTML = indBars(ind, 999); ia.remove(); });
}
function indBars(ind, n) {
  const arr = [...ind].sort((a, b) => b.s[S.hz] - a.s[S.hz]).slice(0, n);
  return arr.map((x) => {
    const s = x.s[S.hz], half = Math.min(50, Math.abs(s - 50) * 2), left = s >= 50 ? 50 : 50 - half, width = half;
    return `<div class="b"><span class="nm" title="${esc(x.ind)}（${x.n} 檔）">${esc(x.ind)}</span><div class="sbar"><div class="track"><div class="fill ${s >= 50 ? "u" : "d"}" style="left:${left}%;width:${width}%"></div></div></div><span class="v">${Math.round(s)}</span></div>`;
  }).join("");
}
function modelSentence(m, i) {
  if (!m || m.top_hit == null) return '<p class="note">資料還在累積，至少需要幾週的歷史才能檢驗模型準確度。</p>';
  const diff = (m.top_hit - m.base_hit) * 100;
  return `<p style="margin:0">過去 ${m.eval_days} 個交易日回測：${HZ_NAME[i]}分數前 20% 的股票，${HZ_DAYS[i]}後有 <b class="num" style="font-size:18px">${(m.top_hit * 100).toFixed(0)}%</b> 上漲，全市場平均為 ${(m.base_hit * 100).toFixed(0)}%（${diff >= 0 ? "高" : "低"} ${Math.abs(diff).toFixed(1)} 個百分點）。</p>
    ${m.spread_avg != null ? `<p class="note" style="margin:6px 0 0">分數前 20% 平均比後 20% ${m.spread_avg >= 0 ? "多賺" : "少賺"} ${Math.abs(m.spread_avg * 100).toFixed(2)}%，這個關係在 ${(m.spread_win * 100).toFixed(0)}% 的日子成立。</p>` : ""}`;
}

// ====================================================================== 選股
let stockState = { sort: "s", dir: -1, mk: "", ind: "", type: "stock", minval: 0.1, limit: 100, q: "" };
async function vStocks(tok) {
  if (location.hash.includes("asc")) { stockState.sort = "s"; stockState.dir = 1; history.replaceState(null, "", "#/stocks"); }
  const L = S.latest;
  const inds = [...new Set(L.stocks.map((r) => r.ind).filter(Boolean))].sort();
  view.innerHTML = `<h1>選股</h1><p class="lead">所有上市櫃股票與 ETF 的短、中、長期分數。點欄位名稱可以排序，點星號加入自選。</p>
    <div class="filters">
      <input type="text" id="fq" placeholder="篩選名稱或代號" value="${esc(stockState.q)}" aria-label="篩選">
      <select id="fmk" aria-label="市場"><option value="">上市＋上櫃</option><option>上市</option><option>上櫃</option></select>
      <select id="ftype" aria-label="類型"><option value="stock">只看股票</option><option value="etf">只看 ETF</option><option value="all">股票＋ETF</option></select>
      <select id="find" aria-label="產業"><option value="">全部產業</option>${inds.map((i) => `<option>${esc(i)}</option>`).join("")}</select>
      <select id="fval" aria-label="成交金額"><option value="0">成交金額不限</option><option value="0.1">日均成交 1000 萬以上</option><option value="1">日均成交 1 億以上</option><option value="5">日均成交 5 億以上</option></select>
    </div>
    <section class="card flush"><div class="list" id="slist"></div></section>${disclaimer}`;
  $("#fmk").value = stockState.mk; $("#ftype").value = stockState.type; $("#find").value = stockState.ind; $("#fval").value = String(stockState.minval);
  const upd = () => {
    stockState.q = $("#fq").value.trim(); stockState.mk = $("#fmk").value; stockState.type = $("#ftype").value;
    stockState.ind = $("#find").value; stockState.minval = +$("#fval").value; stockState.limit = 100; drawStocks();
  };
  ["#fq"].forEach((s) => $(s).addEventListener("input", upd));
  ["#fmk", "#ftype", "#find", "#fval"].forEach((s) => $(s).addEventListener("change", upd));
  drawStocks();
}
function drawStocks() {
  const st = stockState, q = st.q.toLowerCase();
  let arr = S.latest.stocks.filter((r) =>
    (!st.mk || r.m === st.mk) && (st.type === "all" || (st.type === "etf") === r.etf) && (!st.ind || r.ind === st.ind) &&
    (r.val || 0) >= st.minval && (!q || r.c.includes(q) || r.n.toLowerCase().includes(q)));
  const key = st.sort === "s" ? "s" + S.hz : st.sort;
  const get = (r) => key === "name" ? r.c : key === "px" ? r.px : key === "chg" ? r.chg : r.s[+key.slice(1)];
  arr.sort((a, b) => { const x = get(a), y = get(b); if (x == null) return 1; if (y == null) return -1; return (x > y ? 1 : x < y ? -1 : 0) * st.dir; });
  const box = $("#slist");
  box.innerHTML = rowsHead3(key, st.dir) + arr.slice(0, st.limit).map((r) => stockRow(r, { mode: "three" })).join("") +
    (arr.length > st.limit ? `<div style="padding:14px 22px"><button class="btn" id="more">再顯示 100 檔（共 ${arr.length} 檔）</button></div>` : "") +
    (arr.length ? "" : '<div class="empty"><p>沒有符合條件的股票，試著放寬篩選。</p></div>');
  $$("[data-sort]", box).forEach((b) => b.addEventListener("click", (e) => {
    e.preventDefault();
    const k = b.dataset.sort;
    if ((st.sort === "s" ? "s" + S.hz : st.sort) === k) st.dir = -st.dir; else { st.sort = k; st.dir = k === "name" ? 1 : -1; }
    drawStocks();
  }));
  const m = $("#more", box);
  if (m) m.addEventListener("click", () => { st.limit += 100; drawStocks(); });
}

// ====================================================================== 個股
async function vStock(tok, code) {
  const d = await api("stock/" + code);
  if (tok !== routeToken) return;
  const r = S.byCode[code] || {};
  const last = d.hist[d.hist.length - 1] || [];
  const prev = d.hist[d.hist.length - 2];
  const chg = r.chg ?? (prev ? last[4] / prev[4] - 1 : null);
  const hzs = HZ.map((h) => d.h[h]);
  const base = HZ.map((h) => S.latest.model?.[h]?.base_hit ?? null);
  const cur = hzs[S.hz];
  const f = d.fund || {};
  const fv = d.factors || {};
  const chips = d.chips || [];
  const sum = (k, n) => chips.slice(-n).reduce((a, c) => a + (c[k] || 0), 0);
  const mbNow = chips.length ? chips[chips.length - 1][4] : null, mb20 = chips.length > 20 ? chips[chips.length - 21][4] : null;
  view.innerHTML = `
  <div class="sh">
    <div class="sht"><h1 style="margin-bottom:2px">${esc(d.n)} <span class="num muted" style="font-size:22px">${d.c}</span></h1>
      <div class="muted small">${esc(d.m)}${d.ind ? "・" + esc(d.ind) : ""}・${dayFull(d.day)} 收盤</div></div>
    <div class="px" data-count="${last[4]}" data-dec="${last[4] >= 1000 ? 0 : last[4] >= 100 ? 1 : 2}">${fmtPx(last[4])}</div><div class="chg">${chgHtml(chg)}</div>
    <div class="shb">${starBtn(code).replace('class="star', 'class="btn star').replace("</button>", "<span>自選</span></button>")}
      ${d.dt != null ? `<a class="btn" href="#/daytrade" title="下一個交易日的當沖分數">當沖分數 ${pill(d.dt)}</a>` : ""}
      ${d.warrants ? `<a class="btn" href="#/warrants/${code}">相關權證 ${d.warrants.n_call + d.warrants.n_put} 檔</a>` : ""}</div>
  </div>
  <div class="grid g3">
    ${hzs.map((h, i) => `<section class="card hzcard ${i === S.hz ? "cur" : ""}">
      <div class="card-h" style="margin:0"><h2>${HZ_NAME[i]}</h2><span class="note">${HZ_SPAN[i]}</span>${i === 0 ? help("score") : ""}</div>
      <div class="hzbody"><div class="hzd">${dial(h ? h.score : null, { animate: i === S.hz })}
      <div class="hzl">${h ? h.label : "資料不足"}</div></div><div class="hzs">
      ${h && h.up != null ? `<div class="stat">上漲機率 <b>${(h.up * 100).toFixed(0)}%</b>${i === 0 ? help("upprob") : ""}${base[i] != null ? `<span class="note">（全市場 ${(base[i] * 100).toFixed(0)}%）</span>` : ""}</div>
      <div class="stat">常見報酬 <b class="${cls(h.lo)}">${fmtPct(h.lo, 1)}</b> ～ <b class="${cls(h.hi)}">${fmtPct(h.hi, 1)}</b>${i === 0 ? help("range") : ""}</div>` : '<div class="stat muted">歷史資料不足，暫無機率估計</div>'}
    </div></div></section>`).join("")}
  </div>
  ${cur ? `<section class="card section"><div class="card-h"><h2>為什麼是 ${Math.round(cur.score)} 分？</h2><span class="note">${HZ_NAME[S.hz]}觀點，影響最大的因素</span></div>
    <div class="why"><div class="plus"><h3>加分</h3><ul>${cur.pos.length ? cur.pos.map((t) => `<li><i>＋</i>${esc(t)}</li>`).join("") : '<li class="muted">沒有明顯加分項</li>'}</ul></div>
    <div class="minus"><h3>扣分</h3><ul>${cur.neg.length ? cur.neg.map((t) => `<li><i>－</i>${esc(t)}</li>`).join("") : '<li class="muted">沒有明顯扣分項</li>'}</ul></div></div>
    <p class="note" style="margin:14px 0 0">分數 = 個股在全市場的排名（75%）＋ 大盤氣氛（25%）。目前排在全市場第 ${Math.round(cur.pct * 100)} 百分位。${cur.n ? `機率依過去 ${fmtInt(cur.n)} 筆同分數區間的實際結果估算。` : ""}</p></section>` : ""}
  <section class="card section"><div class="card-h"><h2>股價走勢</h2><div class="seg" id="rng" style="margin-left:auto"><button data-n="60">3 個月</button><button data-n="120" class="on">6 個月</button><button data-n="250">1 年</button></div></div>
    <div class="chart" id="kchart"></div></section>
  <div class="grid g2 section">
    <section class="card"><div class="card-h"><h2>法人與融資</h2><span class="note">近 20 個交易日，單位：張</span></div>
      <div class="kv" style="margin-bottom:14px">
        <div><span>外資 5 日</span><b class="${cls(sum(1, 5))}">${fmtInt(sum(1, 5))}</b></div>
        <div><span>投信 5 日</span><b class="${cls(sum(2, 5))}">${fmtInt(sum(2, 5))}</b></div>
        <div><span>自營商 5 日</span><b class="${cls(sum(3, 5))}">${fmtInt(sum(3, 5))}</b></div>
        <div><span>融資餘額</span><b>${fmtInt(mbNow)}</b>${mbNow != null && mb20 ? `<span class="${cls(mbNow - mb20)}">20 日 ${mbNow >= mb20 ? "+" : ""}${fmtInt(mbNow - mb20)}</span>` : ""}</div>
      </div>
      <h3>外資每日買賣超</h3><div class="chart" id="cfi"></div>
      <h3 style="margin-top:10px">投信每日買賣超</h3><div class="chart" id="cit"></div>
    </section>
    <section class="card"><div class="card-h"><h2>基本面</h2><span class="note">${f.rev_ym ? "營收 " + f.rev_ym.slice(0, 3) + "/" + f.rev_ym.slice(3) : ""}${f.q ? "・財報 " + f.q : ""}</span></div>
      <div class="kv">
        <div><span>本益比</span><b>${f.pe ? f.pe.toFixed(1) + " 倍" : "—"}</b></div>
        <div><span>股價淨值比</span><b>${f.pb ? f.pb.toFixed(2) + " 倍" : "—"}</b></div>
        <div><span>殖利率</span><b>${f.yld != null ? f.yld.toFixed(2) + "%" : "—"}</b></div>
        <div><span>月營收年增</span><b class="${cls(f.rev_yoy)}">${f.rev_yoy != null ? fmtPct(f.rev_yoy / 100, 1) : "—"}</b></div>
        <div><span>累計營收年增</span><b class="${cls(f.rev_cum_yoy)}">${f.rev_cum_yoy != null ? fmtPct(f.rev_cum_yoy / 100, 1) : "—"}</b></div>
        <div><span>毛利率</span><b>${f.gm != null ? f.gm.toFixed(1) + "%" : "—"}</b></div>
        <div><span>營業利益率</span><b>${f.om != null ? f.om.toFixed(1) + "%" : "—"}</b></div>
        <div><span>EPS（${f.eps_q || "累計"}）</span><b>${f.eps != null ? f.eps.toFixed(2) : "—"}</b></div>
      </div>
      ${d.fut ? `<div class="card-h" style="margin-top:18px"><h2>個股期貨</h2>${help("basis")}</div>
        <div class="kv"><div><span>${esc(d.fut.c)} 近月</span><b>${fmtPx(d.fut.close)}</b></div><div><span>期現價差</span><b class="${cls(d.fut.basis)}">${fmtPct(d.fut.basis)}</b></div>
        <div><span>成交量</span><b>${fmtInt(d.fut.vol)} 口</b></div><div><span>未平倉</span><b>${fmtInt(d.fut.oi)} 口</b></div></div>` : ""}
      ${d.warrants ? `<div class="card-h" style="margin-top:18px"><h2>條件較好的權證</h2>${help("quality")}<a class="more" href="#/warrants/${code}">全部 ${d.warrants.n_call + d.warrants.n_put} 檔</a></div>
        ${miniWarrants(d.warrants)}` : ""}
    </section>
  </div>${disclaimer}`;
  const draw = (n) => candleChart($("#kchart"), d.hist, n);
  let curN = 120;
  draw(curN);
  $("#rng").addEventListener("click", (e) => {
    const b = e.target.closest("[data-n]"); if (!b) return;
    $$("#rng button").forEach((x) => x.classList.toggle("on", x === b)); curN = +b.dataset.n; draw(curN);
  });
  const c20 = chips.slice(-20);
  barChart($("#cfi"), c20.map((c) => c[0]), c20.map((c) => c[1]), { unit: " 張" });
  barChart($("#cit"), c20.map((c) => c[0]), c20.map((c) => c[2]), { unit: " 張" });
  onResize(() => { if (location.hash === "#/stock/" + code) { draw(curN); barChart($("#cfi"), c20.map((c) => c[0]), c20.map((c) => c[1]), { unit: " 張" }); barChart($("#cit"), c20.map((c) => c[0]), c20.map((c) => c[2]), { unit: " 張" }); } });
}
function miniWarrants(w) {
  const pick = [...(w.calls || []).slice(0, 2), ...(w.puts || []).slice(0, 2)];
  if (!pick.length) return '<p class="note">沒有可評估的權證。</p>';
  return `<div class="list" style="margin:0 -22px">${pick.map((p) => `<a class="row" href="#/warrants/${p.u}"><div class="nm"><b>${esc(p.n)}</b><span>${p.c}・${p.t === "C" ? "認購" : "認售"}・剩 ${p.days} 天</span></div><div class="px">${fmtPx(p.P)}</div><div class="ch"><span class="q ${p.q >= 75 ? "hi" : p.q >= 55 ? "md" : "lo"}">${Math.round(p.q)}</span></div><div class="sb small muted">${esc(p.why[0])}</div></a>`).join("")}</div>`;
}

let resizeFn = null, resizeT = null;
function onResize(fn) { resizeFn = fn; }
addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(() => resizeFn && resizeFn(), 200); });

// ====================================================================== 權證
async function vWarrants(tok, u) {
  if (u) return vWarrantsOf(tok, u);
  const wp = await api("warrant_picks").catch(() => null);
  if (tok !== routeToken) return;
  if (!wp) { view.innerHTML = `<h1>權證</h1><div class="card empty"><h2>權證資料準備中</h2><p>下次更新資料後就會出現。</p></div>`; return; }
  view.innerHTML = `<h1>權證</h1>
  <p class="lead">先選標的，再挑條件好的權證。推薦度同時看「權證本身划不划算」和「標的股票的看多／看空分數」。認購權證適合看漲、認售權證適合看跌。</p>
  <div class="filters"><input type="text" id="wu" placeholder="輸入標的代號或名稱，例如 2330" style="min-width:260px" aria-label="搜尋標的"></div>
  <div id="wulist"></div>
  <section class="card flush section"><div class="card-h" style="padding:18px 22px 4px"><h2>今日精選</h2>${help("rec")}<span class="note">每個標的只列最好的一檔；只列有成交、品質 60 分以上、方向和標的分數一致的權證</span></div>
    ${warrantTable(wp.picks, true)}</section>${disclaimer}`;
  const draw = () => {
    const q = $("#wu").value.trim().toLowerCase();
    const list = (wp.underlyings || []).filter((x) => !q || x.u.toLowerCase().includes(q) || (x.n || "").toLowerCase().includes(q)).slice(0, q ? 30 : 12);
    $("#wulist").innerHTML = `<div class="filters">${list.map((x) => `<a class="btn" href="#/warrants/${x.u}">${esc(x.n)} <span class="muted num">${x.u}</span> <span class="tag">${x.nc + x.np} 檔</span></a>`).join("")}${q && !list.length ? '<span class="note">找不到這個標的的權證</span>' : ""}</div>`;
  };
  $("#wu").addEventListener("input", draw);
  draw();
}
function warrantTable(rows, showU) {
  if (!rows || !rows.length) return '<div class="empty"><p>目前沒有符合條件的權證。</p></div>';
  return `<div class="tbl-wrap"><table class="tbl"><thead><tr>
    <th>權證</th>${showU ? "<th>標的分數</th>" : ""}<th>推薦度${help("rec")}</th><th>品質${help("quality")}</th><th>價格</th><th>價內外${help("money")}</th><th>剩餘天數${help("days")}</th>
    <th>實質槓桿${help("lev")}</th><th>隱含／歷史波動${help("iv")}</th><th>買賣價差${help("spread")}</th><th>每日時間損耗${help("theta")}</th><th style="text-align:left">白話說明</th></tr></thead><tbody>
    ${rows.map((p) => `<tr><td><b>${esc(p.n)}</b><br><span class="muted small">${p.c}・${p.t === "C" ? "認購" : "認售"}${showU ? "・" + esc(p.un) : ""}</span></td>
      ${showU ? `<td>${p.us ? pill(p.us[1], "標的中期分數") : "—"}</td>` : ""}
      <td><span class="q ${p.rec >= 70 ? "hi" : p.rec >= 50 ? "md" : "lo"}">${Math.round(p.rec)}</span></td>
      <td>${Math.round(p.q)}</td><td>${fmtPx(p.P)}</td><td class="${p.money >= 0 ? "" : "muted"}">${p.money >= 0 ? "價內 " : "價外 "}${(Math.abs(p.money) * 100).toFixed(1)}%</td>
      <td>${p.days}</td><td>${p.lev != null ? p.lev.toFixed(1) + " 倍" : "—"}</td>
      <td>${p.iv != null ? (p.iv * 100).toFixed(0) + "%" : "—"} / ${p.hv != null ? (p.hv * 100).toFixed(0) + "%" : "—"}</td>
      <td>${p.spread != null ? (p.spread * 100).toFixed(1) + "%" : "無報價"}</td><td>${p.theta != null ? (p.theta * 100).toFixed(2) + "%" : "—"}</td>
      <td class="txt">${esc(p.why.join("；"))}</td></tr>`).join("")}</tbody></table></div>`;
}
let wTab = "C";
async function vWarrantsOf(tok, u) {
  const w = await api("warrants/" + u);
  if (tok !== routeToken) return;
  const r = S.byCode[u];
  const name = r ? r.n : u === "IX0001" ? "臺股指數" : u;
  const sc = r ? r.s : u === "IX0001" ? HZ.map((h) => S.latest.market.horizons[h].score) : null;
  const sMid = sc ? sc[S.hz] : null;
  const advice = sMid == null ? "" : sMid >= 60 ? `標的${HZ_NAME[S.hz]}分數 ${Math.round(sMid)}（${labelOf(sMid)}），方向上較適合認購權證。` : sMid <= 40 ? `標的${HZ_NAME[S.hz]}分數 ${Math.round(sMid)}（${labelOf(sMid)}），方向上較適合認售權證。` : `標的${HZ_NAME[S.hz]}分數 ${Math.round(sMid)}，方向不明確，建議先觀望或只看條件特別好的權證。`;
  if (sMid != null && sMid <= 40) wTab = "P"; else if (sMid != null && sMid >= 60) wTab = "C";
  view.innerHTML = `<p><a class="note" href="#/warrants">← 回到權證首頁</a></p>
    <div class="sh"><div><h1 style="margin-bottom:2px">${esc(name)} 的權證</h1><div class="muted small">認購 ${w.n_call} 檔、認售 ${w.n_put} 檔，依品質由高到低列出前 40 檔</div></div>
      ${sc ? `<div style="display:flex;gap:8px;align-items:center">${sc.map((s, i) => `<span class="small muted">${HZ_NAME[i]}</span>${pill(s)}`).join("")}</div>` : ""}
      ${r ? `<a class="btn" href="#/stock/${u}" style="margin-left:auto">看標的個股分析</a>` : ""}</div>
    ${advice ? `<div class="warnbox">${esc(advice)}</div>` : ""}
    <div class="section"><div class="seg" id="wtab"><button data-t="C">認購（看漲）</button><button data-t="P">認售（看跌）</button></div></div>
    <section class="card flush section" id="wtbl"></section>${disclaimer}`;
  const draw = () => {
    $$("#wtab button").forEach((b) => b.classList.toggle("on", b.dataset.t === wTab));
    $("#wtbl").innerHTML = warrantTable(wTab === "C" ? w.calls : w.puts, false);
  };
  $("#wtab").addEventListener("click", (e) => { const b = e.target.closest("[data-t]"); if (b) { wTab = b.dataset.t; draw(); } });
  draw();
}

// ====================================================================== 期貨
async function vFutures(tok) {
  const F = await api("futures");
  if (tok !== routeToken) return;
  const M = S.latest.market, hz = HZ[S.hz], mh = M.horizons[hz], ser = M.series || {};
  const tx = F.index.find((x) => x.c === "TX");
  const basisPts = tx && M.taiex ? tx.close - M.taiex : null;
  view.innerHTML = `<h1>期貨</h1><p class="lead">台指期跟著大盤走，所以方向判斷沿用大盤分數；另外參考正逆價差、外資留倉與選擇權籌碼。個股期貨則看標的股票的分數。</p>
  <section class="card hero glow"><span class="glow-ring"></span>
    <div class="dial-wrap">${dial(mh.score, { size: "lg" })}<div class="verdict">台指期${HZ_NAME[S.hz]}${mh.label}</div></div>
    <div class="hero-side">
      <div class="idx"><span class="muted">臺股期貨 ${tx ? tx.month.slice(0, 4) + "/" + tx.month.slice(4) : ""}</span><span class="big" ${tx ? `data-count="${tx.close}"` : ""}>${tx ? fmtPx(tx.close) : "—"}</span><span class="chg">${chgHtml(tx && tx.chg)}</span></div>
      <div class="kv" style="margin-top:14px">
        <div><span>正逆價差${help("basis")}</span><b class="${cls(basisPts)}">${basisPts != null ? (basisPts >= 0 ? "正價差 " : "逆價差 ") + Math.abs(basisPts).toFixed(0) + " 點" : "—"}</b></div>
        <div><span>外資淨留倉${help("foi")}</span><b class="${cls(M.foi)}">${M.foi != null ? (M.foi >= 0 ? "多 " : "空 ") + fmtInt(Math.abs(M.foi)) + " 口" : "—"}</b></div>
        <div><span>外資留倉 5 日變化</span><b class="${cls(M.foi5)}">${M.foi5 != null ? (M.foi5 >= 0 ? "+" : "") + fmtInt(M.foi5) + " 口" : "—"}</b></div>
        <div><span>買賣權未平倉比${help("pc")}</span><b>${M.pc != null ? M.pc.toFixed(1) + "%" : "—"}</b></div>
      </div>
      <ul class="facts">${mh.pos.length ? `<li>加分：${esc(mh.pos.join("、"))}</li>` : ""}${mh.neg.length ? `<li>扣分：${esc(mh.neg.join("、"))}</li>` : ""}</ul>
    </div>
  </section>
  <div class="grid g3 section">
    <section class="card"><div class="card-h"><h2>外資台指期淨留倉</h2><span class="note">口</span></div><div class="chart" id="cfoi"></div></section>
    <section class="card"><div class="card-h"><h2>加權指數</h2></div><div class="chart" id="ctx"></div></section>
    <section class="card"><div class="card-h"><h2>買賣權未平倉比</h2><span class="note">%</span></div><div class="chart" id="cpc"></div></section>
  </div>
  <section class="card flush section"><div class="card-h" style="padding:18px 22px 4px"><h2>指數期貨</h2></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>商品</th><th>月份</th><th>收盤</th><th>漲跌</th><th>成交量</th><th>未平倉${help("oi")}</th></tr></thead><tbody>
    ${F.index.map((x) => `<tr><td><b>${esc(x.n)}</b></td><td>${x.month.slice(0, 4)}/${x.month.slice(4)}</td><td>${fmtPx(x.close)}</td><td>${chgHtml(x.chg)}</td><td>${fmtInt(x.vol)}</td><td>${fmtInt(x.oi)}</td></tr>`).join("")}</tbody></table></div></section>
  <section class="card flush section"><div class="card-h" style="padding:18px 22px 4px"><h2>個股期貨</h2><span class="note">依成交量排序，分數為標的股票的分數</span></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>標的</th><th>期貨價</th><th>現貨價</th><th>期現價差${help("basis")}</th><th>成交量</th><th>未平倉變化${help("oi")}</th><th>短期</th><th>中期</th><th>長期</th></tr></thead><tbody>
    ${F.stock.slice(0, 80).map((x) => `<tr style="cursor:pointer" onclick="location.hash='#/stock/${x.stock}'"><td><b>${esc(x.n)}</b> <span class="muted small">${x.stock}・${x.c}</span></td><td>${fmtPx(x.close)}</td><td>${fmtPx(x.spot)}</td>
      <td class="${cls(x.basis)}">${fmtPct(x.basis)}</td><td>${fmtInt(x.vol)}</td><td class="${cls(x.oi_chg)}">${x.oi_chg != null ? (x.oi_chg >= 0 ? "+" : "") + fmtInt(x.oi_chg) : "—"}</td>
      ${(x.s || [null, null, null]).map((s) => `<td>${pill(s)}</td>`).join("")}</tr>`).join("") || '<tr><td colspan="9">暫無資料</td></tr>'}</tbody></table></div></section>${disclaimer}`;
  const draw = () => {
    lineChart($("#cfoi"), ser.days || [], ser.foi || [], { color: "var(--blue)", fmt: (v) => fmtInt(v), zero: true });
    lineChart($("#ctx"), ser.days || [], ser.taiex || [], { color: "var(--ink-2)", fmt: (v) => fmtPx(v) });
    lineChart($("#cpc"), ser.days || [], ser.pc || [], { color: "var(--brass)", fmt: (v) => v.toFixed(0), ref: 100, refLabel: "100" });
  };
  draw(); onResize(() => location.hash === "#/futures" && draw());
}

// ====================================================================== 當沖
let dtSide = null;
async function vDayTrade(tok) {
  const d = await api("daytrade").catch(() => null);
  if (tok !== routeToken) return;
  if (!d) { view.innerHTML = `<h1>當沖</h1><div class="card empty"><h2>當沖分析準備中</h2><p>下次資料更新後就會出現。</p></div>`; return; }
  const M = d.model, L = M.long, Sx = M.short;
  const sideOk = (x) => x && x.avg > 0 && x.win > 0.5;
  if (!dtSide) dtSide = d.long_ok !== d.short_ok ? (d.long_ok > d.short_ok ? "long" : "short") : (sideOk(M.short) && !sideOk(M.long) ? "short" : "long");
  const pctS = (x) => (x * 100).toFixed(1) + "%";
  const sv = (x) => x == null ? "—" : `<span class="${cls(x)}">${x > 0 ? "+" : ""}${(x * 100).toFixed(2)}%</span>`;
  const statLine = (x, name) => x ? `${name}：扣成本後勝率 <b class="num">${pctS(x.win)}</b>，平均每筆 ${sv(x.avg)}` : `${name}：資料不足`;
  view.innerHTML = `<h1 class="grad">當沖</h1>
  <p class="lead">依 ${dayFull(d.day)} 收盤資料，評估<b>下一個交易日</b>開盤進場、收盤前出場的勝算。勝率與報酬都已扣除來回成本約 ${(d.cost * 100).toFixed(2)}%（手續費 6 折＋當沖證交稅 0.15%）。只看日均成交 1 億元以上、股價 10 元以上的股票，共 ${d.universe} 檔。</p>
  <section class="card"><div class="card-h"><h2>回測成績</h2><span class="note">最近 ${M.eval_days} 個交易日，每天只用當時已知的資料打分數</span></div>
    <div class="grid g2">
      <div class="tile" style="padding:14px 16px"><div class="card-h" style="margin:0 0 6px"><h3>做多（先買後賣）</h3>${sideOk(L) ? '<span class="pill p-up1">有優勢</span>' : '<span class="pill p-mid">目前無優勢</span>'}</div>
        <p style="margin:0">${statLine(L, "分數前 10%")}</p></div>
      <div class="tile" style="padding:14px 16px"><div class="card-h" style="margin:0 0 6px"><h3>做空（先賣後買）</h3>${sideOk(Sx) ? '<span class="pill p-dn1">有優勢</span>' : '<span class="pill p-mid">目前無優勢</span>'}</div>
        <p style="margin:0">${statLine(Sx, "分數後 10%")}</p></div>
    </div>
    <p class="note" style="margin:12px 0 0">對照：所有股票隨機當沖做多，扣成本後勝率約 ${M.base_win != null ? pctS(M.base_win) : "—"}。分數最高與最低兩組的隔天盤中表現平均相差 ${M.spread_avg != null ? (M.spread_avg * 100).toFixed(2) + "%" : "—"}，在 ${M.spread_win != null ? pctS(M.spread_win) : "—"} 的日子成立。</p>
  </section>
  <div class="section"><div class="seg" id="dtab"><button data-s="long">做多（先買後賣）</button><button data-s="short">做空（先賣後買）</button></div></div>
  <div id="dtwarn"></div>
  <section class="card flush section" id="dtlist"></section>
  <div class="grid g3 section">
    <section class="card"><h3>分數高低與隔天勝率</h3><p class="note" style="margin:2px 0 8px">由左（分數最低）到右（最高）；虛線是全部股票的平均</p><div class="chart" id="dtcal"></div></section>
    <section class="card"><h3>近期預測力</h3><p class="note" style="margin:2px 0 8px">分數排名與隔天盤中報酬的相關性（20 日平均），大於 0 代表有效</p><div class="chart" id="dtic"></div></section>
    <section class="card"><h3>目前最看重的指標</h3><p class="note" style="margin:2px 0 8px">紅色＝數值越高越適合做多，綠色＝數值越高越適合做空</p><div class="bars" id="dtfw"></div></section>
  </div>
  <p class="disclaimer">當沖風險極高：交易成本會吃掉大部分利潤，盤中波動也可能遠超停損參考。分數與勝率是過去的統計，不保證明天的結果，也不構成投資建議。請先確認自己已開通當沖資格，並嚴格控制部位。</p>`;
  const draw = () => {
    $$("#dtab button").forEach((b) => b.classList.toggle("on", b.dataset.s === dtSide));
    const rows = d[dtSide] || [];
    const okN = rows.filter((r) => r.ok).length;
    const sideStat = dtSide === "long" ? L : Sx;
    $("#dtwarn").innerHTML = okN ? `<div class="warnbox section">今天有 <b>${okN}</b> 檔符合推薦條件（同分數區間過去扣成本後勝率超過 50% 且平均報酬為正），標示為「推薦」。其餘僅列入觀察。</div>` :
      `<div class="warnbox section">這個方向今天<b>沒有</b>符合推薦條件的標的：同分數區間的股票過去扣掉成本後平均仍是虧損${sideOk(sideStat) ? "" : "，整體回測也還沒有優勢"}。以下名單只供觀察，不建議照做。</div>`;
    $("#dtlist").innerHTML = rows.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>股票</th><th>收盤</th><th>當沖分數${help("dtscore")}</th><th>勝率${help("dtwin")}</th><th>平均報酬</th><th>停利參考${help("dttp")}</th><th>停損參考${help("dtsl")}</th><th>平均振幅</th><th>日均成交</th><th style="text-align:left">理由</th></tr></thead><tbody>
      ${rows.map((r) => `<tr style="cursor:pointer" onclick="location.hash='#/stock/${r.c}'"><td><b>${esc(r.n)}</b> ${r.ok ? `<span class="pill ${dtSide === "long" ? "p-up2" : "p-dn2"}" style="height:20px;min-width:0;font-size:12px">推薦</span>` : ""}<br><span class="muted small">${r.c}・${esc(r.m)}</span></td>
        <td>${fmtPx(r.px)}<br>${chgHtml(r.chg)}</td>
        <td><span class="pill ${pillClass(dtSide === "long" ? r.score : 100 - r.score)}" title="當沖分數">${Math.round(r.score)}</span></td><td>${r.win != null ? pctS(r.win) : "—"}</td><td>${sv(r.avg)}</td>
        <td>${r.tp != null ? (dtSide === "long" ? "+" : "−") + Math.abs(r.tp * 100).toFixed(1) + "%" : "—"}</td>
        <td>${r.sl != null ? (dtSide === "long" ? "−" : "+") + Math.abs(r.sl * 100).toFixed(1) + "%" : "—"}</td>
        <td>${r.atr != null ? (r.atr * 100).toFixed(1) + "%" : "—"}</td><td>${r.val != null ? r.val.toFixed(1) + " 億" : "—"}</td>
        <td class="txt">${esc((r.why || []).join("；"))}</td></tr>`).join("")}</tbody></table></div>` : '<div class="empty"><p>今天沒有可評估的標的。</p></div>';
    FX.enhance($("#dtlist"));
    const cal = (M.calib || []).map((c) => c ? { n: c.n, up: dtSide === "long" ? c.win_long : c.win_short } : null);
    const calOrdered = dtSide === "long" ? cal : [...cal].reverse();
    const base = M.base_win != null ? (dtSide === "long" ? M.base_win : null) : null;
    calibChart($("#dtcal"), calOrdered, base);
    lineChart($("#dtic"), (M.ic_roll || []).map((p) => p[0]), (M.ic_roll || []).map((p) => p[1]), { color: "var(--brass)", fmt: (v) => v.toFixed(2), zero: true, height: 150 });
    const fs = (M.factors || []).slice(0, 10), mx = Math.max(...fs.map((f) => Math.abs(f.w)), 1e-6);
    $("#dtfw").innerHTML = fs.map((f) => `<div class="b" title="最近 IC ${f.ic}"><span class="nm">${esc(f.name)}</span><div class="sbar"><div class="track"><div class="fill ${f.w >= 0 ? "u" : "d"}" style="left:${f.w >= 0 ? 50 : 50 - Math.abs(f.w) / mx * 50}%;width:${Math.abs(f.w) / mx * 50}%"></div></div></div><span class="v small"></span></div>`).join("");
  };
  $("#dtab").addEventListener("click", (e) => { const b = e.target.closest("[data-s]"); if (b) { dtSide = b.dataset.s; draw(); } });
  draw();
  onResize(() => location.hash === "#/daytrade" && draw());
}

// ====================================================================== 自選
async function vWatch(tok) {
  await loadWatch();
  if (tok !== routeToken) return;
  const rows = S.watch.map((c) => S.byCode[c]).filter(Boolean);
  view.innerHTML = `<h1>我的自選</h1><p class="lead">在任何股票旁點星號就能加入。自選清單存在你的電腦上，電腦與手機開啟時會看到同一份。</p>
    ${rows.length ? `<section class="card flush"><div class="list">${rowsHead3("", 0)}${rows.map((r) => stockRow(r, { mode: "three" })).join("")}</div></section>` :
      `<div class="card empty"><h2>還沒有自選股</h2><p>用上方搜尋找到股票後，點「自選」星號加入，就能在這裡一次看到它們的分數。</p><a class="btn primary" href="#/stocks">去選股</a></div>`}${disclaimer}`;
}

// ====================================================================== 模型成績單
async function vModel(tok) {
  const m = await api("model");
  if (tok !== routeToken) return;
  view.innerHTML = `<h1>模型成績單</h1>
  <p class="lead">模型每天用「當時已知的資料」打分數，再拿之後實際漲跌來對答案（不偷看未來）。各指標的權重會依最近的對答案結果自動調整，所以市場風格改變時，判斷也會跟著修正。資料期間：${dayFull(m.first_day)}～${dayFull(m.last_day)}，共 ${m.days} 個交易日。</p>
  ${HZ.map((h, i) => {
    const x = m.horizons[h];
    return `<section class="card section"><div class="card-h"><h2>${HZ_NAME[i]}（${HZ_SPAN[i]}）</h2></div>
      ${modelSentence(x, i)}
      <div class="grid g3" style="margin-top:16px">
        <div><h3>分數高低與實際上漲比例</h3><p class="note" style="margin:2px 0 8px">由左（分數最低 10%）到右（最高 10%），柱子越往右越高代表分數越有用</p><div class="chart" id="cal${i}"></div></div>
        <div><h3>近期預測力</h3><p class="note" style="margin:2px 0 8px">分數排名與實際報酬排名的相關性（20 日平均），大於 0 代表有效</p><div class="chart" id="ic${i}"></div></div>
        <div><h3>目前最看重的指標</h3><p class="note" style="margin:2px 0 8px">紅色＝數值越高越加分，綠色＝數值越高越扣分</p><div class="bars" id="fw${i}"></div></div>
      </div></section>`;
  }).join("")}
  <p class="disclaimer">回測結果代表過去，不保證未來。資料天數越多，成績單越可信；剛開始使用的前幾週，權重主要依預設值。</p>`;
  const draw = () => HZ.forEach((h, i) => {
    const x = m.horizons[h];
    calibChart($("#cal" + i), x.calib, x.base_hit);
    lineChart($("#ic" + i), (x.ic_roll || []).map((p) => p[0]), (x.ic_roll || []).map((p) => p[1]), { color: "var(--brass)", fmt: (v) => v.toFixed(2), zero: true, height: 150 });
    const fs = (x.factors || []).slice(0, 10), mx = Math.max(...fs.map((f) => Math.abs(f.w)), 1e-6);
    $("#fw" + i).innerHTML = fs.map((f) => `<div class="b" title="${esc(f.group)}：最近 IC ${f.ic ?? "—"}，檢驗 ${f.n} 天"><span class="nm">${esc(f.name)}</span><div class="sbar"><div class="track"><div class="fill ${f.w >= 0 ? "u" : "d"}" style="left:${f.w >= 0 ? 50 : 50 - Math.abs(f.w) / mx * 50}%;width:${Math.abs(f.w) / mx * 50}%"></div></div></div><span class="v small">${f.group}</span></div>`).join("");
  });
  draw(); onResize(() => location.hash === "#/model" && draw());
}
function calibChart(box, cal, base) {
  const W = Math.max(240, box.clientWidth), H = 150, PB = 20, PT = 8, PR = 40;
  const vals = (cal || []).map((c) => c ? c.up : null);
  if (!vals.some((v) => v != null)) { box.innerHTML = '<p class="note">資料累積中</p>'; return; }
  const lo = Math.max(0, Math.min(base ?? 0.5, ...vals.filter((v) => v != null)) - 0.05), hi = Math.min(1, Math.max(base ?? 0.5, ...vals.filter((v) => v != null)) + 0.05);
  const pw = W - PR, step = pw / 10, y = (v) => PT + (hi - v) / (hi - lo) * (H - PT - PB);
  let b = "";
  vals.forEach((v, i) => { if (v == null) return; b += `<rect x="${i * step + 2}" y="${y(v)}" width="${step - 4}" height="${H - PB - y(v)}" rx="3" fill="${v >= (base ?? 0.5) ? "var(--up)" : "var(--down)"}" opacity=".85"><title>分數 ${i * 10}～${i * 10 + 10} 百分位：${(v * 100).toFixed(1)}% 上漲（${cal[i].n} 筆）</title></rect>`; });
  const bl = base != null ? `<line x1="0" x2="${pw}" y1="${y(base)}" y2="${y(base)}" stroke="var(--ink)" stroke-dasharray="4 4"/><text x="4" y="${y(base) - 5}" font-size="11" fill="var(--ink-2)">全市場平均</text>` : "";
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><g class="axis grid">${niceTicks(lo, hi, 3).map((t) => `<line x1="0" x2="${pw}" y1="${y(t)}" y2="${y(t)}"/><text x="${W - 2}" y="${y(t) + 4}" text-anchor="end">${(t * 100).toFixed(0)}%</text>`).join("")}
    <text x="0" y="${H - 4}">分數低</text><text x="${pw}" y="${H - 4}" text-anchor="end">分數高</text></g>${b}${bl}</svg>`;
}

// ====================================================================== 說明
async function vHelp(tok) {
  let st = S.status || {};
  try { st = await api("status", { fresh: true }); } catch { }
  if (tok !== routeToken) return;
  const lan = (st.lan || []).map((ip) => `http://${ip}:${st.port || 8787}`);
  view.innerHTML = `<h1>使用說明</h1>
  <div class="grid g2">
    <section class="card"><h2>分數怎麼看</h2>
      <p>每檔股票有短期（約 1 週）、中期（約 1 個月）、長期（約 3 個月）三個分數，0～100 分，50 分是中立。</p>
      <div class="bars" style="margin:10px 0">${[[85, "75 分以上：強烈看多"], [65, "60～75：偏多"], [50, "40～60：中立"], [33, "25～40：偏空"], [15, "25 分以下：強烈看空"]].map(([s, t]) => `<div class="b"><span>${pill(s)}</span><span>${t}</span><span></span></div>`).join("")}</div>
      <p>分數由約 30 個指標組成：漲勢與均線（技術面）、外資投信買賣與融資（籌碼面）、營收與本益比（基本面），再加上大盤氣氛。</p>
      <p>關鍵在於<b>權重不是固定的</b>：每天收盤後，模型會檢查每個指標過去預測得準不準，準的加重、失靈的減輕，所以判斷會隨行情自動修正。「模型成績單」可以看到它最近的表現。</p>
    </section>
    ${st.static ? `<section class="card"><h2>雲端版（不用開電腦）</h2>
      <p>你現在看的是雲端版，資料每個交易日由雲端自動更新，電腦不用開。</p>
      <p>用手機瀏覽器打開這個網址，在選單點「加到主畫面」，就能像 App 一樣使用。這個網址不會被搜尋引擎收錄，請不要公開分享。</p>
      <h2 style="margin-top:18px">資料何時更新</h2>
      <p>每個交易日下午 3 點 40 分（收盤行情、法人）與晚上 9 點 50 分（融資融券）各更新一次，更新完約 10 分鐘內網頁就會換成新資料。</p>
      <p class="note">雲端版的自選股存在這支手機（或這個瀏覽器）裡，和電腦版的自選不互通。</p>
    </section>` : `<section class="card"><h2>在手機上使用</h2>
      <p>電腦開著台股羅盤時，手機連上<b>同一個 Wi-Fi</b>，用瀏覽器開啟：</p>
      ${lan.length ? lan.map((u) => `<p class="num" style="font-size:22px;margin:4px 0"><b>${esc(u)}</b></p>`).join("") : '<p class="note">找不到這台電腦的區域網路位址。</p>'}
      <p>打開後在瀏覽器選單點「加到主畫面」，之後就能像 App 一樣從桌面開啟。第一次開啟時若 Windows 詢問是否允許網路存取，請按「允許」。</p>
      <h2 style="margin-top:18px">資料何時更新</h2>
      <p>台股羅盤開著的時候，平日下午 2 點到晚上 11 點每 20 分鐘自動檢查新資料。收盤行情約 2 點半後公布，法人約 4 點，融資融券約晚上 9 點。也可以按右上角的更新按鈕立即更新。</p>
      <p>如果有執行「設定每日自動更新」，就算沒開網頁，每個交易日晚上 9 點 40 分也會自動更新。</p>
    </section>`}
  </div>
  <section class="card section"><h2>權證怎麼挑</h2>
    <p>權證推薦度同時考量兩件事：權證本身划不划算（價格是否合理、買賣價差、剩餘天數、價內外、每天的時間價值損耗、槓桿），以及標的股票的看多／看空分數。看漲選認購、看跌選認售。表格的每一欄旁邊都有 <span class="help" style="cursor:default">?</span> 可以看白話解釋。</p>
  </section>
  ${disclaimer}`;
}

// ====================================================================== 第一次使用
const ROSE = `<svg class="rose" viewBox="0 0 200 200" aria-hidden="true">
  <defs><radialGradient id="rg" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="var(--brass)" stop-opacity=".25"/><stop offset="1" stop-color="var(--brass)" stop-opacity="0"/></radialGradient></defs>
  <circle cx="100" cy="100" r="96" fill="url(#rg)"/>
  <g class="spinner" fill="none" stroke="var(--brass)">
    <circle cx="100" cy="100" r="84" stroke-opacity=".5"/><circle cx="100" cy="100" r="76" stroke-opacity=".25" stroke-dasharray="2 5"/>
    ${Array.from({ length: 72 }, (_, i) => { const a = i * 5 * Math.PI / 180, r1 = i % 18 === 0 ? 70 : i % 6 === 0 ? 74 : 78; return `<line x1="${100 + r1 * Math.sin(a)}" y1="${100 - r1 * Math.cos(a)}" x2="${100 + 84 * Math.sin(a)}" y2="${100 - 84 * Math.cos(a)}" stroke-opacity="${i % 6 === 0 ? .9 : .4}"/>`; }).join("")}
  </g>
  <g fill="var(--brass)" opacity=".35">${[0, 90, 180, 270].map((d) => `<path d="M100 40 L108 100 L100 160 L92 100Z" transform="rotate(${d + 45} 100 100)"/>`).join("")}</g>
  <g fill="var(--ink)" font-family="var(--font)" font-weight="700" font-size="14" text-anchor="middle"><text x="100" y="30">北</text><text x="174" y="105">東</text><text x="100" y="182">南</text><text x="26" y="105">西</text></g>
  <g class="needle2"><path d="M100 36 L109 100 L100 108 L91 100Z" fill="var(--brass)"/><path d="M100 164 L109 100 L100 92 L91 100Z" fill="var(--muted)"/></g>
  <circle cx="100" cy="100" r="7" fill="var(--surface-solid)" stroke="var(--brass)" stroke-width="2"/></svg>`;
function renderOnboarding() {
  const st = S.status || {};
  const pct = st.total ? Math.min(100, Math.round(st.done / st.total * 100)) : 0;
  const order = ["collect", "snapshot", "engine", "backfill"];
  const names = { collect: "下載最近 70 個交易日的行情、法人、融資", snapshot: "下載基本面、權證條款與行情", engine: "分析：檢驗指標、調整權重、算分數", backfill: "背景補齊更早的歷史資料" };
  const cur = order.indexOf(st.phase);
  const running = st.running || st.state === "running";
  view.innerHTML = `<div class="card empty glow" style="max-width:660px;margin:36px auto"><span class="glow-ring"></span>
    ${ROSE}
    <h2>正在建立你的台股資料庫</h2>
    <p style="max-width:52ch;margin:0 auto">第一次使用要從證交所、櫃買中心、期交所下載近一年的公開資料。官方網站會擋太快的連線，所以刻意放慢：約 15 分鐘後就能先看到分析結果，完整一年資料約 40 分鐘補齊，之後每天只要幾分鐘。</p>
    ${running ? `<div class="progress" style="margin:22px 0 8px"><div style="width:${Math.max(3, pct)}%"></div></div>
      <p class="note num">${pct}%${st.msg ? "　" + esc(st.msg) : ""}</p>
      <ul class="steps">${order.map((k, i) => `<li class="${i < cur ? "done" : i === cur ? "now" : ""}"><i>${i < cur ? "✓" : i + 1}</i>${names[k]}</li>`).join("")}</ul>` :
      `<button class="btn primary" id="startbtn" style="margin-top:16px">${svgI("refresh")}開始下載資料</button>`}
    ${(st.errors || []).length ? `<p class="note" style="color:var(--up)">最近的問題：${esc(st.errors[st.errors.length - 1])}</p>` : ""}
    <p class="note" style="margin-top:18px">等待時可以先看<a href="#/help" style="color:var(--brass)">使用說明</a>。瀏覽器分頁可以關掉，但請保持黑色的台股羅盤視窗開著。</p></div>`;
  const b = $("#startbtn");
  if (b) b.addEventListener("click", startUpdate);
}

// ====================================================================== 更新狀態
async function startUpdate() {
  try { await fetch("api/update", { method: "POST" }); } catch { }
  pollStatus(true);
}
let pollT = null, lastGenerated = null;
async function pollStatus(force) {
  clearTimeout(pollT);
  try {
    const st = await api("status", { fresh: true });
    S.status = st;
    const running = st.running;
    const L = S.latest;
    const pct = st.total ? Math.min(100, Math.round(st.done / st.total * 100)) : 0;
    $("#datainfo").innerHTML = `${L ? `<span class="dtxt">資料日 <b class="num">${dayFull(L.day)}</b></span>` : ""}
      <button class="btn iconbtn" id="updbtn" title="${running ? "更新中 " + pct + "%：" + esc(st.msg || "") : "立即更新資料"}" aria-label="更新資料">${running ? `<span class="spin" style="display:inline-flex">${svgI("refresh")}</span>` : svgI("refresh")}</button>
      <button class="btn iconbtn" id="themebtn" title="切換深淺色" aria-label="切換深淺色">${svgI("sun")}</button>`;
    if (st.static) { $("#updbtn").remove(); } else $("#updbtn").onclick = () => { if (!running) startUpdate(); };
    $("#themebtn").onclick = toggleTheme;
    // 有新的分析結果就重新載入
    if (st.has_data && st.latest_mtime && st.latest_mtime !== S.latestMtime) {
      const first = S.latestMtime == null && L;
      S.latestMtime = st.latest_mtime;
      if (!first) {
        clearCache(); await loadLatest(true); renderTicker();
        if (!location.hash.startsWith("#/stock/") || !L) route();
      }
    }
    if (!S.latest && !location.hash.startsWith("#/help")) {
      const bar = $(".progress > div");
      if (bar && (st.running || st.state === "running")) {
        const pct = st.total ? Math.min(100, Math.round(st.done / st.total * 100)) : 0;
        bar.style.width = Math.max(3, pct) + "%";
        const n = bar.parentElement.nextElementSibling; if (n) n.textContent = pct + "%" + (st.msg ? "　" + st.msg : "");
        const order = ["collect", "snapshot", "engine", "backfill"], cur = order.indexOf(st.phase);
        $$(".steps li").forEach((li, i) => { li.className = i < cur ? "done" : i === cur ? "now" : ""; $("i", li).textContent = i < cur ? "✓" : i + 1; });
      } else renderOnboarding();
    }
    pollT = setTimeout(() => pollStatus("silent"), st.static ? 600000 : running ? 4000 : 60000);
  } catch (e) {
    $("#datainfo").innerHTML = '<span class="small" style="color:var(--up)">連不到台股羅盤程式，請確認黑色視窗還開著</span>';
    pollT = setTimeout(() => pollStatus("silent"), 8000);
  }
}
function toggleTheme() {
  const cur = document.documentElement.dataset.theme || "dark";
  const nx = cur === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = nx; store.set("theme", nx);
}
{ const t = store.get("theme", null); if (t) document.documentElement.dataset.theme = t; }

// ====================================================================== 搜尋
const qi = $("#q"), sug = $("#suggest");
let sugSel = 0, sugList = [];
qi.addEventListener("input", () => {
  const q = qi.value.trim().toLowerCase();
  if (!q || !S.latest) { sug.classList.add("hide"); return; }
  const st = S.latest.stocks;
  sugList = st.filter((r) => r.c.toLowerCase().startsWith(q)).concat(st.filter((r) => !r.c.toLowerCase().startsWith(q) && r.n.toLowerCase().includes(q)))
    .slice(0, 8);
  sugSel = 0;
  sug.innerHTML = sugList.map((r, i) => `<a href="#/stock/${r.c}" class="${i === 0 ? "sel" : ""}" role="option"><span><b>${esc(r.n)}</b> <span class="muted num">${r.c}</span></span><span>${pill(r.s[S.hz])}</span></a>`).join("") || '<div style="padding:12px 14px" class="note">找不到符合的股票</div>';
  sug.classList.remove("hide");
});
qi.addEventListener("keydown", (e) => {
  if (sug.classList.contains("hide")) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault(); sugSel = (sugSel + (e.key === "ArrowDown" ? 1 : -1) + sugList.length) % sugList.length;
    $$("a", sug).forEach((a, i) => a.classList.toggle("sel", i === sugSel));
  } else if (e.key === "Enter" && sugList[sugSel]) {
    location.hash = "#/stock/" + sugList[sugSel].c; qi.value = ""; sug.classList.add("hide"); qi.blur();
  } else if (e.key === "Escape") sug.classList.add("hide");
});
sug.addEventListener("click", () => { qi.value = ""; sug.classList.add("hide"); });
document.addEventListener("click", (e) => { if (!e.target.closest("#search")) sug.classList.add("hide"); });

// ====================================================================== 啟動
function renderTicker() {
  const L = S.latest, el = $("#ticker");
  if (!el || !L) return;
  const items = [];
  const M = L.market;
  if (M && M.taiex) items.push({ n: "加權指數", px: fmtPx(M.taiex), chg: (M.taiex_chg >= 0 ? "▲" : "▼") + fmtPct(Math.abs(M.taiex_chg), 2, false), cls: cls(M.taiex_chg), href: "#/futures" });
  if (M && M.tx_close) items.push({ n: "台指期", px: fmtPx(M.tx_close), chg: M.basis != null ? (M.basis >= 0 ? "正價差" : "逆價差") : "", cls: cls(M.basis), href: "#/futures" });
  const big = L.stocks.filter((r) => r.val != null && r.px != null).sort((a, b) => b.val - a.val).slice(0, 24);
  for (const r of big) items.push({ n: esc(r.n), px: fmtPx(r.px), chg: (r.chg > 0 ? "▲" : r.chg < 0 ? "▼" : "") + fmtPct(Math.abs(r.chg), 2, false), cls: cls(r.chg), href: "#/stock/" + r.c });
  FX.ticker(el, items);
}

(async function init() {
  FX.init();
  renderSeg();
  try { S.status = await api("status", { fresh: true }); } catch { }
  await Promise.all([loadLatest(true), loadWatch()]);
  renderTicker();
  await route();
  pollStatus("silent");
  if ("serviceWorker" in navigator && (location.hostname === "localhost" || location.protocol === "https:")) {
    navigator.serviceWorker.register("sw.js").catch(() => { });
  }
})();
