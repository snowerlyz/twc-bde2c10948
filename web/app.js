/* 台股羅盤 前端（不需任何外部套件） */
"use strict";

// ====================================================================== 小工具
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const HZ = ["short", "mid", "long"];
const HZ_NAME = ["短期", "中期", "長期"];
const HZ_SPAN = ["約 1 週・5 個交易日", "約 1 個月・20 個交易日", "約 3 個月・60 個交易日"];
const HZ_SHORT = ["1 週", "1 個月", "3 個月"];
const hzTag = (i) => `${HZ_NAME[i]}<small class="hzt">${HZ_SHORT[i]}</small>`;
const hzFull = (i) => `${HZ_NAME[i]}（${HZ_SHORT[i]}）`;
function relInfo(r) {
  if (r == null) return { t: "—", c: "p-mid" };
  if (r >= 0.7) return { t: "高", c: "p-good" };
  if (r >= 0.4) return { t: "中", c: "p-mid" };
  return { t: "低", c: "p-bad" };
}
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
  score: "分數 0～100，50 分代表看不出方向；越高越可能漲，越低越可能跌。75 分以上＝強烈看多，25 分以下＝強烈看空。分數綜合約 35 項指標：股價走勢、法人買賣、公司營收獲利、新聞消息，再加上大盤與美股等國際行情。短期看 1 週、中期看 1 個月、長期看 3 個月。",
  rel: "可信度＝最近分數準不準。每天會拿過去的分數和後來真正的漲跌對答案：最近常猜對，可信度就高；最近常猜錯，可信度就低，分數也會自動往 50 靠攏，不給太肯定的判斷。等它重新變準，可信度會自己回升。",
  tune: "模型每天收盤後會自我檢討：試好幾種做法（例如各項指標的比重要不要、要多快跟著最近表現調整），用過去一年的資料各模擬一遍，看哪一種猜得最準，就改用那一種。",
  news: "收集鉅亨網、Yahoo 股市的財經新聞，和公司在公開資訊觀測站發布的重大訊息，依標題用字判斷偏好消息（利多）還是壞消息（利空）。這是用關鍵字粗略判斷，可能看錯，重要消息請點開原文確認。",
  glob: "台股常跟著國外走：美國股市（特別是半導體類股）、台積電在美國的股價、美元匯率、美國利率。這些已經算進大盤分數。美股是前一晚的收盤價。",
  upprob: "過去分數跟它差不多的股票，在這段期間後真的上漲的比例。是過去的統計，不是保證。",
  range: "過去分數差不多的股票，大部分（中間 6 成）的實際漲跌落在這個範圍。",
  rec: "推薦度：權證本身划不划算（價格、買賣價差、剩幾天到期、每天耗損多少、槓桿大小），加上股票本身看漲還是看跌，綜合打分。",
  quality: "權證條件分數（0～100）：只看這檔權證本身划不划算，不管股票會漲會跌。",
  money: "價內外：正數＝現在就有價值（價內），負數＝股價還要再漲（或跌）一段才有價值（價外）。稍微價外到剛好價平，通常最划算。",
  lev: "槓桿：股票漲 1%，這檔權證大約漲幾 %。",
  iv: "權證價格反推出的「預期波動」。跟股票實際的波動相比，越接近或越低，代表權證賣得越便宜。",
  spread: "買價和賣價差多少。越小越好；差太多，代表一買一賣就先虧在價差上。",
  theta: "什麼都沒變的情況下，權證每天光是時間經過就會少掉的價值。",
  days: "距離最後交易日還有幾天。少於 45 天時，權證價值掉得很快。",
  basis: "期貨價格減掉現貨（加權指數）。期貨比現貨高（正價差）通常代表市場比較樂觀，低（逆價差）比較保守；快到結算日時會趨近於零。",
  foi: "外資在台指期押多還是押空的淨口數。正數＝押漲，負數＝押跌；最近的變化方向比數字大小更重要。",
  pc: "選擇權裡「賭跌」的部位 ÷「賭漲」的部位。在台灣，這個比值偏高時，常被解讀為下方支撐較強。",
  dtscore: "當沖分數：依今天收盤後的資料，估計下一個交易日「開盤買、收盤賣」能賺錢的機會。",
  dtwin: "勝算＝扣掉手續費和稅之後，真的賺錢的機會。依過去 60 個交易日、條件差不多的股票隔天實際結果估算。超過 50% 而且平均是賺的，才算有優勢。",
  dttp: "過去條件差不多的股票，隔天從開盤算起通常最多漲（跌）到哪裡，可以當停利參考。",
  dtsl: "過去條件差不多的股票，隔天從開盤算起通常最多反向走到哪裡，可以當停損參考。",
  oi: "未平倉：市場上還沒了結的期貨口數。價格上漲、未平倉也增加，代表有新資金進場。",
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
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/>',
  news: '<path d="M4 5h13v14H6a2 2 0 0 1-2-2V5Z"/><path d="M17 9h3v8a2 2 0 0 1-2 2"/><path d="M7 9h7M7 13h7M7 16h4"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
};
const svgI = (k, fill) => `<svg viewBox="0 0 24 24" fill="${fill ? "currentColor" : "none"}" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[k]}</svg>`;

const NAV = [
  ["#/", "總覽", "home"], ["#/stocks", "選股", "list"], ["#/daytrade", "當沖", "bolt"], ["#/warrants", "權證", "warrant"],
  ["#/futures", "期貨", "fut"], ["#/watch", "自選", "star"], ["#/check", "實測對答案", "target"], ["#/model", "分數怎麼算", "model"], ["#/help", "使用說明", "help"],
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
  $("#hzseg").innerHTML = HZ_NAME.map((n, i) => `<button role="tab" aria-selected="${i === S.hz}" class="${i === S.hz ? "on" : ""}" data-hz="${i}" title="${HZ_SPAN[i]}">${hzTag(i)}</button>`).join("");
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
      ${r.s.map((s, i) => `<div style="text-align:center">${pill(s, HZ_NAME[i] + "（" + HZ_SPAN[i] + "）：" + labelOf(s))}</div>`).join("")}${starBtn(r.c)}</a>`;
  }
  return `<a class="row" href="#/stock/${r.c}">${nm}<div class="px">${fmtPx(r.px)}</div><div class="ch">${chgHtml(r.chg)}</div><div class="sb">${sbar(r.s[S.hz])}</div><div class="pm">${pill(r.s[S.hz])}</div></a>`;
}
function rowsHead3(sortKey, dir) {
  const b = (k, t) => `<button data-sort="${k}" class="${sortKey === k ? "on" : ""}">${t}${sortKey === k ? (dir > 0 ? " ↑" : " ↓") : ""}</button>`;
  return `<div class="row head s3"><div>${b("name", "股票")}</div><div class="hpx" style="text-align:right">${b("px", "股價")}</div><div class="hpx" style="text-align:right">${b("chg", "漲跌")}</div>
    ${HZ_NAME.map((n, i) => `<div style="text-align:center">${b("s" + i, hzTag(i))}</div>`).join("")}<div></div></div>`;
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
    else if (page === "check") await vCheck(tok);
    else if (page === "help") await vHelp(tok);
    else await vHome(tok);
  } catch (e) {
    console.error(e);
    if (tok === routeToken) view.innerHTML = `<div class="card empty"><h2>這一頁暫時無法顯示</h2><p>${esc(e.message === "notfound" ? "找不到這檔股票的分析，可能是剛上市、已下市，或平常幾乎沒人買賣。" : "讀取資料時發生問題：" + e.message)}</p><a class="btn" href="#/">回到總覽</a></div>`;
  }
  if (tok === routeToken) { FX.enhance(view); if (!location.hash.startsWith("#/stock/")) scrollTo(0, 0); }
}
addEventListener("hashchange", route);

const disclaimer = `<p class="disclaimer">本工具用證交所、櫃買中心、期交所的公開資料自動計算。分數和機率是根據過去的統計，不保證未來一定如此，也不是投資建議；買賣前請自己判斷，並控制好風險。</p>`;

// ====================================================================== 總覽
async function vHome(tok) {
  const L = S.latest, M = L.market, hz = HZ[S.hz], mh = M.horizons[hz];
  const liquid = L.stocks.filter((r) => !r.etf && r.val >= 0.3 && r.s[S.hz] != null);
  const top = [...liquid].sort((a, b) => b.s[S.hz] - a.s[S.hz]).slice(0, 10);
  const bot = [...liquid].sort((a, b) => a.s[S.hz] - b.s[S.hz]).slice(0, 10);
  const facts = [];
  if (M.up != null) facts.push(`今天上市股票 ${M.up} 家上漲、${M.down} 家下跌`);
  if (M.foi != null) facts.push(`外資在期貨上押${M.foi >= 0 ? "漲" : "跌"} ${fmtInt(Math.abs(M.foi))} 口${M.foi5 != null ? `，近 5 天又加碼押${M.foi5 >= 0 ? "漲" : "跌"} ${fmtInt(Math.abs(M.foi5))} 口` : ""}`);
  if (mh.pos.length) facts.push(`有利大盤：${mh.pos.join("、")}`);
  if (mh.neg.length) facts.push(`不利大盤：${mh.neg.join("、")}`);
  if (mh.similar_n) facts.push(`過去一年出現過 ${mh.similar_n} 次類似的盤勢，${HZ_DAYS[S.hz]}後大盤有 ${mh.similar_up} 次上漲，平均${mh.similar_avg >= 0 ? "漲" : "跌"} ${Math.abs(mh.similar_avg).toFixed(1)}%`);
  const mod = L.model[hz];
  const ind = L.industries || [];
  const w = S.watch.map((c) => S.byCode[c]).filter(Boolean).slice(0, 6);
  let picks = [];
  try { picks = (await api("warrant_picks")).picks.slice(0, 5); } catch { }
  if (tok !== routeToken) return;
  view.innerHTML = `
  <h1 class="grad">今天的台股氣氛</h1>
  <p class="lead">依 ${dayFull(L.day)} 收盤資料，判斷未來 ${HZ_SHORT[S.hz]}（約 ${[5, 20, 60][S.hz]} 個交易日）的方向。想看其他期間，按上方的「短期 1 週」「中期 1 個月」「長期 3 個月」切換。</p>
  <section class="card hero glow"><span class="glow-ring"></span>
    <div class="dial-wrap">${dial(mh.score, { size: "lg" })}<div class="verdict">大盤${mh.label}</div>${mh.rel != null ? `<a class="relnote" href="#/check">可信度 <span class="pill ${relInfo(mh.rel).c}">${relInfo(mh.rel).t}</span></a>${help("rel")}` : ""}</div>
    <div class="hero-side">
      <div class="idx"><span class="muted">加權指數</span><span class="big" data-count="${M.taiex}" data-dec="2">${fmtPx(M.taiex)}</span><span class="chg">${chgHtml(M.taiex_chg)}</span></div>
      <div class="hz3">${HZ.map((h, i) => `<button class="hzbox ${i === S.hz ? "on" : ""}" data-hz2="${i}"><div class="t">${HZ_NAME[i]}<span class="hsp">${HZ_SPAN[i].replace("・", "<br>")}</span></div><div class="v" data-count="${Math.round(M.horizons[h].score)}" data-from="50">${Math.round(M.horizons[h].score)}</div><div class="l">${M.horizons[h].label}</div></button>`).join("")}</div>
      <ul class="facts">${facts.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
    </div>
  </section>
  ${M.global && M.global.rows && M.global.rows.length || M.news ? `<div class="grid g2 section">${globalCard(M.global)}${newsCard(M.news)}</div>` : ""}
  <div class="grid g2 section">
    <section class="card flush"><div class="card-h" style="padding:18px 22px 4px"><h2>未來 ${HZ_SHORT[S.hz]}最看好的 10 檔</h2>${help("score")}<a class="more" href="#/stocks">看全部股票</a></div><div class="list">${top.map((r) => stockRow(r)).join("")}</div></section>
    <section class="card flush"><div class="card-h" style="padding:18px 22px 4px"><h2>未來 ${HZ_SHORT[S.hz]}最不看好的 10 檔</h2><a class="more" href="#/stocks?asc">看全部股票</a></div><div class="list">${bot.map((r) => stockRow(r)).join("")}</div></section>
  </div>
  <div class="grid g2 section">
    <section class="card"><div class="card-h"><h2>哪些產業比較強</h2><span class="note">產業內股票的平均分數（未來 ${HZ_SHORT[S.hz]}）</span></div>
      <div class="bars" id="indbars">${indBars(ind, 12)}</div>
      ${ind.length > 12 ? `<button class="btn" style="margin-top:12px" id="indall">顯示全部 ${ind.length} 個產業</button>` : ""}</section>
    <section class="card"><a class="checklink" href="#/check">${svgI("target")}<span><b>分數準不準？</b><span class="note">每天拿以前的分數和真正的漲跌對答案，模型也會依結果自我調整</span></span><span class="pill ${relInfo(mod && mod.rel).c} sm">可信度 ${relInfo(mod && mod.rel).t}</span></a>
      <div class="card-h" style="margin-top:18px"><h2>今日權證精選</h2>${help("rec")}<a class="more" href="#/warrants">看更多</a></div>
      ${picks.length ? `<div class="list" style="margin:0 -22px">${picks.map((p) => `<a class="row" href="#/warrants/${p.u}"><div class="nm"><b>${esc(p.n)}</b><span>${p.c}・標的 ${esc(p.un)}・${p.t === "C" ? "認購" : "認售"}</span></div><div class="px">${fmtPx(p.P)}</div><div class="ch"><span class="q ${p.rec >= 70 ? "hi" : "md"}">${Math.round(p.rec)}</span></div><div class="sb small muted">${esc(p.why[0] || "")}</div></a>`).join("")}</div>` : '<p class="note">權證資料準備中。</p>'}
    </section>
  </div>
  <p class="note section" style="text-align:center"><a href="#/check" style="color:var(--brass)">實測對答案</a>　·　<a href="#/model" style="color:var(--brass)">分數怎麼算</a>　·　<a href="#/help" style="color:var(--brass)">使用說明</a></p>
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

// ====================================================================== 選股
let stockState = { sort: "s", dir: -1, mk: "", ind: "", type: "stock", minval: 0.1, limit: 100, q: "" };
async function vStocks(tok) {
  if (location.hash.includes("asc")) { stockState.sort = "s"; stockState.dir = 1; history.replaceState(null, "", "#/stocks"); }
  const L = S.latest;
  const inds = [...new Set(L.stocks.map((r) => r.ind).filter(Boolean))].sort();
  view.innerHTML = `<h1>選股</h1><p class="lead">所有上市櫃股票與 ETF 的分數：短期看未來 1 週、中期看 1 個月、長期看 3 個月。點欄位名稱可以排序，點星號可以加入自選。</p>
    <div class="filters">
      <input type="text" id="fq" placeholder="篩選名稱或代號" value="${esc(stockState.q)}" aria-label="篩選">
      <select id="fmk" aria-label="市場"><option value="">上市＋上櫃</option><option>上市</option><option>上櫃</option></select>
      <select id="ftype" aria-label="類型"><option value="stock">只看股票</option><option value="etf">只看 ETF</option><option value="all">股票＋ETF</option></select>
      <select id="find" aria-label="產業"><option value="">全部產業</option>${inds.map((i) => `<option>${esc(i)}</option>`).join("")}</select>
      <select id="fval" aria-label="成交金額"><option value="0">不限成交量</option><option value="0.1">每天成交 1000 萬以上</option><option value="1">每天成交 1 億以上</option><option value="5">每天成交 5 億以上</option></select>
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
      <div class="muted small">${esc(d.m)}${d.ind ? "・" + esc(d.ind) : ""}・${dayFull(d.day)} 收盤
      ${d.news && d.news.disp ? `<span class="tag alert2" title="${esc(d.news.disp)}">處置股</span>` : d.news && d.news.warn ? `<span class="tag alert1" title="${esc(d.news.warn)}">注意股</span>` : ""}</div></div>
    <div class="px" data-count="${last[4]}" data-dec="${last[4] >= 1000 ? 0 : last[4] >= 100 ? 1 : 2}">${fmtPx(last[4])}</div><div class="chg">${chgHtml(chg)}</div>
    <div class="shb">${starBtn(code).replace('class="star', 'class="btn star').replace("</button>", "<span>自選</span></button>")}
      ${Array.isArray(d.dt) && d.dt[0] != null ? `<a class="btn" href="#/daytrade" title="下一個交易日當沖、扣掉手續費和稅後賺錢的機會">當沖勝算　多 <b class="num">${Math.round(d.dt[0])}%</b>　空 <b class="num">${Math.round(d.dt[1])}%</b></a>` : ""}
      ${d.warrants ? `<a class="btn" href="#/warrants/${code}">相關權證 ${d.warrants.n_call + d.warrants.n_put} 檔</a>` : ""}</div>
  </div>
  <div class="grid g3">
    ${hzs.map((h, i) => `<section class="card hzcard ${i === S.hz ? "cur" : ""}">
      <div class="card-h" style="margin:0"><h2>${HZ_NAME[i]}</h2><span class="note">${HZ_SPAN[i]}</span>${i === 0 ? help("score") : ""}</div>
      <div class="hzbody"><div class="hzd">${dial(h ? h.score : null, { animate: i === S.hz })}
      <div class="hzl">${h ? h.label : "資料不足"}</div></div><div class="hzs">
      ${h && h.up != null ? `<div class="stat">上漲機會 <b>${(h.up * 100).toFixed(0)}%</b>${i === 0 ? help("upprob") : ""}${base[i] != null ? `<span class="note">（一般股票 ${(base[i] * 100).toFixed(0)}%）</span>` : ""}</div>
      <div class="stat">常見漲跌 <b class="${cls(h.lo)}">${fmtPct(h.lo, 1)}</b> ～ <b class="${cls(h.hi)}">${fmtPct(h.hi, 1)}</b>${i === 0 ? help("range") : ""}</div>` : '<div class="stat muted">過去資料還不夠，暫時無法估計機率</div>'}
    </div></div></section>`).join("")}
  </div>
  ${cur ? `<section class="card section"><div class="card-h"><h2>為什麼是 ${Math.round(cur.score)} 分？</h2><span class="note">影響最大的幾個原因（未來 ${HZ_SHORT[S.hz]}）</span></div>
    <div class="why"><div class="plus"><h3>加分（偏多的理由）</h3><ul>${cur.pos.length ? cur.pos.map((t) => `<li><i>＋</i>${esc(t)}</li>`).join("") : '<li class="muted">沒有明顯的加分理由</li>'}</ul></div>
    <div class="minus"><h3>扣分（偏空的理由）</h3><ul>${cur.neg.length ? cur.neg.map((t) => `<li><i>－</i>${esc(t)}</li>`).join("") : '<li class="muted">沒有明顯的扣分理由</li>'}</ul></div></div>
    <p class="note" style="margin:14px 0 0">分數主要看這檔股票和其他股票比起來條件好不好（占 3/4），再加上大盤氣氛（占 1/4）。它目前的條件贏過全市場 ${Math.round(cur.pct * 100)}% 的股票。${cur.n ? `上漲機會是根據過去 ${fmtInt(cur.n)} 個分數差不多的例子統計出來的。` : ""}${(S.latest.model?.[HZ[S.hz]]?.rel ?? 1) < 0.4 ? "這個期間的分數最近不太準，所以先調得比較保守（靠近 50 分）。" : ""}</p></section>` : ""}
  ${stockNewsCard(d.news)}
  <section class="card section"><div class="card-h"><h2>股價走勢</h2><div class="seg" id="rng" style="margin-left:auto"><button data-n="60">3 個月</button><button data-n="120" class="on">6 個月</button><button data-n="250">1 年</button></div></div>
    <div class="chart" id="kchart"></div></section>
  <div class="grid g2 section">
    <section class="card"><div class="card-h"><h2>法人與散戶動向</h2><span class="note">近 20 個交易日，單位：張</span></div>
      <div class="kv" style="margin-bottom:14px">
        <div><span>外資近 5 天</span><b class="${cls(sum(1, 5))}">${fmtInt(sum(1, 5))}</b></div>
        <div><span>投信近 5 天</span><b class="${cls(sum(2, 5))}">${fmtInt(sum(2, 5))}</b></div>
        <div><span>自營商近 5 天</span><b class="${cls(sum(3, 5))}">${fmtInt(sum(3, 5))}</b></div>
        <div><span>融資（散戶借錢買）</span><b>${fmtInt(mbNow)}</b>${mbNow != null && mb20 ? `<span class="${cls(mbNow - mb20)}">20 日 ${mbNow >= mb20 ? "+" : ""}${fmtInt(mbNow - mb20)}</span>` : ""}</div>
      </div>
      <h3>外資每天買進（紅）或賣出（綠）</h3><div class="chart" id="cfi"></div>
      <h3 style="margin-top:10px">投信每天買進（紅）或賣出（綠）</h3><div class="chart" id="cit"></div>
    </section>
    <section class="card"><div class="card-h"><h2>公司賺不賺錢（基本面）</h2><span class="note">${f.rev_ym ? "營收 " + f.rev_ym.slice(0, 3) + "/" + f.rev_ym.slice(3) : ""}${f.q ? "・財報 " + f.q : ""}</span></div>
      <div class="kv">
        <div><span>本益比（越低越便宜）</span><b>${f.pe ? f.pe.toFixed(1) + " 倍" : "—"}</b></div>
        <div><span>股價淨值比</span><b>${f.pb ? f.pb.toFixed(2) + " 倍" : "—"}</b></div>
        <div><span>殖利率（股利÷股價）</span><b>${f.yld != null ? f.yld.toFixed(2) + "%" : "—"}</b></div>
        <div><span>上月營收比去年同月</span><b class="${cls(f.rev_yoy)}">${f.rev_yoy != null ? fmtPct(f.rev_yoy / 100, 1) : "—"}</b></div>
        <div><span>今年累計營收比去年</span><b class="${cls(f.rev_cum_yoy)}">${f.rev_cum_yoy != null ? fmtPct(f.rev_cum_yoy / 100, 1) : "—"}</b></div>
        <div><span>毛利率</span><b>${f.gm != null ? f.gm.toFixed(1) + "%" : "—"}</b></div>
        <div><span>本業利潤率</span><b>${f.om != null ? f.om.toFixed(1) + "%" : "—"}</b></div>
        <div><span>每股盈餘 EPS（${f.eps_q || "累計"}）</span><b>${f.eps != null ? f.eps.toFixed(2) : "—"}</b></div>
      </div>
      ${d.fut ? `<div class="card-h" style="margin-top:18px"><h2>個股期貨</h2>${help("basis")}</div>
        <div class="kv"><div><span>${esc(d.fut.c)} 近月</span><b>${fmtPx(d.fut.close)}</b></div><div><span>期現價差</span><b class="${cls(d.fut.basis)}">${fmtPct(d.fut.basis)}</b></div>
        <div><span>成交量</span><b>${fmtInt(d.fut.vol)} 口</b></div><div><span>未平倉</span><b>${fmtInt(d.fut.oi)} 口</b></div></div>` : ""}
      ${d.warrants ? `<div class="card-h" style="margin-top:18px"><h2>比較划算的權證</h2>${help("quality")}<a class="more" href="#/warrants/${code}">全部 ${d.warrants.n_call + d.warrants.n_put} 檔</a></div>
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
  <p class="lead">先選一檔股票，再挑划算的權證。看漲買「認購」、看跌買「認售」。推薦度同時看兩件事：權證本身划不划算，以及股票本身看漲還是看跌。</p>
  <div class="filters"><input type="text" id="wu" placeholder="輸入股票代號或名稱，例如 2330" style="min-width:260px" aria-label="搜尋標的"></div>
  <div id="wulist"></div>
  <section class="card flush section"><div class="card-h" style="padding:18px 22px 4px"><h2>今日精選</h2>${help("rec")}<span class="note">每檔股票只挑一檔最划算的；只列今天有成交、條件 60 分以上、而且看漲看跌方向和股票分數一致的</span></div>
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
    <th>權證</th>${showU ? "<th>股票分數</th>" : ""}<th>推薦度${help("rec")}</th><th>條件分數${help("quality")}</th><th>價格</th><th>價內外${help("money")}</th><th>剩幾天到期${help("days")}</th>
    <th>槓桿${help("lev")}</th><th>貴不貴（權證／股票波動）${help("iv")}</th><th>買賣價差${help("spread")}</th><th>每天耗損${help("theta")}</th><th style="text-align:left">白話說明</th></tr></thead><tbody>
    ${rows.map((p) => `<tr><td><b>${esc(p.n)}</b><br><span class="muted small">${p.c}・${p.t === "C" ? "認購" : "認售"}${showU ? "・" + esc(p.un) : ""}</span></td>
      ${showU ? `<td>${p.us ? pill(p.us[1], "股票中期（1 個月）分數") : "—"}</td>` : ""}
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
  const advice = sMid == null ? "" : sMid >= 60 ? `這檔股票未來 ${HZ_SHORT[S.hz]}是 ${Math.round(sMid)} 分（${labelOf(sMid)}），看漲，比較適合買認購權證。` : sMid <= 40 ? `這檔股票未來 ${HZ_SHORT[S.hz]}是 ${Math.round(sMid)} 分（${labelOf(sMid)}），看跌，比較適合買認售權證。` : `這檔股票未來 ${HZ_SHORT[S.hz]}是 ${Math.round(sMid)} 分，看不出明顯方向，建議先觀望，或只考慮條件特別好的權證。`;
  if (sMid != null && sMid <= 40) wTab = "P"; else if (sMid != null && sMid >= 60) wTab = "C";
  view.innerHTML = `<p><a class="note" href="#/warrants">← 回到權證</a></p>
    <div class="sh"><div><h1 style="margin-bottom:2px">${esc(name)} 的權證</h1><div class="muted small">認購 ${w.n_call} 檔、認售 ${w.n_put} 檔，依條件由好到差列出前 40 檔</div></div>
      ${sc ? `<div style="display:flex;gap:8px;align-items:center">${sc.map((s, i) => `<span class="small muted">${HZ_NAME[i]}</span>${pill(s)}`).join("")}</div>` : ""}
      ${r ? `<a class="btn" href="#/stock/${u}" style="margin-left:auto">看這檔股票的分析</a>` : ""}</div>
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
  view.innerHTML = `<h1>期貨</h1><p class="lead">台指期就是押大盤會漲還是會跌，所以直接用大盤分數判斷方向。下面另外列出外資在期貨上押多押空、期貨和現貨的價差等，幫你看市場氣氛。個股期貨則看那檔股票本身的分數。</p>
  <section class="card hero glow"><span class="glow-ring"></span>
    <div class="dial-wrap">${dial(mh.score, { size: "lg" })}<div class="verdict">台指期${mh.label}</div><div class="note">未來 ${HZ_SHORT[S.hz]}</div></div>
    <div class="hero-side">
      <div class="idx"><span class="muted">臺股期貨 ${tx ? tx.month.slice(0, 4) + "/" + tx.month.slice(4) : ""}</span><span class="big" ${tx ? `data-count="${tx.close}"` : ""}>${tx ? fmtPx(tx.close) : "—"}</span><span class="chg">${chgHtml(tx && tx.chg)}</span></div>
      <div class="kv" style="margin-top:14px">
        <div><span>期貨比現貨${help("basis")}</span><b class="${cls(basisPts)}">${basisPts != null ? (basisPts >= 0 ? "高 " : "低 ") + Math.abs(basisPts).toFixed(0) + " 點" : "—"}</b></div>
        <div><span>外資押漲／押跌${help("foi")}</span><b class="${cls(M.foi)}">${M.foi != null ? (M.foi >= 0 ? "押漲 " : "押跌 ") + fmtInt(Math.abs(M.foi)) + " 口" : "—"}</b></div>
        <div><span>外資近 5 天加碼</span><b class="${cls(M.foi5)}">${M.foi5 != null ? (M.foi5 >= 0 ? "+" : "") + fmtInt(M.foi5) + " 口" : "—"}</b></div>
        <div><span>選擇權看跌／看漲比${help("pc")}</span><b>${M.pc != null ? M.pc.toFixed(1) + "%" : "—"}</b></div>
      </div>
      <ul class="facts">${mh.pos.length ? `<li>有利大盤：${esc(mh.pos.join("、"))}</li>` : ""}${mh.neg.length ? `<li>不利大盤：${esc(mh.neg.join("、"))}</li>` : ""}</ul>
    </div>
  </section>
  <div class="grid g3 section">
    <section class="card"><div class="card-h"><h2>外資在期貨上押漲（正）或押跌（負）</h2><span class="note">口</span></div><div class="chart" id="cfoi"></div></section>
    <section class="card"><div class="card-h"><h2>加權指數</h2></div><div class="chart" id="ctx"></div></section>
    <section class="card"><div class="card-h"><h2>選擇權看跌／看漲比</h2><span class="note">%</span></div><div class="chart" id="cpc"></div></section>
  </div>
  <section class="card flush section"><div class="card-h" style="padding:18px 22px 4px"><h2>指數期貨</h2></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>商品</th><th>月份</th><th>收盤</th><th>漲跌</th><th>成交量</th><th>未平倉${help("oi")}</th></tr></thead><tbody>
    ${F.index.map((x) => `<tr><td><b>${esc(x.n)}</b></td><td>${x.month.slice(0, 4)}/${x.month.slice(4)}</td><td>${fmtPx(x.close)}</td><td>${chgHtml(x.chg)}</td><td>${fmtInt(x.vol)}</td><td>${fmtInt(x.oi)}</td></tr>`).join("")}</tbody></table></div></section>
  <section class="card flush section"><div class="card-h" style="padding:18px 22px 4px"><h2>個股期貨</h2><span class="note">依成交量排序；分數是那檔股票本身的分數</span></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>標的</th><th>期貨價</th><th>現貨價</th><th>期貨比現貨${help("basis")}</th><th>成交量</th><th>未平倉增減${help("oi")}</th>${HZ.map((_, i) => `<th>${hzTag(i)}</th>`).join("")}</tr></thead><tbody>
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
function dtPill(win, side) {
  if (win == null) return "p-mid";
  if (win >= 0.55) return side === "long" ? "p-up2" : "p-dn2";
  if (win > 0.5) return side === "long" ? "p-up1" : "p-dn1";
  return "p-mid";
}
async function vDayTrade(tok) {
  const d = await api("daytrade").catch(() => null);
  if (tok !== routeToken) return;
  if (!d) { view.innerHTML = `<h1>當沖</h1><div class="card empty"><h2>當沖分析準備中</h2><p>下次資料更新後就會出現。</p></div>`; return; }
  const M = d.model, L = M.long, Sx = M.short;
  const sideOk = (x) => x && x.avg > 0 && x.win > 0.5;
  if (!dtSide) dtSide = d.long_ok !== d.short_ok ? (d.long_ok > d.short_ok ? "long" : "short") : (sideOk(M.short) && !sideOk(M.long) ? "short" : "long");
  const pctS = (x) => (x * 100).toFixed(1) + "%";
  const sv = (x) => x == null ? "—" : `<span class="${cls(x)}">${x > 0 ? "+" : ""}${(x * 100).toFixed(2)}%</span>`;
  const statLine = (x, name) => x ? `${name}扣掉成本後 <b class="num">${pctS(x.win)}</b> 的機會賺錢，平均每筆 ${sv(x.avg)}` : `${name}：資料不足`;
  view.innerHTML = `<h1 class="grad">當沖</h1>
  <p class="lead">依 ${dayFull(d.day)} 收盤資料，估計<b>下一個交易日</b>「開盤買進、收盤前賣出」（或反過來先賣後買）能賺錢的機會。勝算已經扣掉手續費（6 折）和當沖證交稅，一買一賣約 ${(d.cost * 100).toFixed(2)}%。只看每天成交 1 億元以上、股價 10 元以上的股票，共 ${d.universe} 檔。</p>
  <a class="card checklink" href="#/check">${svgI("target")}<span><b>過去成績：先買後賣${sideOk(L) ? "有優勢" : "目前沒有優勢"}、先賣後買${sideOk(Sx) ? "有優勢" : "目前沒有優勢"}</b><span class="note">照分數先買後賣，${statLine(L, "")}；先賣後買，${statLine(Sx, "")}。詳細請看「實測對答案」。</span></span></a>
  <div class="section"><div class="seg" id="dtab"><button data-s="long">做多（先買後賣）</button><button data-s="short">做空（先賣後買）</button></div></div>
  <div id="dtwarn"></div>
  <section class="card flush section" id="dtlist"></section>
  <div class="section">
    <section class="card"><h3>目前最看重的指標</h3><p class="note" style="margin:2px 0 8px">紅色＝數字越高越適合先買後賣，綠色＝數字越高越適合先賣後買；越長影響越大</p><div class="bars" id="dtfw"></div></section>
  </div>
  <p class="disclaimer">當沖風險非常高：手續費和稅會吃掉大部分利潤，盤中漲跌也可能遠超過停損參考。勝算是過去的統計，不保證明天一定如此，也不是投資建議。請先確認已開通當沖資格，並嚴格控制買賣的金額。</p>`;
  const draw = () => {
    $$("#dtab button").forEach((b) => b.classList.toggle("on", b.dataset.s === dtSide));
    const rows = d[dtSide] || [];
    const okN = rows.filter((r) => r.ok).length;
    const sideStat = dtSide === "long" ? L : Sx;
    $("#dtwarn").innerHTML = okN ? `<div class="warnbox section">今天有 <b>${okN}</b> 檔標示「推薦」：過去條件差不多的股票，扣掉成本後賺錢的機會超過一半，而且平均是賺的。其他只供觀察。</div>` :
      `<div class="warnbox section">這個方向今天<b>沒有</b>推薦的股票：過去條件差不多的股票，扣掉成本後平均還是虧錢${sideOk(sideStat) ? "" : "，整體來看這個方向目前也沒有優勢"}。下面的名單只供觀察，不建議照做。</div>`;
    $("#dtlist").innerHTML = rows.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>股票</th><th>收盤</th><th>勝算${help("dtwin")}</th><th>平均每筆</th><th>停利參考${help("dttp")}</th><th>停損參考${help("dtsl")}</th><th>每天平均震盪</th><th>每天成交</th><th style="text-align:left">理由</th></tr></thead><tbody>
      ${rows.map((r) => `<tr style="cursor:pointer" onclick="location.hash='#/stock/${r.c}'"><td><b>${esc(r.n)}</b> ${r.al ? '<span class="tag alert1">注意股</span> ' : ""}${r.ok ? `<span class="pill ${dtSide === "long" ? "p-up2" : "p-dn2"}" style="height:20px;min-width:0;font-size:12px">推薦</span>` : ""}<br><span class="muted small">${r.c}・${esc(r.m)}</span></td>
        <td>${fmtPx(r.px)}<br>${chgHtml(r.chg)}</td>
        <td><span class="pill ${dtPill(r.win, dtSide)}" title="扣成本後勝率">${(r.win * 100).toFixed(0)}%</span></td><td>${sv(r.avg)}</td>
        <td>${r.tp != null ? (dtSide === "long" ? "+" : "−") + Math.abs(r.tp * 100).toFixed(1) + "%" : "—"}</td>
        <td>${r.sl != null ? (dtSide === "long" ? "−" : "+") + Math.abs(r.sl * 100).toFixed(1) + "%" : "—"}</td>
        <td>${r.atr != null ? (r.atr * 100).toFixed(1) + "%" : "—"}</td><td>${r.val != null ? r.val.toFixed(1) + " 億" : "—"}</td>
        <td class="txt">${esc((r.why || []).join("；"))}</td></tr>`).join("")}</tbody></table></div>` : '<div class="empty"><p>今天沒有可評估的標的。</p></div>';
    FX.enhance($("#dtlist"));
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
  view.innerHTML = `<h1>我的自選</h1><p class="lead">在任何股票旁點星號就能加入。${S.status && S.status.static ? "雲端版的自選存在這支手機（或這個瀏覽器）裡。" : "自選清單存在你的電腦上，電腦和手機開啟時看到的是同一份。"}</p>
    ${rows.length ? `<section class="card flush"><div class="list">${rowsHead3("", 0)}${rows.map((r) => stockRow(r, { mode: "three" })).join("")}</div></section>` :
      `<div class="card empty"><h2>還沒有自選股</h2><p>用上方搜尋找到股票後，點「自選」星號加入，就能在這裡一次看到它們的分數。</p><a class="btn primary" href="#/stocks">去選股</a></div>`}${disclaimer}`;
}

// ====================================================================== 分數怎麼算
async function vModel(tok) {
  const m = await api("model");
  let tu = null;
  try { tu = await api("tuning"); } catch { }
  if (tok !== routeToken) return;
  view.innerHTML = `<h1>分數怎麼算</h1>
  <p class="lead">分數由約 35 項指標組成，每項指標占的比重不一樣。下面列出每個期間影響最大的指標：<b>紅色</b>代表數字越高越加分，<b>綠色</b>代表數字越高越扣分，長條越長影響越大。比重怎麼決定、準不準，請看 <a href="#/check" style="color:var(--brass)">實測對答案</a>。資料期間 ${dayFull(m.first_day)}～${dayFull(m.last_day)}，共 ${m.days} 個交易日。</p>
  ${HZ.map((h, i) => `<section class="card section"><div class="card-h"><h2>${HZ_NAME[i]}：預測未來 ${HZ_SHORT[i]}</h2><span class="note">目前做法：${esc(((tu && tu.main) || {})[h]?.name || "預設做法")}</span></div>
      <div class="bars fw2" id="fw${i}"></div></section>`).join("")}
  <p class="disclaimer">比重每天收盤後依實測結果自動更新。累積的資料越多，越可信。</p>`;
  const draw = () => HZ.forEach((h, i) => {
    const x = m.horizons[h];
    const fs = (x.factors || []).slice(0, 16), mx = Math.max(...fs.map((f) => Math.abs(f.w)), 1e-6);
    $("#fw" + i).innerHTML = fs.map((f) => `<div class="b" title="${esc(f.group)}類指標；最近 ${accLabel(f.ic).t}"><span class="nm">${esc(f.name)}</span><div class="sbar"><div class="track"><div class="fill ${f.w >= 0 ? "u" : "d"}" style="left:${f.w >= 0 ? 50 : 50 - Math.abs(f.w) / mx * 50}%;width:${Math.abs(f.w) / mx * 50}%"></div></div></div><span class="v small">${f.group}</span></div>`).join("");
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

// ====================================================================== 國際市場與消息面
function spark(vals, up) {
  const v = (vals || []).filter((x) => x != null);
  if (v.length < 2) return "";
  const W = 84, H = 26, lo = Math.min(...v), hi = Math.max(...v), r = hi - lo || 1;
  const pts = v.map((x, i) => `${(i / (v.length - 1) * W).toFixed(1)},${(H - 2 - (x - lo) / r * (H - 4)).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="${up ? "var(--up)" : "var(--down)"}" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
}
function globalCard(G) {
  if (!G || !G.rows || !G.rows.length) return "";
  const fmtV = (r) => r.unit === "pt" ? r.v.toFixed(2) + "%" : r.v >= 1000 ? fmtInt(Math.round(r.v)) : r.v.toFixed(r.v >= 100 ? 1 : 2);
  const ch = (r, x) => x == null ? "—" : r.unit === "pt" ? `<span class="${cls(x)}">${x > 0 ? "+" : ""}${x.toFixed(2)}</span>` : chgHtml(x, 1);
  const NOTE = { "^SOX": "台股電子股的風向球", "^IXIC": "美國科技股", "^GSPC": "美國大型股", "TSM": "台積電在美國的股價", "^VIX": "越高代表市場越緊張", "^TNX": "利率；變化以百分點計", "TWD=X": "數字變大＝台幣貶值", "DX-Y.NYB": "美元強弱", "^N225": "日本股市", "CL=F": "國際油價" };
  return `<section class="card flush"><div class="card-h" style="padding:18px 22px 4px"><h2>${svgI("globe")} 國際市場</h2>${help("glob")}<span class="note" style="margin-left:auto">${G.at ? "更新 " + esc(G.at.slice(5)) : ""}</span></div>
    <div class="tbl-wrap"><table class="tbl gtbl"><thead><tr><th style="text-align:left">項目</th><th>最新</th><th>1 日</th><th>1 週</th><th class="hide-s2">1 個月</th><th class="hide-s">近 3 個月</th></tr></thead><tbody>
    ${G.rows.map((r) => `<tr><td style="text-align:left"><b>${esc(r.name)}</b>${NOTE[r.sym] ? `<br><span class="muted small">${NOTE[r.sym]}</span>` : ""}</td><td class="num">${fmtV(r)}</td><td>${ch(r, r.c1)}</td><td>${ch(r, r.c5)}</td><td class="hide-s2">${ch(r, r.c20)}</td><td class="hide-s">${spark(r.spark, (r.spark[r.spark.length - 1] ?? 0) >= (r.spark[0] ?? 0))}</td></tr>`).join("")}
    </tbody></table></div><p class="note" style="padding:8px 22px 16px;margin:0">美股是前一晚的收盤。這些數字已經算進大盤分數。</p></section>`;
}
function sentTag(x) {
  if (x > 0.05) return '<span class="stag pos">利多</span>';
  if (x < -0.05) return '<span class="stag neg">利空</span>';
  return '<span class="stag">中性</span>';
}
function ago(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000), now = Date.now(), m = Math.round((now - d) / 60000);
  if (m < 60) return m + " 分鐘前";
  if (m < 60 * 24) return Math.round(m / 60) + " 小時前";
  return `${d.getMonth() + 1}/${d.getDate()}`;
}
function newsCard(N) {
  if (!N) return `<section class="card"><div class="card-h"><h2>${svgI("news")} 消息面</h2></div><p class="note">新聞資料將在下次更新後出現。</p></section>`;
  const tot = N.pos + N.neg || 1, pw = N.pos / tot * 100;
  const mood = N.mood > 0.05 ? "偏樂觀" : N.mood < -0.05 ? "偏悲觀" : "好壞參半";
  return `<section class="card flush"><div class="card-h" style="padding:18px 22px 4px"><h2>${svgI("news")} 消息面</h2>${help("news")}<span class="note" style="margin-left:auto">近兩天 ${N.n} 則財經新聞</span></div>
    <div style="padding:4px 22px 10px"><div class="moodline"><span>新聞氣氛 <b>${mood}</b></span><span class="note">好消息 ${N.pos} 則・壞消息 ${N.neg} 則</span></div>
      <div class="moodbar"><i style="width:${pw}%"></i></div>
      ${N.warn_n || N.disp_n ? `<p class="note" style="margin:8px 0 0">今天有 ${N.warn_n} 檔被列為注意股（近期漲跌或成交量異常）、${N.disp_n} 檔處置股（交易受限制，已從當沖推薦中排除）。</p>` : ""}</div>
    <ul class="newslist">${(N.heads || []).slice(0, 8).map((h) => `<li>${sentTag(h.s)}<a href="${esc(h.u)}" target="_blank" rel="noopener">${esc(h.t)}</a><span class="muted small">${esc(h.src || "")}・${ago(h.at)}</span></li>`).join("")}</ul></section>`;
}
function stockNewsCard(N) {
  if (!N) return "";
  const items = N.items || [], mops = N.mops || [];
  return `<section class="card section"><div class="card-h"><h2>${svgI("news")} 相關新聞與公告</h2>${help("news")}<span class="note">近期，依時間排列</span></div>
    ${N.disp ? `<div class="warnbox" style="margin-bottom:10px">本股目前為<b>處置股</b>：${esc(N.disp)}。處置期間每隔幾分鐘才撮合一次，買賣前還要先付清款項或股票，比較難買賣。</div>` : N.warn ? `<div class="warnbox" style="margin-bottom:10px">本股今天被列為<b>注意股</b>：${esc(N.warn)}</div>` : ""}
    ${mops.length ? `<h3>公司公告（公開資訊觀測站重大訊息）</h3><ul class="newslist tight">${mops.map((m) => `<li>${sentTag(m.s)}<span>${esc(m.t)}</span><span class="muted small">${dayStr(m.d)}</span></li>`).join("")}</ul>` : ""}
    ${items.length ? `<h3 style="margin-top:10px">新聞</h3><ul class="newslist tight">${items.map((h) => `<li>${sentTag(h.s)}<a href="${esc(h.u)}" target="_blank" rel="noopener">${esc(h.t)}</a><span class="muted small">${esc(h.src || "")}・${ago(h.at)}</span></li>`).join("")}</ul>` : '<p class="note">最近沒有提到這檔股票的新聞。</p>'}
  </section>`;
}

// ====================================================================== 實測對答案
function checkChart(box, series, h) {
  // 上：當時的大盤分數；下：之後實際漲跌（柱）
  const W = Math.max(280, box.clientWidth), H = 200, PL = 4, PR = 44, mid = 92;
  const n = series.length;
  if (n < 5) { box.innerHTML = '<p class="note">資料累積中</p>'; return; }
  const pw = W - PL - PR, x = (i) => PL + i / (n - 1) * pw;
  const ys = (v) => 8 + (85 - v) / 70 * (mid - 16);
  const rets = series.map((p) => p[2]).filter((v) => v != null);
  const rm = Math.max(0.01, ...rets.map(Math.abs));
  const yr = (v) => mid + 18 + (H - mid - 30) / 2 - v / rm * (H - mid - 30) / 2;
  const line = series.map((p, i) => `${x(i).toFixed(1)},${ys(Math.max(15, Math.min(85, p[1]))).toFixed(1)}`).join(" ");
  const bw = Math.max(1, pw / n - 0.6);
  const bars = series.map((p, i) => p[2] == null ? "" : `<rect x="${(x(i) - bw / 2).toFixed(1)}" y="${Math.min(yr(0), yr(p[2])).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.abs(yr(p[2]) - yr(0)).toFixed(1)}" fill="${p[2] >= 0 ? "var(--up)" : "var(--down)"}" opacity=".8"/>`).join("");
  const dots = series.map((p, i) => { const ok = p[2] == null ? null : (p[1] >= 55 && p[2] > 0) || (p[1] <= 45 && p[2] < 0); const bad = p[2] != null && ((p[1] >= 55 && p[2] <= 0) || (p[1] <= 45 && p[2] >= 0)); return ok || bad ? `<circle cx="${x(i).toFixed(1)}" cy="${(H - 6).toFixed(1)}" r="2.2" fill="${ok ? "var(--brass)" : "var(--muted)"}"/>` : ""; }).join("");
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">
    <g class="axis grid"><line x1="${PL}" x2="${PL + pw}" y1="${ys(50)}" y2="${ys(50)}"/><text x="${W - 2}" y="${ys(50) + 4}" text-anchor="end">50 分</text>
    <line x1="${PL}" x2="${PL + pw}" y1="${ys(55)}" y2="${ys(55)}" stroke-dasharray="2 4"/><line x1="${PL}" x2="${PL + pw}" y1="${ys(45)}" y2="${ys(45)}" stroke-dasharray="2 4"/>
    <text x="${W - 2}" y="${ys(80) + 4}" text-anchor="end">看多</text><text x="${W - 2}" y="${ys(20) + 4}" text-anchor="end">看空</text>
    <line x1="${PL}" x2="${PL + pw}" y1="${yr(0)}" y2="${yr(0)}"/><text x="${W - 2}" y="${yr(rm) + 10}" text-anchor="end">+${(rm * 100).toFixed(0)}%</text><text x="${W - 2}" y="${yr(-rm)}" text-anchor="end">−${(rm * 100).toFixed(0)}%</text>
    <text x="${PL}" y="${H - 14}">${dayStr(series[0][0])}</text><text x="${PL + pw}" y="${H - 14}" text-anchor="end">${dayStr(series[n - 1][0])}</text></g>
    ${bars}<polyline points="${line}" fill="none" stroke="var(--brass)" stroke-width="2" stroke-linejoin="round"/>${dots}
    <rect class="hit" x="${PL}" y="0" width="${pw}" height="${H}" fill="transparent"/></svg><div class="tip hide"></div>`;
  const svg = $("svg", box);
  svg.addEventListener("pointermove", (e) => {
    const r = svg.getBoundingClientRect(), i = Math.max(0, Math.min(n - 1, Math.round((e.clientX - r.left - PL) / pw * (n - 1))));
    const p = series[i];
    tipAt(box, `<b>${dayFull(p[0])}</b><br>當時大盤分數 ${p[1].toFixed(0)}（${labelOf(p[1])}）<br>之後 ${h} 個交易日實際 ${p[2] == null ? "尚未揭曉" : `<span class="${cls(p[2])}">${p[2] > 0 ? "+" : ""}${(p[2] * 100).toFixed(2)}%</span>`}`, e.clientX - r.left, e.clientY - r.top);
  });
  svg.addEventListener("pointerleave", () => hideTip(box));
}
function verdictOf(edge, good, bad, pre = "") {
  if (edge == null) return { t: "資料不足", c: "p-mid" };
  if (edge >= good) return { t: pre + "有參考價值", c: "p-good" };
  if (edge <= bad) return { t: pre + "不準", c: "p-bad" };
  return { t: pre + "普通", c: "p-mid" };
}
function accLabel(x) {
  if (x == null) return { t: "資料不足", c: "" };
  if (x >= 0.05) return { t: "很準", c: "acc-good" };
  if (x >= 0.02) return { t: "有用", c: "acc-good" };
  if (x > 0.005) return { t: "略有用", c: "" };
  if (x > -0.005) return { t: "沒差別", c: "muted" };
  return { t: "猜反了", c: "acc-bad" };
}
function tenTimes(p) { return p == null ? "" : `10 次裡約有 ${Math.round(p * 10)} 次是這樣`; }
async function vCheck(tok) {
  const m = await api("model");
  let dt = null, tu = null;
  try { dt = await api("daytrade"); } catch { }
  try { tu = await api("tuning"); } catch { }
  if (tok !== routeToken) return;
  const MC = m.market_check || {}, MR = m.market_rel || {};
  const P = (x, d = 0) => x == null ? "—" : (x * 100).toFixed(d) + "%";
  const R = (x, d = 2) => x == null ? "—" : `<span class="${cls(x)}">${x > 0 ? "+" : ""}${(x * 100).toFixed(d)}%</span>`;
  const DM = dt && dt.model;
  const cfgName = (part, hn) => tu ? (part === "dt" ? tu.dt : (tu.main || {})[hn])?.name || "預設做法" : "預設做法";
  const trend = (roll) => {
    const v = (roll || []).map((p) => p[1]).filter((x) => x != null);
    if (v.length < 60) return null;
    const a = v.slice(0, v.length - 40), b = v.slice(-40);
    return { early: a.reduce((s, x) => s + x, 0) / a.length, late: b.reduce((s, x) => s + x, 0) / b.length };
  };
  const ok = (x) => x && x.avg > 0 && x.win > 0.5;
  const line = (icon, cl, title, text) => `<li class="cl ${cl}"><i>${icon}</i><span><b>${title}</b>${text}</span></li>`;
  // ---- 結論卡
  const cards = HZ.map((h, i) => {
    const x = m.horizons[h], c = MC[h] || {}, tr = trend(x.ic_roll), d = HZ_SHORT[i];
    const lines = [];
    if (x.spread_avg == null) lines.push(line("…", "", "選股：", "資料累積中。"));
    else {
      const good = x.spread_avg > 0.002 && (x.spread_win ?? 0) > 0.53;
      const lvl = !good ? "沒什麼用" : (x.spread_win >= 0.65 ? "有用" : "有一點用");
      lines.push(line(good ? "✓" : "✗", good ? "ok" : "no", `選股${lvl}：`, `分數高的股票，${d}後平均比分數低的${x.spread_avg >= 0 ? "多賺" : "少賺"} ${Math.abs(x.spread_avg * 100).toFixed(1)}%，${tenTimes(x.spread_win)}。`));
    }
    if (c.call_hit != null && c.base_up != null) {
      const base = Math.max(c.base_up, 1 - c.base_up), up = c.base_up >= 0.5;
      const better = c.call_hit > base;
      lines.push(line(better ? "✓" : "✗", better ? "ok" : "no", better ? "看大盤有用：" : `看大盤還不如直接猜「${up ? "會漲" : "會跌"}」：`,
        better ? `模型猜對 ${P(c.call_hit)}，比一律猜${up ? "漲" : "跌"}（${P(base)}）準。` : `這段期間大盤大多在${up ? "漲" : "跌"}，一律猜${up ? "漲" : "跌"}就能猜對 ${P(base)}，模型只猜對 ${P(c.call_hit)}。`));
    }
    if (tr && tr.early > 0.02 && tr.late < 0) lines.push(line("!", "warn", "最近變不準了：", "最近 2 個月常猜反，所以分數先調得保守（多半在 40～60 分）。"));
    else if (x.rel != null && x.rel < 0.4) lines.push(line("!", "warn", "最近不太準：", "所以分數先調得保守（多半在 40～60 分）。"));
    else if (x.rel != null) lines.push(line("✓", "ok", "最近表現穩定：", "分數照常顯示。"));
    return `<div class="concl"><h3>${HZ_NAME[i]}<small>預測未來 ${d}</small></h3><ul>${lines.join("")}</ul><p class="note">目前做法：${esc(cfgName("main", h))}</p></div>`;
  });
  if (DM && DM.long) {
    cards.push(`<div class="concl"><h3>當沖<small>隔天開盤買、收盤賣</small></h3><ul>
      ${line(ok(DM.long) ? "✓" : "✗", ok(DM.long) ? "ok" : "no", `先買後賣${ok(DM.long) ? "有優勢" : "沒有優勢"}：`, `照分數做，扣掉手續費和稅後有 ${P(DM.long.win)} 的機會賺錢，平均每筆 ${R(DM.long.avg)}。`)}
      ${DM.short ? line(ok(DM.short) ? "✓" : "✗", ok(DM.short) ? "ok" : "no", `先賣後買${ok(DM.short) ? "有一點優勢" : "沒有優勢"}：`, `照分數做，扣掉成本後有 ${P(DM.short.win)} 的機會賺錢，平均每筆 ${R(DM.short.avg)}。`) : ""}
      </ul><p class="note">目前做法：${esc(cfgName("dt"))}</p></div>`);
  }
  // ---- 自我調整
  const tuneTable = (rows, title) => {
    if (!rows || !rows.length) return `<div><h3>${title}</h3><p class="note">資料累積中</p></div>`;
    const top = rows.slice(0, 4);
    const fixed = rows.find((r) => r.sk >= 1e11);
    if (fixed && !top.includes(fixed)) top.push(fixed);
    const mx = Math.max(0.01, ...rows.map((r) => Math.abs(r.score || 0)));
    const lab = (x) => { const a = accLabel(x); return `<span class="${a.c}" title="${x == null ? "" : "一致程度 " + x.toFixed(3)}">${a.t}</span>`; };
    return `<div><h3>${title}</h3><table class="tbl tune"><thead><tr><th>做法</th><th>整體</th><th>最近</th></tr></thead><tbody>
      ${top.map((r) => `<tr class="${r.chosen ? "on" : ""}"><td class="txt">${r.chosen ? "✓ " : ""}${esc(r.name)}<div class="tbar"><i class="${(r.score || 0) >= 0 ? "g" : "b"}" style="width:${Math.abs(r.score || 0) / mx * 100}%"></i></div></td><td>${lab(r.all)}</td><td>${lab(r.recent)}</td></tr>`).join("")}
      </tbody></table></div>`;
  };
  const EV = (tu && tu.eval) || {};
  const logs = ((tu && tu.log) || []).slice(-8).reverse();
  const hist = (tu && tu.history) || [];
  const histDays = [...new Set(hist.map((x) => x.day))];
  const PART_NAME = { short: "短期", mid: "中期", long: "長期", dt: "當沖" };
  // ---- 各期間詳細
  const sections = HZ.map((h, i) => {
    const c = MC[h], x = m.horizons[h], rc = x.recent, mr = MR[h] || {}, d = HZ_SHORT[i];
    const mv = verdictOf(c ? c.corr : null, 0.15, 0, "整體");
    const sv = verdictOf(x.rel_ic, 0.03, 0, "最近");
    const base = c && c.base_up != null ? Math.max(c.base_up, 1 - c.base_up) : null;
    return `<section class="card section"><div class="card-h"><h2>${HZ_NAME[i]}：預測未來 ${d}<span class="note" style="margin-left:8px">約 ${[5, 20, 60][i]} 個交易日</span></h2></div>
    <div class="grid g2">
      <div><div class="card-h" style="margin:0 0 6px"><h3>選股準不準</h3><span class="pill ${sv.c} sm">${sv.t}</span></div>
        ${x.top_hit != null ? `<div class="kv"><div><span>分數最高的 2 成股票，${d}後上漲的比例</span><b>${P(x.top_hit, 1)}</b><span class="note">全部股票是 ${P(x.base_hit, 1)}</span></div>
          <div><span>分數最低的 2 成股票，${d}後下跌的比例</span><b>${P(x.bot_fall, 1)}</b><span class="note">全部股票是 ${P(x.base_fall, 1)}</span></div>
          <div><span>高分股比低分股平均多賺</span><b>${R(x.spread_avg)}</b><span class="note">${tenTimes(x.spread_win)}</span></div>
          <div><span>最近準不準</span><b><span class="pill ${relInfo(x.rel).c} sm">${relInfo(x.rel).t === "低" ? "不太準" : relInfo(x.rel).t === "中" ? "普通" : "準"}</span></b><span class="note">${{ "猜反了": "最近常猜反", "沒差別": "最近分數和漲跌幾乎沒關係", "略有用": "最近略有幫助", "有用": "最近有幫助", "很準": "最近很準", "資料不足": "資料不足" }[accLabel(x.rel_ic).t]}</span></div></div>
          <p class="note" style="margin:8px 0 0">統計了 ${x.eval_days} 個交易日，每天都只用當天以前的資料打分數。</p>` : '<p class="note">資料累積中</p>'}
        <div class="grid g2" style="margin-top:14px">
          <div><h3>分數高低 vs 真的上漲的比例</h3><p class="note" style="margin:2px 0 8px">左邊是分數最低的一成、右邊是最高的一成；越往右越高，代表分數越有用（最近約 3 個月）</p><div class="chart" id="cal${i}"></div></div>
          <div><h3>準確度的變化</h3><p class="note" style="margin:2px 0 8px">線在 0 以上＝分數有用；掉到 0 以下＝那段時間猜反了</p><div class="chart" id="ic${i}"></div></div>
        </div>
        ${rc ? `<h3 style="margin-top:16px">最近一次對答案：${dayFull(rc.from)} 的分數，到 ${dayFull(rc.to)} 的結果</h3>
          <p class="note" style="margin:2px 0 8px">在每天成交 1 億元以上的股票中，挑出當天分數最高和最低的各 10 檔，看到今天實際漲跌多少。同期間大盤 ${R(rc.taiex)}、全部股票平均 ${R(rc.all_avg)}。</p>
          <div class="grid g2 rcgrid"><div><div class="rch up">分數最高的 10 檔　平均 ${R(rc.top_avg)}<span class="note">　${rc.top_up} 檔上漲</span></div>
            <ul class="rcl">${rc.top.map((r) => `<li><a href="#/stock/${r.c}">${esc(r.n)}</a><span class="num">${R(r.r, 1)}</span></li>`).join("")}</ul></div>
            <div><div class="rch dn">分數最低的 10 檔　平均 ${R(rc.bot_avg)}<span class="note">　${rc.bot_dn} 檔下跌</span></div>
            <ul class="rcl">${rc.bot.map((r) => `<li><a href="#/stock/${r.c}">${esc(r.n)}</a><span class="num">${R(r.r, 1)}</span></li>`).join("")}</ul></div></div>
          <p class="note" style="margin:6px 0 0">${rc.top_avg > rc.bot_avg ? `這一次猜對了：高分組比低分組多賺 ${((rc.top_avg - rc.bot_avg) * 100).toFixed(1)} 個百分點。` : `這一次猜錯了：高分組反而比低分組少賺 ${((rc.bot_avg - rc.top_avg) * 100).toFixed(1)} 個百分點。`}單一次的結果運氣成分很大，請以上面的長期統計為準。</p>` : ""}
      </div>
      <div><div class="card-h" style="margin:0 0 6px"><h3>看大盤準不準</h3><span class="pill ${mv.c} sm">${mv.t}</span></div>
        ${c && c.n ? `<p style="margin:0 0 6px">過去 ${c.n} 個交易日裡，模型說「偏多」（55 分以上）的有 <b>${c.bull_n}</b> 天，${d}後大盤真的漲的占 <b class="num">${P(c.bull_hit)}</b>；說「偏空」（45 分以下）的有 <b>${c.bear_n}</b> 天，${d}後真的跌的占 <b class="num">${P(c.bear_hit)}</b>。</p>
        <p class="note" style="margin:0 0 6px">對照：這段期間隨便挑一天，${d}後大盤上漲的機率是 ${P(c.base_up)}。${base != null ? (c.call_hit > base ? `模型比「一律猜${c.base_up >= 0.5 ? "漲" : "跌"}」準一些。` : `所以模型看大盤，還沒有比「一律猜${c.base_up >= 0.5 ? "漲" : "跌"}」準；這段期間大盤主要是順著趨勢走。`) : ""}</p>
        ${mr.raw != null && Math.abs(mr.raw - mr.score) >= 1 ? `<p class="note" style="margin:0 0 6px">今天：模型原本算出 ${Math.round(mr.raw)} 分，但最近不太準，所以調成 ${Math.round(mr.score)} 分。</p>` : ""}
        <div class="chart" id="mc${i}"></div><p class="note" style="margin:4px 0 0">金線＝當時的大盤分數；紅綠柱＝之後 ${d}大盤實際漲跌；底部金點＝猜對、灰點＝猜錯（只算 55 分以上或 45 分以下的日子）。</p>` : '<p class="note">資料累積中</p>'}
      </div>
    </div></section>`;
  }).join("");
  const dtSec = DM ? `<section class="card section"><div class="card-h"><h2>當沖：隔天開盤買、收盤賣<span class="note" style="margin-left:8px">已扣手續費和稅</span></h2><a class="more" href="#/daytrade">看當沖名單</a></div>
    <div class="grid g3">
      <div><div class="kv"><div><span>照分數先買後賣（分數最高一成）</span><b>${P(DM.long && DM.long.win, 1)}</b><span class="note">賺錢的機會・平均每筆 ${R(DM.long && DM.long.avg)}</span></div>
        <div><span>照分數先賣後買（分數最低一成）</span><b>${P(DM.short && DM.short.win, 1)}</b><span class="note">賺錢的機會・平均每筆 ${R(DM.short && DM.short.avg)}</span></div>
        <div><span>隨便挑股票先買後賣（對照）</span><b>${P(DM.base_win, 1)}</b><span class="note">賺錢的機會</span></div></div>
        <p class="note" style="margin:8px 0 0">統計最近 ${DM.eval_days} 個交易日。</p></div>
      <div><h3>分數高低 vs 先買後賣賺錢的機會</h3><p class="note" style="margin:2px 0 8px">左邊分數最低、右邊最高；虛線是隨便挑股票的結果</p><div class="chart" id="dtcal"></div></div>
      <div><h3>準確度的變化</h3><p class="note" style="margin:2px 0 8px">線在 0 以上＝分數有用；掉到 0 以下＝那段時間猜反了</p><div class="chart" id="dtic"></div></div>
    </div></section>` : "";
  view.innerHTML = `<h1 class="grad">實測對答案</h1>
  <p class="lead">這頁回答一個問題：<b>分數到底準不準？</b>做法是把過去每一天算出來的分數，拿去跟後來真正的漲跌對答案（當時只用當天以前的資料，不作弊）。每天收盤後自動更新。資料期間 ${dayFull(m.first_day)}～${dayFull(m.last_day)}。</p>
  <section class="card glow"><span class="glow-ring"></span><div class="card-h"><h2>結論</h2><span class="note">✓ 有用　✗ 沒用　! 要注意</span></div>
    <div class="grid g2 concls">${cards.join("")}</div>
    <p class="note" style="margin:12px 0 0">股價短期漲跌本來就很難預測，就算是專業機構的模型，也只是「比亂猜好一點」。這頁幫你看出哪些分數現在比較能參考；標示「不太準」的時候，請保守看待。</p></section>
  <section class="card section"><div class="card-h"><h2>模型每天自我調整</h2>${help("tune")}<span class="note">${tu && tu.eval_day ? "最近一次：" + dayFull(tu.eval_day) : ""}</span></div>
    <p style="margin:0 0 6px">每天收盤後，模型會試好幾種計分做法——主要差在「各項指標的比重，要不要、要多快跟著最近的表現改」——用過去一年的資料各模擬一遍，看哪一種猜得最準，就改用那一種（打 ✓ 的）。新做法要明顯比較好才會換，避免天天換來換去。</p>
    <p class="note" style="margin:0 0 12px">「整體」看過去一年，「最近」看最近幾個月；金色長條越長越準，灰色代表反而猜反了。</p>
    <div class="grid g2">${tuneTable(EV.main && EV.main.short, "短期（1 週）")}${tuneTable(EV.main && EV.main.mid, "中期（1 個月）")}${tuneTable(EV.main && EV.main.long, "長期（3 個月）")}${tuneTable(EV.dt, "當沖")}</div>
    <h3 style="margin-top:16px">調整紀錄</h3>
    ${logs.length ? `<ul class="rcl">${logs.map((l) => `<li><span>${dayFull(l.day)}　${PART_NAME[l.hn] || ""}：${l.from ? `由「${esc(l.from)}」改為` : "開始採用"}「${esc(l.to)}」</span></li>`).join("")}</ul>` : '<p class="note">還沒有調整過。</p>'}
    ${histDays.length >= 5 ? `<h3 style="margin-top:16px">每天的比較結果</h3><p class="note" style="margin:2px 0 8px">金線＝採用的做法，灰虛線＝固定比重（對照）；金線比灰線高，代表調整真的有幫助</p><div class="grid g2" id="tuneh"></div>` : `<p class="note" style="margin-top:10px">每天的比較結果會一天天累積（目前 ${histDays.length} 天），滿 5 天後這裡會出現走勢圖。</p>`}
  </section>
  ${sections}
  ${dtSec}
  <p class="disclaimer">以上都是過去的成績，不保證未來。因為每天都算「之後 1 週、1 個月、3 個月」這類互相重疊的期間，真正獨立的樣本比天數少，數字會有誤差。另外，自我調整是用同一段歷史挑出最好的做法，所以這段歷史的成績會稍微好看一點。</p>`;
  const draw = () => {
    HZ.forEach((h, i) => {
      const c = MC[h], x = m.horizons[h];
      const box = $("#mc" + i); if (c && box) checkChart(box, c.series || [], [5, 20, 60][i]);
      calibChart($("#cal" + i), x.calib, x.base_hit);
      lineChart($("#ic" + i), (x.ic_roll || []).map((p) => p[0]), (x.ic_roll || []).map((p) => p[1]), { color: "var(--brass)", fmt: (v) => v.toFixed(2), zero: true, height: 150 });
    });
    if (DM && $("#dtcal")) {
      calibChart($("#dtcal"), (DM.calib || []).map((c) => c ? { n: c.n, up: c.win_long } : null), DM.base_win);
      lineChart($("#dtic"), (DM.ic_roll || []).map((p) => p[0]), (DM.ic_roll || []).map((p) => p[1]), { color: "var(--brass)", fmt: (v) => v.toFixed(2), zero: true, height: 150 });
    }
    const th = $("#tuneh");
    if (th) {
      th.innerHTML = ["short", "mid", "long", "dt"].map((p) => `<div><h3>${PART_NAME[p]}</h3><div class="chart" id="th_${p}"></div></div>`).join("");
      ["short", "mid", "long", "dt"].forEach((p) => tuneChart($("#th_" + p), hist.filter((x) => x.hn === p)));
    }
  };
  draw(); onResize(() => location.hash === "#/check" && draw());
}
function tuneChart(box, hs) {
  if (!box) return;
  if (hs.length < 2) { box.innerHTML = '<p class="note">累積中</p>'; return; }
  const W = Math.max(220, box.clientWidth), H = 120, PR = 40, PB = 18;
  const vals = hs.flatMap((x) => [x.score, x.fixed]).filter((v) => v != null);
  const lo = Math.min(0, ...vals), hi = Math.max(0.01, ...vals), pw = W - PR;
  const x = (i) => i / (hs.length - 1) * pw, y = (v) => 6 + (hi - v) / (hi - lo || 1) * (H - PB - 6);
  const line = (k, col, dash) => `<polyline fill="none" stroke="${col}" stroke-width="2" ${dash ? 'stroke-dasharray="4 3"' : ""} points="${hs.map((p, i) => p[k] == null ? "" : `${x(i).toFixed(1)},${y(p[k]).toFixed(1)}`).join(" ")}"/>`;
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><g class="axis grid"><line x1="0" x2="${pw}" y1="${y(0)}" y2="${y(0)}"/><text x="${W - 2}" y="${y(0) + 4}" text-anchor="end">0</text><text x="${W - 2}" y="${y(hi) + 8}" text-anchor="end">${hi.toFixed(2)}</text>
    <text x="0" y="${H - 3}">${dayStr(hs[0].day)}</text><text x="${pw}" y="${H - 3}" text-anchor="end">${dayStr(hs[hs.length - 1].day)}</text></g>
    ${line("fixed", "var(--muted)", true)}${line("score", "var(--brass)")}</svg>`;
}
const H_D = ["5 個交易日", "20 個交易日", "60 個交易日"];

// ====================================================================== 說明
async function vHelp(tok) {
  let st = S.status || {};
  try { st = await api("status", { fresh: true }); } catch { }
  if (tok !== routeToken) return;
  const lan = (st.lan || []).map((ip) => `http://${ip}:${st.port || 8787}`);
  view.innerHTML = `<h1>使用說明</h1>
  <div class="grid g2">
    <section class="card"><h2>分數怎麼看</h2>
      <p>每檔股票有三個分數，分別預測不同長度的未來：<b>短期＝1 週</b>（約 5 個交易日）、<b>中期＝1 個月</b>（約 20 個交易日）、<b>長期＝3 個月</b>（約 60 個交易日）。分數 0～100，50 分代表看不出方向。</p>
      <div class="bars" style="margin:10px 0">${[[85, "75 分以上：強烈看多"], [65, "60～75：偏多"], [50, "40～60：中立"], [33, "25～40：偏空"], [15, "25 分以下：強烈看空"]].map(([s, t]) => `<div class="b"><span>${pill(s)}</span><span>${t}</span><span></span></div>`).join("")}</div>
      <p>分數綜合約 35 項指標，分成五類：</p>
      <ul class="facts" style="margin:4px 0 10px">
        <li><span><b>股價走勢</b>：最近漲跌、有沒有站上平均價、量能變化。</span></li>
        <li><span><b>大戶動向</b>：外資、投信有沒有在買，散戶有沒有借錢追高。</span></li>
        <li><span><b>公司體質</b>：營收成長、賺錢能力、股價貴不貴。</span></li>
        <li><span><b>新聞消息</b>：最近的新聞和公司公告偏好消息還是壞消息。</span></li>
        <li><span><b>大盤與國外</b>：台股大盤氣氛，以及美股、台積電在美國的股價、匯率、美國利率。</span></li>
      </ul>
      <p><b>它會自己檢討：</b>每天收盤後，拿過去的分數和真正的漲跌對答案。最近常猜錯，就降低「可信度」、把分數調得保守；也會比較幾種計分做法，改用最準的那一種。結果都在「實測對答案」頁。</p>
    </section>
    ${st.static ? `<section class="card"><h2>雲端版（不用開電腦）</h2>
      <p>你現在看的是雲端版，資料每個交易日由雲端自動更新，電腦不用開。</p>
      <p>用手機瀏覽器打開這個網址，在選單點「加到主畫面」，就能像 App 一樣使用。這個網址不會被搜尋引擎收錄，請不要公開分享。</p>
      <h2 style="margin-top:18px">資料何時更新</h2>
      <p>每個交易日更新兩次：下午 3 點 40 分（收盤價、法人買賣、新聞）和晚上 9 點 50 分（融資融券）。更新完大約 10 分鐘內，網頁就會換成新資料。</p>
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
    <p>看漲買「認購」、看跌買「認售」。推薦度同時看兩件事：一是權證本身划不划算（價格貴不貴、買賣價差、剩幾天到期、每天耗損多少、槓桿大小），二是股票本身看漲還是看跌。表格每一欄旁邊的 <span class="help" style="cursor:default">?</span> 都有白話解釋。</p>
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
  const names = { collect: "下載最近 70 個交易日的股價、法人買賣、融資", snapshot: "下載公司營收獲利、權證、新聞與國外行情", engine: "分析：對答案、自我調整、算分數", backfill: "在背景補齊更早的歷史資料" };
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
