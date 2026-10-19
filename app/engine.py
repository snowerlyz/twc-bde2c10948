# -*- coding: utf-8 -*-
"""分析引擎：計算因子、用歷史實際走勢檢驗並調整權重、產生短中長期分數與說明。

核心想法（白話）：
1. 每天替每檔股票算出約 30 個「因子」（漲勢、均線、法人買賣、融資、營收、評價…）。
2. 拿過去每一天的因子，和「之後 5／20／60 個交易日的實際漲跌」比對，看哪些因子真的有預測力
   （排名相關係數，IC）。越近期的表現權重越高，資料少時向預設值收斂，避免被雜訊帶著走。
3. 用當天學到的權重把因子加總成綜合分數，換成全市場排名百分位。
4. 再看「過去分數落在同一區間的股票，後來實際漲跌如何」，換算成上漲機率與報酬區間。
每天有新行情進來，第 2～4 步都會重算，所以判斷會隨市場變化自動修正。
所有回測都是「當時只用當時已知資訊」（walk-forward），不偷看未來。
"""
import json
import math
import os
import time
from array import array

from util import DB, RESULTS, is_etf, is_stock_code, log, now_tw, read_json, write_json
from collector import part_path, month_path

NAN = float("nan")
H = {"short": 5, "mid": 20, "long": 60}
HN = ["short", "mid", "long"]
H_LABEL = {"short": "短期（約 1 週）", "mid": "中期（約 1 個月）", "long": "長期（約 3 個月）"}
HALF_LIFE = {"short": 40, "mid": 60, "long": 90}
CAL_WIN = {"short": 60, "mid": 80, "long": 100}
SHRINK_K = 20.0
MIN_VALUE = 5e6        # 20 日均成交金額低於 500 萬的股票不列入模型檢驗
ENGINE_VERSION = 5


def isnan(x):
    return x != x


def fmt_pct(x, d=1):
    return ("%+." + str(d) + "f%%") % (x * 100)


# ====================================================================== 因子定義
# key: (中文名稱, 類別, 預設權重[短, 中, 長])   預設權重以 IC 為單位，學到資料後會逐步取代
FACTORS = [
    ("mom5", "近一週漲跌", "技術", (-0.010, 0.000, 0.000)),
    ("mom20", "近一個月漲跌", "技術", (0.000, 0.010, 0.010)),
    ("mom60", "近一季漲跌", "技術", (0.010, 0.015, 0.020)),
    ("mom120", "近半年漲跌", "技術", (0.000, 0.010, 0.020)),
    ("ma20_gap", "與月線的距離", "技術", (0.005, 0.005, 0.000)),
    ("ma60_gap", "與季線的距離", "技術", (0.005, 0.010, 0.010)),
    ("ma_align", "均線排列", "技術", (0.010, 0.010, 0.010)),
    ("ma20_slope", "月線方向", "技術", (0.010, 0.010, 0.005)),
    ("rsi14", "RSI 強弱指標", "技術", (-0.005, 0.000, 0.000)),
    ("kd", "KD 指標", "技術", (-0.005, 0.000, 0.000)),
    ("macd", "MACD 動能", "技術", (0.005, 0.005, 0.000)),
    ("bb_pos", "布林通道位置", "技術", (-0.005, 0.000, 0.000)),
    ("vol_ratio", "成交量變化", "技術", (0.005, 0.000, -0.005)),
    ("volat20", "股價波動度", "技術", (-0.010, -0.010, -0.015)),
    ("high52", "距一年高點", "技術", (0.005, 0.010, 0.015)),
    ("liq", "成交金額規模", "技術", (0.000, 0.000, 0.005)),
    ("fi5", "外資近一週買賣超", "籌碼", (0.015, 0.010, 0.005)),
    ("fi20", "外資近一個月買賣超", "籌碼", (0.010, 0.015, 0.010)),
    ("it5", "投信近一週買賣超", "籌碼", (0.015, 0.015, 0.010)),
    ("it20", "投信近一個月買賣超", "籌碼", (0.010, 0.015, 0.015)),
    ("dl5", "自營商近一週買賣超", "籌碼", (0.005, 0.000, 0.000)),
    ("fi_streak", "外資連續買賣天數", "籌碼", (0.010, 0.005, 0.000)),
    ("it_streak", "投信連續買賣天數", "籌碼", (0.010, 0.010, 0.005)),
    ("mb5", "融資近一週增減", "籌碼", (-0.005, -0.005, 0.000)),
    ("mb20", "融資近一個月增減", "籌碼", (-0.005, -0.010, -0.010)),
    ("sb_ratio", "券資比", "籌碼", (0.003, 0.000, 0.000)),
    ("rev_yoy", "月營收年增率", "基本面", (0.005, 0.010, 0.020)),
    ("rev_cum", "累計營收年增率", "基本面", (0.000, 0.010, 0.020)),
    ("ey", "本益比（越低越便宜）", "基本面", (0.000, 0.005, 0.015)),
    ("bpy", "股價淨值比（越低越便宜）", "基本面", (0.000, 0.005, 0.010)),
    ("yld", "殖利率", "基本面", (0.000, 0.005, 0.010)),
    ("om", "營業利益率", "基本面", (0.000, 0.005, 0.010)),
]
FKEYS = [f[0] for f in FACTORS]
FNAME = {f[0]: f[1] for f in FACTORS}
FGROUP = {f[0]: f[2] for f in FACTORS}
FPRIOR = {f[0]: dict(zip(HN, f[3])) for f in FACTORS}
NF = len(FACTORS)


# ====================================================================== 數列工具

def first_valid(x):
    for i, v in enumerate(x):
        if not isnan(v):
            return i
    return len(x)


def sma(x, n):
    T = len(x)
    out = [NAN] * T
    s = 0.0
    q = []
    for t in range(T):
        v = x[t]
        if isnan(v):
            s, q = 0.0, []
            continue
        q.append(v)
        s += v
        if len(q) > n:
            s -= q.pop(0)
        if len(q) == n:
            out[t] = s / n
    return out


def ema(x, n):
    a = 2.0 / (n + 1)
    out = [NAN] * len(x)
    prev = None
    for t, v in enumerate(x):
        if isnan(v):
            continue
        prev = v if prev is None else prev + a * (v - prev)
        out[t] = prev
    return out


def rolling_std(x, n):
    T = len(x)
    out = [NAN] * T
    for t in range(n - 1, T):
        w = x[t - n + 1:t + 1]
        if any(isnan(v) for v in w):
            continue
        m = sum(w) / n
        out[t] = math.sqrt(sum((v - m) ** 2 for v in w) / (n - 1))
    return out


def rolling_sum(x, n):
    T = len(x)
    out = [NAN] * T
    for t in range(n - 1, T):
        w = x[t - n + 1:t + 1]
        if any(isnan(v) for v in w):
            continue
        out[t] = sum(w)
    return out


def rank_unit(vals):
    """vals: list of (value, idx)。回傳 {idx: 介於 -1..1 的排名}，同值取平均名次。"""
    n = len(vals)
    if n < 2:
        return {i: 0.0 for _, i in vals}
    vals.sort(key=lambda p: p[0])
    out = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and vals[j + 1][0] == vals[i][0]:
            j += 1
        r = (i + j) / 2.0
        u = r / (n - 1) * 2 - 1
        for k in range(i, j + 1):
            out[vals[k][1]] = u
        i = j + 1
    return out


def pearson(a, b):
    n = len(a)
    if n < 30:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    sab = saa = sbb = 0.0
    for x, y in zip(a, b):
        dx, dy = x - ma, y - mb
        sab += dx * dy
        saa += dx * dx
        sbb += dy * dy
    if saa <= 0 or sbb <= 0:
        return None
    return sab / math.sqrt(saa * sbb)


# ====================================================================== 載入資料

class Data:
    pass


def load_data(max_days=320):
    pdir = os.path.join(DB, "parts", "twse_px")
    days = sorted(f[:8] for f in os.listdir(pdir) if f.endswith(".json.gz")) if os.path.isdir(pdir) else []
    days = days[-max_days:]
    if len(days) < 25:
        raise RuntimeError("歷史資料不足（目前 %d 個交易日，至少需要 25 天）" % len(days))
    T = len(days)
    D = Data()
    D.days, D.T = days, T
    names, market = {}, {}
    raw = {}   # code -> dict of lists
    keys = ["o", "h", "l", "c", "v", "val", "ref", "fi", "it", "dl", "mb", "sb"]
    D.mkt = {k: [NAN] * T for k in ("taiex", "up", "down", "mtot")}
    D.fund_days = {}
    D.shares = {}

    def series(code):
        s = raw.get(code)
        if s is None:
            s = {k: [NAN] * T for k in keys}
            raw[code] = s
        return s

    for t, d in enumerate(days):
        for mk, part in (("上市", "twse_px"), ("上櫃", "tpex_px")):
            j = read_json(part_path(part, d))
            if not j:
                continue
            for code, nm in j.get("names", {}).items():
                names[code] = nm
                market[code] = mk
            for code, r in j["px"].items():
                if not is_stock_code(code):
                    continue
                s = series(code)
                o, h, l, c, v, val, ref = (r + [None] * 7)[:7]
                s["o"][t] = o if o is not None else NAN
                s["h"][t] = h if h is not None else NAN
                s["l"][t] = l if l is not None else NAN
                s["c"][t] = c if c is not None else NAN
                s["v"][t] = v or 0.0
                s["val"][t] = val or 0.0
                s["ref"][t] = ref if ref is not None else NAN
            if part == "twse_px":
                m = j.get("mkt", {})
                for k in ("taiex", "up", "down"):
                    if m.get(k) is not None:
                        D.mkt[k][t] = m[k]
            for code, sh in (j.get("shares") or {}).items():
                if sh:
                    D.shares[code] = sh
        for part in ("twse_ch", "tpex_ch"):
            j = read_json(part_path(part, d))
            if not j:
                continue
            for code, r in j["ch"].items():
                s = raw.get(code)
                if s is None:
                    continue
                s["fi"][t], s["it"][t], s["dl"][t] = r[0], r[1], r[2]
        for part in ("twse_mg", "tpex_mg"):
            j = read_json(part_path(part, d))
            if not j:
                continue
            for code, r in j["mg"].items():
                s = raw.get(code)
                if s is None:
                    continue
                s["mb"][t], s["sb"][t] = r[0], r[1]
            if part == "twse_mg" and j.get("total", {}).get("mb") is not None:
                D.mkt["mtot"][t] = j["total"]["mb"]
        fj = read_json(part_path("fund", d))
        if fj:
            D.fund_days[t] = fj

    # 只保留最新一天仍有交易資料的股票
    last_codes = set()
    for part in ("twse_px", "tpex_px"):
        j = read_json(part_path(part, days[-1])) or {}
        last_codes |= set(j.get("px", {}).keys())
    D.codes = sorted(c for c in raw if c in last_codes and first_valid(raw[c]["c"]) < T - 1)
    D.idx = {c: i for i, c in enumerate(D.codes)}
    D.raw = raw
    D.names, D.market = names, market
    D.industry = read_json(os.path.join(DB, "snapshot", "industry.json"), {}) or {}
    D.fund = read_json(os.path.join(DB, "snapshot", "fund.json"), {}) or {}
    D.fut = {}
    for t, d in enumerate(days):
        j = read_json(part_path("fut", d))
        if j:
            D.fut[t] = j["fut"]
    D.txf, D.pc = {}, {}
    for ym in sorted(set(d[:6] for d in days)):
        D.txf.update(read_json(month_path("txf_inst", ym), {}) or {})
        D.pc.update(read_json(month_path("pc", ym), {}) or {})
    return D


# ====================================================================== 個股序列與因子

def adjust_series(s):
    """用「收盤價 ÷ 參考價」串出不受除權息干擾的還原股價。"""
    c, ref = s["c"], s["ref"]
    T = len(c)
    level = [NAN] * T
    traded = [False] * T
    cur = None
    last_c = None
    for t in range(T):
        ct = c[t]
        if isnan(ct):
            level[t] = cur if cur is not None else NAN
            continue
        traded[t] = True
        if cur is None:
            cur = ct
        else:
            r = ref[t]
            ratio = None
            if not isnan(r) and r > 0:
                ratio = ct / r
            if ratio is None or not (0.5 < ratio < 2.0):
                ratio = ct / last_c if last_c else 1.0
            cur = cur * ratio
        last_c = ct
        level[t] = cur
    # 讓最新一天的還原價等於實際收盤價
    lv = level[T - 1]
    lc = last_c
    f = (lc / lv) if (lv and lc and not isnan(lv)) else 1.0
    A = [v * f if not isnan(v) else NAN for v in level]
    return A, traded


def stock_factors(s, A, traded, fund_days, code, T):
    """回傳 {因子: list(長度 T)}，資料不足處為 NaN。"""
    F = {}
    ret = [NAN] * T
    for t in range(1, T):
        if not isnan(A[t]) and not isnan(A[t - 1]) and A[t - 1] > 0:
            ret[t] = A[t] / A[t - 1] - 1

    def mom(n):
        out = [NAN] * T
        for t in range(n, T):
            a, b = A[t], A[t - n]
            if not isnan(a) and not isnan(b) and b > 0:
                out[t] = a / b - 1
        return out

    F["mom5"], F["mom20"], F["mom60"], F["mom120"] = mom(5), mom(20), mom(60), mom(120)
    ma5, ma10, ma20, ma60 = sma(A, 5), sma(A, 10), sma(A, 20), sma(A, 60)
    F["ma20_gap"] = [A[t] / ma20[t] - 1 if not isnan(ma20[t]) else NAN for t in range(T)]
    F["ma60_gap"] = [A[t] / ma60[t] - 1 if not isnan(ma60[t]) else NAN for t in range(T)]
    al = [NAN] * T
    for t in range(T):
        seq = (A[t], ma5[t], ma10[t], ma20[t], ma60[t])
        if any(isnan(v) for v in seq[:4]):
            continue
        if isnan(seq[4]):
            seq = seq[:4]
        sc = 0
        for i in range(len(seq) - 1):
            sc += 1 if seq[i] > seq[i + 1] else -1
        al[t] = sc
    F["ma_align"] = al
    F["ma20_slope"] = [ma20[t] / ma20[t - 5] - 1 if t >= 5 and not isnan(ma20[t]) and not isnan(ma20[t - 5]) else NAN
                       for t in range(T)]
    # RSI（Wilder）
    rsi = [NAN] * T
    ag = al_ = None
    for t in range(1, T):
        r = ret[t]
        if isnan(r):
            continue
        d = A[t] - A[t - 1]
        g, l = max(d, 0), max(-d, 0)
        if ag is None:
            ag, al_, cnt = g, l, 1
            continue
        ag = (ag * 13 + g) / 14
        al_ = (al_ * 13 + l) / 14
        cnt += 1
        if cnt >= 14:
            rsi[t] = 100.0 if al_ == 0 else 100 - 100 / (1 + ag / al_)
    F["rsi14"] = rsi
    # KD（9 日）
    fac = [A[t] / s["c"][t] if traded[t] and s["c"][t] else NAN for t in range(T)]
    hi = [s["h"][t] * fac[t] if traded[t] and not isnan(s["h"][t]) else A[t] for t in range(T)]
    lo = [s["l"][t] * fac[t] if traded[t] and not isnan(s["l"][t]) else A[t] for t in range(T)]
    kd = [NAN] * T
    k = 50.0
    for t in range(8, T):
        wh, wl = hi[t - 8:t + 1], lo[t - 8:t + 1]
        if any(isnan(v) for v in wh + wl) or isnan(A[t]):
            continue
        hh, ll = max(wh), min(wl)
        rsv = 50.0 if hh == ll else (A[t] - ll) / (hh - ll) * 100
        k = k * 2 / 3 + rsv / 3
        kd[t] = k
    F["kd"] = kd
    e12, e26 = ema(A, 12), ema(A, 26)
    dif = [e12[t] - e26[t] if not isnan(e26[t]) else NAN for t in range(T)]
    sig = ema(dif, 9)
    F["macd"] = [(dif[t] - sig[t]) / A[t] if not isnan(sig[t]) and A[t] else NAN for t in range(T)]
    sd20 = rolling_std(A, 20)
    F["bb_pos"] = [(A[t] - ma20[t]) / (2 * sd20[t]) if not isnan(sd20[t]) and sd20[t] > 0 else NAN for t in range(T)]
    v = s["v"]
    v5, v20 = sma(v, 5), sma(v, 20)
    F["vol_ratio"] = [math.log((v5[t] + 1) / (v20[t] + 1)) if not isnan(v20[t]) else NAN for t in range(T)]
    F["volat20"] = rolling_std(ret, 20)
    high = [NAN] * T
    for t in range(T):
        lo_i = max(0, t - 249)
        w = [x for x in A[lo_i:t + 1] if not isnan(x)]
        if len(w) >= 60:
            high[t] = A[t] / max(w) - 1
    F["high52"] = high
    val20 = sma(s["val"], 20)
    F["liq"] = [math.log10(val20[t] + 1) if not isnan(val20[t]) else NAN for t in range(T)]
    # 籌碼：以 20 日均量（股）標準化
    def chip_sum(x, n):
        rs = rolling_sum(x, n)
        return [rs[t] / v20[t] if not isnan(rs[t]) and not isnan(v20[t]) and v20[t] > 0 else NAN for t in range(T)]
    F["fi5"], F["fi20"] = chip_sum(s["fi"], 5), chip_sum(s["fi"], 20)
    F["it5"], F["it20"] = chip_sum(s["it"], 5), chip_sum(s["it"], 20)
    F["dl5"] = chip_sum(s["dl"], 5)

    def streak(x):
        out = [NAN] * T
        cur = 0
        for t in range(T):
            if isnan(x[t]):
                cur = 0
                continue
            if x[t] > 0:
                cur = cur + 1 if cur > 0 else 1
            elif x[t] < 0:
                cur = cur - 1 if cur < 0 else -1
            else:
                cur = 0
            out[t] = max(-20, min(20, cur))
        return out
    F["fi_streak"], F["it_streak"] = streak(s["fi"]), streak(s["it"])
    mb, sb = s["mb"], s["sb"]

    def mchg(n):
        out = [NAN] * T
        for t in range(n, T):
            if isnan(mb[t]) or isnan(mb[t - n]) or isnan(v20[t]):
                continue
            out[t] = (mb[t] - mb[t - n]) / (v20[t] / 1000.0 + 1)
        return out
    F["mb5"], F["mb20"] = mchg(5), mchg(20)
    F["sb_ratio"] = [sb[t] / mb[t] if not isnan(mb[t]) and mb[t] > 0 and not isnan(sb[t]) else NAN for t in range(T)]
    # 基本面：只有在有每日快照的日子才有值
    for k in ("rev_yoy", "rev_cum", "ey", "bpy", "yld", "om"):
        F[k] = [NAN] * T
    for t, fj in fund_days.items():
        f = fj.get(code)
        if not f:
            continue
        F["rev_yoy"][t] = _clip(f.get("rev_yoy"), -100, 300)
        F["rev_cum"][t] = _clip(f.get("rev_cum_yoy"), -100, 300)
        pe = f.get("pe")
        F["ey"][t] = 1.0 / pe if pe and pe > 0 else NAN
        pb = f.get("pb")
        F["bpy"][t] = 1.0 / pb if pb and pb > 0 else NAN
        F["yld"][t] = f.get("yld") if f.get("yld") is not None else NAN
        F["om"][t] = _clip(f.get("om"), -100, 100)
    return F, ret, val20, ma5, ma20, ma60


def _clip(v, lo, hi):
    if v is None:
        return NAN
    return max(lo, min(hi, v))


# ====================================================================== 大盤模型

MKT_FACTORS = [
    ("m_mom5", "加權指數近一週漲跌", (-0.05, 0.00, 0.00)),
    ("m_mom20", "加權指數近一個月漲跌", (0.00, 0.08, 0.05)),
    ("m_ma20", "指數與月線距離", (0.05, 0.05, 0.00)),
    ("m_ma60", "指數與季線距離", (0.05, 0.08, 0.08)),
    ("m_breadth", "上漲家數比例（5 日）", (0.05, 0.05, 0.03)),
    ("m_fi5", "外資現貨買賣超（5 日）", (0.10, 0.08, 0.05)),
    ("m_marg5", "融資餘額變化（5 日）", (-0.05, -0.05, -0.05)),
    ("m_basis", "台指期正逆價差", (0.05, 0.03, 0.00)),
    ("m_foi", "外資台指期留倉", (0.05, 0.05, 0.03)),
    ("m_foi5", "外資台指期留倉變化（5 日）", (0.10, 0.05, 0.00)),
    ("m_pc", "選擇權買賣權未平倉比", (0.05, 0.05, 0.00)),
]


def front_month(recs):
    """同一商品多個月份中取成交量最大的（近月）。"""
    best = None
    for r in recs:
        if best is None or (r[5] or 0) > (best[5] or 0):
            best = r
    return best


def market_model(D, stock_close, stock_fi):
    T = D.T
    tx = D.mkt["taiex"]
    # 補空值
    for t in range(1, T):
        if isnan(tx[t]):
            tx[t] = tx[t - 1]
    raw = {k: [NAN] * T for k, _, _ in MKT_FACTORS}
    ma20, ma60 = sma(tx, 20), sma(tx, 60)
    br = [D.mkt["up"][t] / (D.mkt["up"][t] + D.mkt["down"][t])
          if not isnan(D.mkt["up"][t]) and not isnan(D.mkt["down"][t]) and (D.mkt["up"][t] + D.mkt["down"][t]) > 0 else NAN
          for t in range(T)]
    br5 = sma(br, 5)
    fi_amt = [NAN] * T
    tot_val = [NAN] * T
    for t in range(T):
        s_fi = s_val = 0.0
        n = 0
        for code, (cl, val) in stock_close.items():
            f = stock_fi[code][t]
            c = cl[t]
            if not isnan(f) and not isnan(c):
                s_fi += f * c
                n += 1
            if not isnan(val[t]):
                s_val += val[t]
        if n > 100:
            fi_amt[t] = s_fi
        tot_val[t] = s_val
    fi5 = rolling_sum(fi_amt, 5)
    tv20 = sma(tot_val, 20)
    mt = D.mkt["mtot"]
    txc = [NAN] * T
    oi_tot = [NAN] * T
    for t in range(T):
        recs = (D.fut.get(t) or {}).get("TX")
        if recs:
            fm = front_month(recs)
            txc[t] = fm[4] if fm[4] is not None else NAN
            oi_tot[t] = sum((r[7] or 0) for r in recs)
    foi = [NAN] * T
    pcr = [NAN] * T
    for t, d in enumerate(D.days):
        x = D.txf.get(d, {}).get("foreign")
        if x:
            foi[t] = x[1]
        p = D.pc.get(d)
        if p and p[5] is not None:
            pcr[t] = p[5]
    for t in range(T):
        if t >= 5 and not isnan(tx[t - 5]):
            raw["m_mom5"][t] = tx[t] / tx[t - 5] - 1
        if t >= 20 and not isnan(tx[t - 20]):
            raw["m_mom20"][t] = tx[t] / tx[t - 20] - 1
        if not isnan(ma20[t]):
            raw["m_ma20"][t] = tx[t] / ma20[t] - 1
        if not isnan(ma60[t]):
            raw["m_ma60"][t] = tx[t] / ma60[t] - 1
        raw["m_breadth"][t] = br5[t]
        if not isnan(fi5[t]) and not isnan(tv20[t]) and tv20[t] > 0:
            raw["m_fi5"][t] = fi5[t] / tv20[t]
        if t >= 5 and not isnan(mt[t]) and not isnan(mt[t - 5]) and mt[t - 5] > 0:
            raw["m_marg5"][t] = mt[t] / mt[t - 5] - 1
        if not isnan(txc[t]) and not isnan(tx[t]):
            raw["m_basis"][t] = txc[t] / tx[t] - 1
        raw["m_foi"][t] = foi[t]
        if t >= 5 and not isnan(foi[t]) and not isnan(foi[t - 5]):
            raw["m_foi5"][t] = foi[t] - foi[t - 5]
        raw["m_pc"][t] = pcr[t]
    # 時間序列 z 分數（相對自己過去 120 天）
    Z = {}
    for k in raw:
        x = raw[k]
        z = [NAN] * T
        for t in range(T):
            if isnan(x[t]):
                continue
            w = [v for v in x[max(0, t - 120):t] if not isnan(v)]
            if len(w) < 20:
                continue
            m = sum(w) / len(w)
            sd = math.sqrt(sum((v - m) ** 2 for v in w) / (len(w) - 1))
            if sd > 0:
                z[t] = max(-3, min(3, (x[t] - m) / sd))
        Z[k] = z
    out = {"horizons": {}, "raw": {}, "series": {}}
    last = T - 1
    for hn in HN:
        h = H[hn]
        weights = {}
        for k, name, pri in MKT_FACTORS:
            prior = dict(zip(HN, pri))[hn]
            xs, ys = [], []
            for t in range(T - h):
                if not isnan(Z[k][t]) and not isnan(tx[t + h]):
                    xs.append(Z[k][t])
                    ys.append(tx[t + h] / tx[t] - 1)
            c = pearson(xs, ys) if len(xs) >= 40 else None
            n_info = len(xs) / max(1.0, h / 5.0)
            K = 150.0
            w = prior if c is None else (n_info / (n_info + K)) * c + (K / (n_info + K)) * prior
            weights[k] = w
        sw = sum(abs(w) for w in weights.values()) or 1.0
        comp = [NAN] * T
        for t in range(T):
            tot = 0.0
            used = 0
            for k in weights:
                z = Z[k][t]
                if not isnan(z):
                    tot += weights[k] * z
                    used += 1
            if used >= 4:
                comp[t] = tot / sw * 1.5
        cl = comp[last] if not isnan(comp[last]) else 0.0
        # 分數＝今天的讀數在過去一年裡排第幾（百分位），換算到 15～85 分。
        # 用排名而不是絕對值，避免幾個指標同時極端時分數被推到 10 分以下。
        past = [c for c in comp[:last] if not isnan(c)]
        if len(past) >= 20:
            below = sum(1 for c in past if c < cl) + 0.5 * sum(1 for c in past if c == cl)
            pct = below / len(past)
        else:
            pct = 0.5 + 0.5 * math.tanh(cl)
        score = 50 + (pct - 0.5) * 70
        # 過去類似讀數之後的實際表現
        sims = [(comp[t], tx[t + h] / tx[t] - 1) for t in range(T - h) if not isnan(comp[t])]
        near = sorted(sims, key=lambda p: abs(p[0] - cl))[:max(15, len(sims) // 4)]
        up = sum(1 for _, r in near if r > 0)
        # 再用「過去類似讀數之後大盤實際漲跌」校正，讓分數與歷史結果一致（樣本少時向 50% 收斂）
        if near:
            up_s = (up + 2.5) / (len(near) + 5)
            score = 0.6 * score + 0.4 * up_s * 100
        contrib = sorted(((weights[k] * Z[k][last], k) for k in weights if not isnan(Z[k][last])), reverse=True)
        out["horizons"][hn] = {
            "score": round(score, 1),
            "label": label_of(score),
            "pct": round(pct, 3),
            "similar_n": len(near), "similar_up": up,
            "similar_avg": round(sum(r for _, r in near) / len(near) * 100, 2) if near else None,
            "pos": [MKT_NAME[k] for c_, k in contrib[:3] if c_ > 0.05],
            "neg": [MKT_NAME[k] for c_, k in contrib[::-1][:3] if c_ < -0.05],
            "weights": {k: round(w, 4) for k, w in weights.items()},
        }
    out["raw"] = {k: (None if isnan(raw[k][last]) else raw[k][last]) for k in raw}
    n = min(T, 120)
    out["series"] = {
        "days": D.days[-n:],
        "taiex": _r(tx[-n:], 2),
        "tx": _r(txc[-n:], 0),
        "foi": _r(foi[-n:], 0),
        "pc": _r(pcr[-n:], 2),
        "breadth": _r(br[-n:], 3),
        "oi": _r(oi_tot[-n:], 0),
    }
    out["taiex"] = tx[last]
    out["taiex_chg"] = tx[last] / tx[last - 1] - 1 if T > 1 and not isnan(tx[last - 1]) else None
    out["tx_close"] = None if isnan(txc[last]) else txc[last]
    out["foi"] = None if isnan(foi[last]) else foi[last]
    out["foi5"] = out["raw"].get("m_foi5")
    out["pc"] = None if isnan(pcr[last]) else pcr[last]
    out["basis"] = out["raw"].get("m_basis")
    out["breadth"] = None if isnan(br[last]) else br[last]
    out["up"] = D.mkt["up"][last]
    out["down"] = D.mkt["down"][last]
    return out


MKT_NAME = {k: n for k, n, _ in MKT_FACTORS}


def _r(xs, d):
    return [None if (x is None or isnan(x)) else round(x, d) for x in xs]


def label_of(score):
    if score >= 75:
        return "強烈看多"
    if score >= 60:
        return "偏多"
    if score > 40:
        return "中立"
    if score > 25:
        return "偏空"
    return "強烈看空"


# ====================================================================== 說明文字

def reason_text(k, v, sign):
    """把因子數值翻成白話。sign>0 代表對分數加分。"""
    if v is None or isnan(v):
        return None
    if k.startswith("mom"):
        n = {"mom5": "近一週", "mom20": "近一個月", "mom60": "近一季", "mom120": "近半年"}[k]
        return "%s%s %.1f%%" % (n, "上漲" if v >= 0 else "下跌", abs(v) * 100)
    if k == "ma20_gap":
        return "股價%s月線 %.1f%%" % ("高於" if v >= 0 else "低於", abs(v) * 100)
    if k == "ma60_gap":
        return "股價%s季線 %.1f%%" % ("高於" if v >= 0 else "低於", abs(v) * 100)
    if k == "ma_align":
        if v >= 3:
            return "均線多頭排列（短中長期均線由上而下依序排開）"
        if v <= -3:
            return "均線空頭排列"
        return "均線糾結、方向不明" if abs(v) <= 1 else ("均線偏多" if v > 0 else "均線偏空")
    if k == "ma20_slope":
        return "月線%s" % ("向上" if v > 0 else "向下")
    if k == "rsi14":
        if v >= 70:
            return "RSI %.0f，短線偏熱" % v
        if v <= 30:
            return "RSI %.0f，短線超賣" % v
        return "RSI %.0f" % v
    if k == "kd":
        if v >= 80:
            return "KD %.0f，位在高檔" % v
        if v <= 20:
            return "KD %.0f，位在低檔" % v
        return "KD %.0f" % v
    if k == "macd":
        return "MACD 動能%s" % ("轉強" if v > 0 else "轉弱")
    if k == "bb_pos":
        if v > 0.9:
            return "股價貼近布林通道上緣"
        if v < -0.9:
            return "股價貼近布林通道下緣"
        return "股價位於布林通道%s半部" % ("上" if v > 0 else "下")
    if k == "vol_ratio":
        return "成交量較平常%s %.0f%%" % ("放大" if v > 0 else "萎縮", abs(math.exp(v) - 1) * 100)
    if k == "volat20":
        return "近一個月每日波動約 %.1f%%（%s）" % (v * 100, "偏大" if v > 0.03 else "穩定")
    if k == "high52":
        return "距離一年高點 %.1f%%" % (v * 100) if v < -0.005 else "創一年新高"
    if k == "liq":
        return "日均成交約 %.1f 億元" % (10 ** v / 1e8)
    if k in ("fi5", "fi20", "it5", "it20", "dl5"):
        who = {"fi": "外資", "it": "投信", "dl": "自營商"}[k[:2]]
        per = "近一週" if k.endswith("5") else "近一個月"
        a = abs(v)
        size = ("相當於 %.1f 天的成交量" % a) if a >= 1 else ("約平日成交量的 %.0f%%" % (a * 100))
        return "%s%s%s（%s）" % (who, per, "買超" if v > 0 else "賣超", size)
    if k in ("fi_streak", "it_streak"):
        who = "外資" if k.startswith("fi") else "投信"
        if v == 0:
            return None
        return "%s連續 %d 天%s" % (who, abs(v), "買超" if v > 0 else "賣超")
    if k in ("mb5", "mb20"):
        per = "近一週" if k == "mb5" else "近一個月"
        return "融資%s%s（散戶槓桿%s）" % (per, "增加" if v > 0 else "減少", "升溫" if v > 0 else "降溫")
    if k == "sb_ratio":
        return "券資比 %.1f%%" % (v * 100)
    if k == "rev_yoy":
        return "最新月營收年%s %.1f%%" % ("增" if v >= 0 else "減", abs(v))
    if k == "rev_cum":
        return "今年累計營收年%s %.1f%%" % ("增" if v >= 0 else "減", abs(v))
    if k == "ey":
        return "本益比 %.1f 倍" % (1 / v) if v > 0 else None
    if k == "bpy":
        return "股價淨值比 %.2f 倍" % (1 / v) if v > 0 else None
    if k == "yld":
        return "殖利率 %.2f%%" % v
    if k == "om":
        return "營業利益率 %.1f%%" % v
    return None


# ====================================================================== 主計算

def run_engine(prog=None):
    t0 = time.time()

    def say(msg, done=None, total=None):
        log("引擎：" + msg)
        if prog:
            kw = {"phase": "engine", "msg": msg}
            if done is not None:
                kw.update(done=done, total=total)
            prog.set(**kw)

    say("載入歷史資料")
    D = load_data()
    T, codes = D.T, D.codes
    N = len(codes)
    say("計算 %d 檔股票、%d 個交易日的因子" % (N, T), 0, N)

    FA = {k: [None] * N for k in FKEYS}      # 每個因子：每檔股票一個 array('f')
    A_all, traded_all, val20_all, ret_all = [None] * N, [None] * N, [None] * N, [None] * N
    ma_all = [None] * N
    stock_close, stock_fi = {}, {}
    for i, code in enumerate(codes):
        s = D.raw[code]
        A, traded = adjust_series(s)
        F, ret, val20, ma5, ma20, ma60 = stock_factors(s, A, traded, D.fund_days, code, T)
        for k in FKEYS:
            FA[k][i] = array("f", F[k])
        A_all[i] = array("d", A)
        traded_all[i] = traded
        val20_all[i] = array("d", val20)
        ma_all[i] = (ma5, ma20, ma60)
        stock_close[code] = (s["c"], s["val"])
        stock_fi[code] = s["fi"]
        if i % 200 == 0:
            say("計算因子 %d/%d" % (i, N), i, N)

    say("大盤模型")
    mkt = market_model(D, stock_close, stock_fi)

    # ---- 逐日（由舊到新）：排名 → IC → 權重 → 綜合分數
    say("用歷史走勢檢驗因子並調整權重", 0, T)
    ic_hist = {hn: {k: [] for k in FKEYS} for hn in HN}   # (t, ic)
    comp_ic = {hn: [] for hn in HN}
    pct_hist = {hn: {} for hn in HN}                        # t -> list(pct) (只存需要的日子)
    weights_hist = {hn: [] for hn in HN}
    keep_from = max(0, T - 160)
    last_R = None
    last_w = None
    for t in range(T):
        # 有效股票（當天有價）
        alive = [i for i in range(N) if not isnan(A_all[i][t]) and traded_all[i][t]]
        liquid = set(i for i in alive if not isnan(val20_all[i][t]) and val20_all[i][t] >= MIN_VALUE)
        R = {}
        for k in FKEYS:
            col = FA[k]
            vals = []
            for i in alive:
                v = col[i][t]
                if v == v:
                    vals.append((v, i))
            R[k] = rank_unit(vals) if len(vals) >= 50 else {}
        # 未來報酬
        fwd = {}
        for hn in HN:
            h = H[hn]
            if t + h < T:
                fr = []
                for i in liquid:
                    a0, a1 = A_all[i][t], A_all[i][t + h]
                    if a1 == a1 and a0 > 0:
                        fr.append((a1 / a0 - 1, i))
                if len(fr) >= 50:
                    fwd[hn] = (dict((i, r) for r, i in fr), rank_unit(list(fr)))
        # IC（這一天的因子 vs 之後實際報酬）
        for hn, (fr, frr) in fwd.items():
            for k in FKEYS:
                rk = R[k]
                if not rk:
                    continue
                xs, ys = [], []
                for i, y in frr.items():
                    x = rk.get(i)
                    if x is not None:
                        xs.append(x)
                        ys.append(y)
                c = pearson(xs, ys) if len(xs) >= 100 else None
                if c is not None:
                    ic_hist[hn][k].append((t, c))
        # 今天可用的權重：只用「結果已經揭曉」的 IC（t' + h <= t）
        W = {}
        for hn in HN:
            h = H[hn]
            W[hn] = learned_weights(ic_hist[hn], t - h, hn)
            weights_hist[hn].append(W[hn])
        # 綜合分數 → 百分位
        if t >= keep_from or t == T - 1:
            for hn in HN:
                w = W[hn]
                comp = []
                for i in alive:
                    sc = 0.0
                    for k in FKEYS:
                        r = R[k].get(i)
                        if r is not None:
                            sc += w[k] * r
                    comp.append((sc, i))
                pr = rank_unit(comp)
                pct = {i: (u + 1) / 2 for i, u in pr.items()}
                pct_hist[hn][t] = pct
                if hn in fwd:
                    fr, frr = fwd[hn]
                    xs, ys = [], []
                    for i, y in frr.items():
                        if i in pct:
                            xs.append(pct[i])
                            ys.append(y)
                    c = pearson(xs, ys)
                    if c is not None:
                        comp_ic[hn].append((t, c))
        if t == T - 1:
            last_R, last_w = R, W
        if t % 20 == 0:
            say("模型回測 %d/%d 天" % (t, T), t, T)

    say("整理結果")
    last = T - 1
    results = build_outputs(D, FA, A_all, traded_all, val20_all, ma_all, last_R, last_w,
                            pct_hist, ic_hist, comp_ic, weights_hist, mkt)
    results["FA"] = FA
    say("完成，耗時 %.0f 秒" % (time.time() - t0))
    return results, D, A_all


def learned_weights(ic_list_by_f, upto, hn):
    """以指數加權平均 IC 估計每個因子的預測力，資料少時向預設權重收斂。"""
    hl = HALF_LIFE[hn]
    lam = 0.5 ** (1.0 / hl)
    h = H[hn]
    W = {}
    for k in FKEYS:
        prior = FPRIOR[k][hn]
        lst = ic_list_by_f[k]
        sw = s = 0.0
        n = 0
        for tt, c in reversed(lst):
            if tt > upto:
                continue
            age = upto - tt
            if age > 250:
                break
            wt = lam ** age
            sw += wt
            s += wt * c
            n += 1
        if n == 0 or sw == 0:
            W[k] = prior
            continue
        mean = s / sw
        n_info = sw / max(1.0, h / 5.0)
        W[k] = (n_info / (n_info + SHRINK_K)) * mean + (SHRINK_K / (n_info + SHRINK_K)) * prior
    return W


def calibrate(pct_hist, A_all, liquid_fn, hn, T):
    """過去分數落在各區間的股票，h 天後實際表現。回傳 10 個區間的統計。"""
    h = H[hn]
    win = CAL_WIN[hn]
    end = T - 1 - h
    start = max(0, end - win + 1)
    bins = [[] for _ in range(10)]
    for t in range(start, end + 1):
        pct = pct_hist.get(t)
        if not pct:
            continue
        for i, p in pct.items():
            if not liquid_fn(i, t):
                continue
            a0, a1 = A_all[i][t], A_all[i][t + h]
            if a1 == a1 and a0 > 0:
                bins[min(9, int(p * 10))].append(a1 / a0 - 1)
    out = []
    for b in bins:
        if len(b) < 20:
            out.append(None)
            continue
        b.sort()
        n = len(b)
        out.append({
            "n": n,
            "up": sum(1 for r in b if r > 0) / n,
            "avg": sum(b) / n,
            "p20": b[int(n * 0.2)],
            "p50": b[n // 2],
            "p80": b[min(n - 1, int(n * 0.8))],
        })
    # 平滑：與相鄰區間平均，降低雜訊
    sm = []
    for j in range(10):
        group = [out[x] for x in (j - 1, j, j + 1) if 0 <= x < 10 and out[x]]
        if not out[j] or not group:
            sm.append(out[j])
            continue
        wts = [2 if g is out[j] else 1 for g in group]
        tw = sum(wts)
        sm.append({k: (sum(g[k] * w for g, w in zip(group, wts)) / tw if k != "n" else out[j]["n"])
                   for k in out[j]})
    return sm


def build_outputs(D, FA, A_all, traded_all, val20_all, ma_all, R, W, pct_hist, ic_hist, comp_ic,
                  weights_hist, mkt):
    T, codes, N = D.T, D.codes, len(D.codes)
    last = T - 1

    def liquid(i, t):
        v = val20_all[i][t]
        return v == v and v >= MIN_VALUE

    calib = {hn: calibrate(pct_hist[hn], A_all, liquid, hn, T) for hn in HN}

    # ---- 模型成績單（walk-forward）
    model = {"horizons": {}, "version": ENGINE_VERSION, "days": T,
             "first_day": D.days[0], "last_day": D.days[-1]}
    for hn in HN:
        h = H[hn]
        top_up = top_n = all_up = all_n = 0
        spreads = []
        for t, pct in pct_hist[hn].items():
            if t + h > last:
                continue
            tops, bots = [], []
            for i, p in pct.items():
                if not liquid(i, t):
                    continue
                a0, a1 = A_all[i][t], A_all[i][t + h]
                if not (a1 == a1 and a0 > 0):
                    continue
                r = a1 / a0 - 1
                all_n += 1
                all_up += r > 0
                if p >= 0.8:
                    tops.append(r)
                    top_n += 1
                    top_up += r > 0
                elif p <= 0.2:
                    bots.append(r)
            if tops and bots:
                spreads.append((t, sum(tops) / len(tops) - sum(bots) / len(bots)))
        ics = comp_ic[hn]
        roll = []
        for j in range(len(ics)):
            w = [c for _, c in ics[max(0, j - 19):j + 1]]
            roll.append([D.days[ics[j][0]], round(sum(w) / len(w), 4)])
        wl = W[hn]
        fac = []
        for k in FKEYS:
            lst = [c for tt, c in ic_hist[hn][k] if tt <= last - h]
            fac.append({"k": k, "name": FNAME[k], "group": FGROUP[k], "w": round(wl[k], 4),
                        "prior": FPRIOR[k][hn], "n": len(lst),
                        "ic": round(sum(lst[-60:]) / len(lst[-60:]), 4) if lst else None})
        fac.sort(key=lambda x: -abs(x["w"]))
        # 權重變化（最近 60 天）
        wh = weights_hist[hn][-60:]
        model["horizons"][hn] = {
            "label": H_LABEL[hn], "h": h,
            "eval_days": len(spreads),
            "top_hit": round(top_up / top_n, 4) if top_n else None,
            "base_hit": round(all_up / all_n, 4) if all_n else None,
            "spread_avg": round(sum(s for _, s in spreads) / len(spreads), 5) if spreads else None,
            "spread_win": round(sum(1 for _, s in spreads if s > 0) / len(spreads), 4) if spreads else None,
            "ic_roll": roll[-120:],
            "ic_avg": round(sum(c for _, c in ics) / len(ics), 4) if ics else None,
            "factors": fac,
            "calib": [None if c is None else {k: round(v, 4) for k, v in c.items()} for c in calib[hn]],
            "weight_trend": {k: [round(w[k], 4) for w in wh] for k in [f["k"] for f in fac[:8]]},
        }

    # ---- 個股結果
    stocks = []
    details = {}
    for i, code in enumerate(codes):
        s = D.raw[code]
        c_last = s["c"][last]
        if isnan(c_last):
            # 今天沒成交，用最近收盤
            c_last = next((s["c"][t] for t in range(last, -1, -1) if not isnan(s["c"][t])), NAN)
        ref = s["ref"][last]
        chg = (c_last / ref - 1) if (not isnan(ref) and ref > 0 and traded_all[i][last]) else 0.0
        hz = {}
        for hn in HN:
            pct = pct_hist[hn].get(last, {}).get(i)
            if pct is None:
                hz[hn] = None
                continue
            m_score = mkt["horizons"][hn]["score"]
            final = 0.75 * pct * 100 + 0.25 * m_score
            cb = calib[hn]
            b = min(9, int(pct * 10))
            cal = cb[b] if cb[b] else None
            # 說明：貢獻最大的因子
            contrib = []
            for k in FKEYS:
                r = R[k].get(i)
                if r is None:
                    continue
                contrib.append((W[hn][k] * r, k))
            contrib.sort(reverse=True)
            pos, neg = [], []
            for cval, k in contrib:
                if cval <= 0.0005 or len(pos) >= 4:
                    break
                txt = reason_text(k, FA[k][i][last], 1)
                if txt:
                    pos.append(txt)
            for cval, k in reversed(contrib):
                if cval >= -0.0005 or len(neg) >= 3:
                    break
                txt = reason_text(k, FA[k][i][last], -1)
                if txt:
                    neg.append(txt)
            hz[hn] = {
                "score": round(final, 1), "pct": round(pct, 4), "label": label_of(final),
                "up": round(cal["up"], 3) if cal else None,
                "avg": round(cal["avg"], 4) if cal else None,
                "lo": round(cal["p20"], 4) if cal else None,
                "hi": round(cal["p80"], 4) if cal else None,
                "n": cal["n"] if cal else 0,
                "pos": pos, "neg": neg,
            }
        val20 = val20_all[i][last]
        ind = D.industry.get(code) or ("ETF" if is_etf(code) else "")
        row = {
            "c": code, "n": D.names.get(code, code), "m": D.market.get(code, ""), "ind": ind,
            "px": None if isnan(c_last) else c_last, "chg": round(chg, 4),
            "val": None if isnan(val20) else round(val20 / 1e8, 2),
            "s": [hz[hn]["score"] if hz[hn] else None for hn in HN],
            "etf": is_etf(code),
        }
        stocks.append(row)
        details[code] = (i, hz)

    # ---- 產業強弱
    inds = {}
    for r in stocks:
        if r["ind"] and r["s"][1] is not None and r["val"] and r["val"] >= 0.05:
            inds.setdefault(r["ind"], []).append(r)
    industries = []
    for k, rs in inds.items():
        if len(rs) < 3:
            continue
        industries.append({"ind": k, "n": len(rs),
                           "s": [round(sum(r["s"][j] for r in rs if r["s"][j] is not None) / len(rs), 1) for j in range(3)],
                           "chg": round(sum(r["chg"] for r in rs) / len(rs), 4)})
    industries.sort(key=lambda x: -x["s"][1])

    return {"stocks": stocks, "details": details, "model": model, "market": mkt,
            "industries": industries, "calib": calib, "R": R, "W": W}


def stock_detail(code, i, hz, D, FA, A_all, n_hist=250):
    s = D.raw[code]
    T = D.T
    lo = max(0, T - n_hist)
    hist = []
    for t in range(lo, T):
        c = s["c"][t]
        if isnan(c):
            continue
        hist.append([D.days[t], _n(s["o"][t]), _n(s["h"][t]), _n(s["l"][t]), c, round(s["v"][t] / 1000)])
    chips = []
    for t in range(max(0, T - 60), T):
        chips.append([D.days[t], _n(s["fi"][t], 1000), _n(s["it"][t], 1000), _n(s["dl"][t], 1000),
                      _n(s["mb"][t]), _n(s["sb"][t])])
    factors = {}
    for k in FKEYS:
        v = FA[k][i][T - 1]
        factors[k] = None if isnan(v) else round(float(v), 5)
    return {
        "c": code, "n": D.names.get(code, code), "m": D.market.get(code, ""),
        "ind": D.industry.get(code) or ("ETF" if is_etf(code) else ""),
        "day": D.days[-1], "hist": hist, "chips": chips, "factors": factors,
        "fname": FNAME, "fgroup": FGROUP, "h": hz, "fund": D.fund.get(code, {}),
        "shares": D.shares.get(code),
    }


def _n(v, div=None):
    if v is None or isnan(v):
        return None
    if div:
        return round(v / div)
    return v
