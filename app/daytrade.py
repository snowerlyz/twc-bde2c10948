# -*- coding: utf-8 -*-
"""當沖模型：用今天收盤後的資料，評估「下一個交易日開盤買進（或賣出）、收盤前出場」的勝算。

做法與主模型相同、但目標換成「隔天開盤到收盤的漲跌」：
1. 每天替每檔股票算約 17 個短線因子（今天的 K 棒型態、量能、振幅、法人當日買賣…）。
2. 拿過去每一天的因子，對照「隔天開盤→收盤」實際漲跌，計算預測力（IC）。
   當沖的市場特性變化快，所以用 30 天半衰期，近期表現權重更高，每天自動更新。
3. 用當天可用的權重算綜合分數→排名百分位；再看過去同分數區間的股票隔天實際表現，
   換算「扣除成本後的勝率」、平均報酬、停利停損參考。
全程只用當時已知的資料（walk-forward），不偷看未來。
"""
import math

import os

from util import DB, is_etf, read_json, write_json

NAN = float("nan")
# 來回成本：手續費 0.1425% × 2 × 6 折 ＋ 當沖證交稅 0.15%
COST = 0.001425 * 2 * 0.6 + 0.0015
DT_MIN_VALUE = 1e8      # 20 日均成交金額至少 1 億，才有足夠流動性當沖
DT_MIN_PRICE = 10.0
HALF_LIFE = 30
SHRINK_DEFAULT = 15.0
TUNE_PATH = os.path.join(DB, "tuning.json")
DT_CANDS = [{"hl": hl, "sk": sk, "name": "%s跟著最近表現改（%s）" % ({10: "很快", 30: "較快", 90: "中等速度"}[hl], {5: "改得多", 15: "改得少"}[sk])}
            for hl in (10, 30, 90) for sk in (5, 15)] + \
           [{"hl": 60, "sk": 60, "name": "以固定比重為主，小幅跟著改"},
            {"hl": 30, "sk": 1e12, "name": "固定比重（不跟著最近表現改）"}]
TUNE_MARGIN = 0.003
CAL_WIN = 60

DT_FACTORS = [
    ("ret1", "今天漲跌", 0.0),
    ("clv", "收盤接近今天最高價還是最低價", 0.0),
    ("range", "今天最高最低價差", 0.0),
    ("atr10", "近 10 天每天平均震盪幅度", 0.004),
    ("gap", "今天開盤跳高或跳低", 0.0),
    ("body", "今天收盤比開盤高多少", 0.0),
    ("vol1", "今天成交量比平常多多少", 0.004),
    ("streak", "連續漲（跌）幾天", 0.0),
    ("limit", "今天漲停或跌停", 0.0),
    ("hi20", "離 20 天內最高價多遠", 0.0),
    ("fi1", "外資今天買或賣", 0.004),
    ("it1", "投信今天買或賣", 0.004),
    ("dl1", "自營商今天買或賣", 0.0),
    ("oc5", "近 5 天開盤後是走高還是走低", 0.0),
    ("mom5", "近一週漲跌", 0.0),
    ("ma5gap", "股價比 5 天平均價高多少", 0.0),
    ("rsi6", "短線強弱（6 日 RSI）", 0.0),
]
DKEYS = [f[0] for f in DT_FACTORS]
DNAME = {f[0]: f[1] for f in DT_FACTORS}
DPRIOR = {f[0]: f[2] for f in DT_FACTORS}


def isnan(x):
    return x != x


def _sma(x, n, t):
    w = x[t - n + 1:t + 1] if t >= n - 1 else []
    if len(w) < n or any(isnan(v) for v in w):
        return NAN
    return sum(w) / n


def dt_factors(s, A, T):
    o, h, l, c, ref, v = s["o"], s["h"], s["l"], s["c"], s["ref"], s["v"]
    fi, it, dl = s["fi"], s["it"], s["dl"]
    F = {k: [NAN] * T for k in DKEYS}
    rng = [NAN] * T
    oc = [NAN] * T
    up = 0
    for t in range(T):
        ct, ot, ht, lt, rt = c[t], o[t], h[t], l[t], ref[t]
        if isnan(ct) or isnan(rt) or rt <= 0:
            up = 0
            continue
        r1 = ct / rt - 1
        F["ret1"][t] = r1
        if not isnan(ht) and not isnan(lt) and ht > lt:
            F["clv"][t] = (ct - lt) / (ht - lt) * 2 - 1
            rng[t] = (ht - lt) / rt
            F["range"][t] = rng[t]
        if not isnan(ot) and ot > 0:
            F["gap"][t] = ot / rt - 1
            F["body"][t] = (ct - ot) / rt
            oc[t] = ct / ot - 1
        up = (up + 1 if up > 0 else 1) if r1 > 0.0005 else ((up - 1 if up < 0 else -1) if r1 < -0.0005 else 0)
        F["streak"][t] = max(-8, min(8, up))
        F["limit"][t] = 1.0 if r1 >= 0.095 else (-1.0 if r1 <= -0.095 else 0.0)
        v20 = _sma(v, 20, t)
        if not isnan(v20) and v20 > 0:
            F["vol1"][t] = math.log((v[t] + 1) / (v20 + 1))
            for k, x in (("fi1", fi), ("it1", it), ("dl1", dl)):
                if not isnan(x[t]):
                    F[k][t] = x[t] / v20
        if t >= 9:
            w = [x for x in rng[t - 9:t + 1] if not isnan(x)]
            if len(w) >= 7:
                F["atr10"][t] = sum(w) / len(w)
            w = [x for x in oc[t - 4:t + 1] if not isnan(x)]
            if len(w) >= 4:
                F["oc5"][t] = sum(w) / len(w)
        if t >= 19:
            hs = [x for x in h[t - 19:t + 1] if not isnan(x)]
            if len(hs) >= 15:
                F["hi20"][t] = ct / max(hs) - 1
        if t >= 5 and not isnan(A[t]) and not isnan(A[t - 5]) and A[t - 5] > 0:
            F["mom5"][t] = A[t] / A[t - 5] - 1
        m5 = _sma(A, 5, t)
        if not isnan(m5) and m5 > 0:
            F["ma5gap"][t] = A[t] / m5 - 1
        if t >= 6:
            g = d = 0.0
            ok = True
            for k in range(t - 5, t + 1):
                if isnan(A[k]) or isnan(A[k - 1]):
                    ok = False
                    break
                x = A[k] - A[k - 1]
                g += max(x, 0)
                d += max(-x, 0)
            if ok:
                F["rsi6"][t] = 100.0 if d == 0 else 100 - 100 / (1 + g / d)
    return F


def _rank_unit(vals):
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
        u = (i + j) / 2.0 / (n - 1) * 2 - 1
        for k in range(i, j + 1):
            out[vals[k][1]] = u
        i = j + 1
    return out


def _pearson(a, b):
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


def _weights(ic_hist, upto, hl=None, sk=None):
    lam = 0.5 ** (1.0 / (hl or HALF_LIFE))
    SHRINK_K = sk if sk is not None else SHRINK_DEFAULT
    W = {}
    for k in DKEYS:
        sw = sv = 0.0
        for tt, c in reversed(ic_hist[k]):
            if tt > upto:
                continue
            age = upto - tt
            if age > 250:
                break
            wt = lam ** age
            sw += wt
            sv += wt * c
        if sw == 0:
            W[k] = DPRIOR[k]
            continue
        W[k] = (sw / (sw + SHRINK_K)) * (sv / sw) + (SHRINK_K / (sw + SHRINK_K)) * DPRIOR[k]
    return W


def _q(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(len(xs) * p)))]


def reason(k, v, w):
    if v is None or isnan(v):
        return None
    pct = lambda x: "%.1f%%" % (abs(x) * 100)
    if k == "ret1":
        return "今天%s %s" % ("上漲" if v >= 0 else "下跌", pct(v))
    if k == "clv":
        return "收盤接近今天最高價" if v > 0.6 else ("收盤接近今天最低價" if v < -0.6 else "收盤在今天高低價中間")
    if k == "range":
        return "今天最高最低價差 %s" % pct(v)
    if k == "atr10":
        return "近 10 天每天平均上下震盪 %s（%s）" % (pct(v), "波動夠大，有操作空間" if v > 0.04 else "波動偏小")
    if k == "gap":
        return "今天開盤%s %s" % ("跳空上漲" if v > 0 else "跳空下跌", pct(v)) if abs(v) > 0.005 else "今天開盤平盤附近"
    if k == "body":
        return "今天收盤比開盤%s %s" % ("高" if v > 0 else "低", pct(v))
    if k == "vol1":
        return "今天成交量是平常的 %.1f 倍" % math.exp(v)
    if k == "streak":
        return "連續 %d 天%s" % (abs(v), "上漲" if v > 0 else "下跌") if v else None
    if k == "limit":
        return "今天漲停" if v > 0 else ("今天跌停" if v < 0 else None)
    if k == "hi20":
        return "創 20 日新高" if v > -0.003 else "距 20 日高點 %s" % pct(v)
    if k in ("fi1", "it1", "dl1"):
        who = {"fi1": "外資", "it1": "投信", "dl1": "自營商"}[k]
        return "%s今天%s（約平常成交量的 %.0f%%）" % (who, "買超" if v > 0 else "賣超", abs(v) * 100)
    if k == "oc5":
        return "近 5 天開盤後平均%s %s" % ("走高" if v > 0 else "走低", pct(v))
    if k == "mom5":
        return "近一週%s %s" % ("上漲" if v >= 0 else "下跌", pct(v))
    if k == "ma5gap":
        return "股價%s近 5 天平均價 %s" % ("高於" if v >= 0 else "低於", pct(v))
    if k == "rsi6":
        return "短線強弱指標 %.0f（%s）" % (v, "漲多" if v >= 70 else "跌深" if v <= 30 else "普通")
    return None


def _comp(Rk, W, n):
    comp = [0.0] * n
    for k, arr in Rk.items():
        wk = W[k]
        if wk:
            comp = [c + wk * x for c, x in zip(comp, arr)]
    return comp


def _tune(D, stored, univ_hist, ic_hist):
    st = read_json(TUNE_PATH, {}) or {}
    prev = st.get("dt")
    day = D.days[-1]
    ev = [t for t in sorted(stored) if univ_hist.get(t)]
    res = []
    if len(ev) >= 20:
        last_t = ev[-1]
        lam = 0.5 ** (1.0 / 30)
        for c in DT_CANDS:
            ics = []
            for t in ev:
                univ, Rk = stored[t]
                out = univ_hist[t]
                comp = _comp(Rk, _weights(ic_hist, t - 1, c["hl"], c["sk"]), len(univ))
                xs, ys = [], []
                for j, i in enumerate(univ):
                    o = out.get(i)
                    if o is not None:
                        xs.append((comp[j], len(xs)))
                        ys.append(o[0])
                pr = _rank_unit(xs)
                ics.append((t, _pearson([pr[j] for j in range(len(ys))], ys)))
            vals = [v for _, v in ics if v is not None]
            sw = sum(lam ** (last_t - t) for t, v in ics if v is not None)
            sc = sum(lam ** (last_t - t) * v for t, v in ics if v is not None) / sw if sw else None
            n3 = max(1, len(vals) // 3)
            res.append({"name": c["name"], "hl": c["hl"], "sk": c["sk"], "score": sc,
                        "all": sum(vals) / len(vals) if vals else None,
                        "recent": sum(vals[-n3:]) / n3 if vals else None,
                        "win": sum(1 for v in vals if v > 0) / len(vals) if vals else None, "n": len(vals)})
    ok = [r for r in res if r["score"] is not None]
    if not ok:
        return prev or {"hl": HALF_LIFE, "sk": SHRINK_DEFAULT, "name": "預設"}
    best = max(ok, key=lambda r: r["score"])
    prev_r = next((r for r in ok if prev and r["hl"] == prev.get("hl") and r["sk"] == prev.get("sk")), None)
    log_ = list(st.get("log", []))
    if prev_r and best["score"] - prev_r["score"] < TUNE_MARGIN:
        chosen = prev_r
    else:
        chosen = best
        if (not prev or (prev.get("hl"), prev.get("sk")) != (best["hl"], best["sk"])) and not any(
                x.get("day") == day and x.get("hn") == "dt" and x.get("to") == best["name"] for x in log_):
            log_.append({"day": day, "part": "dt", "hn": "dt", "from": prev.get("name") if prev else None,
                         "to": best["name"], "gain": None if not prev_r else round(best["score"] - prev_r["score"], 4)})
    for r in res:
        r["chosen"] = r["name"] == chosen["name"]
        for k in ("score", "all", "recent", "win"):
            if r[k] is not None:
                r[k] = round(r[k], 4)
    cfg = {"hl": chosen["hl"], "sk": chosen["sk"], "name": chosen["name"]}
    st["dt"] = cfg
    st.setdefault("eval", {})["dt"] = sorted(res, key=lambda r: -(r["score"] if r["score"] is not None else -9))
    hist = [x for x in st.get("history", []) if x.get("day") != day or x.get("part") != "dt"]
    fixed = next((r for r in res if r["sk"] >= 1e11), None)
    hist.append({"day": day, "part": "dt", "hn": "dt", "name": chosen["name"], "score": chosen["score"],
                 "fixed": fixed["score"] if fixed else None})
    st["history"] = hist[-900:]
    st["log"] = log_[-200:]
    write_json(TUNE_PATH, st)
    return cfg


DT_SHRINK = 0.6     # 往過去平均收斂的程度（實測：保留 60% 的差距最接近實際結果）


def _per_stock(stored, pct_hist, univ_hist, ts, last):
    """逐檔估計隔天當沖的勝算、平均報酬、最高／最低價。
    用最近 CAL_WIN 天、每檔的所有當沖條件（不只綜合分數）做邏輯迴歸與線性迴歸，
    再往過去平均收斂，避免前段班全部卡在同一個數字。需要 numpy；沒有時回傳 None。"""
    try:
        import numpy as np
    except Exception:
        return None
    if last not in stored or len(ts) < 30:
        return None

    def feats(t):
        univ, Rk = stored[t]
        pc = pct_hist.get(t, {})
        X = np.c_[np.array([pc.get(i, 0.5) for i in univ]), np.array([Rk[k] for k in DKEYS], dtype=np.float64).T] - 0.5
        return univ, X
    Xs, ys = [], []
    for t in ts:
        if t not in stored:
            continue
        out = univ_hist.get(t) or {}
        univ, X = feats(t)
        m = [j for j, i in enumerate(univ) if i in out]
        if not m:
            continue
        Xs.append(X[m])
        ys.append(np.array([out[univ[j]] for j in m], dtype=np.float64))
    if not Xs:
        return None
    X, Y = np.concatenate(Xs), np.concatenate(ys)
    if len(X) < 1500:
        return None
    Z = np.c_[np.ones(len(X)), X]
    reg = np.diag(np.r_[0.0, np.ones(X.shape[1])])

    def logit(y, l2=5.0):
        w = np.zeros(Z.shape[1])
        for _ in range(30):
            p = 1 / (1 + np.exp(-np.clip(Z @ w, -30, 30)))
            step = np.linalg.solve((Z * (p * (1 - p))[:, None]).T @ Z + l2 * reg, Z.T @ (p - y) + l2 * reg @ w)
            w -= step
            if np.abs(step).max() < 1e-7:
                break
        b = min(0.99, max(0.01, y.mean()))
        return w, np.log(b / (1 - b))

    def ridge(y, l2=50.0):
        return np.linalg.solve(Z.T @ Z + l2 * reg, Z.T @ y), y.mean()
    wl, bl = logit((Y[:, 0] - COST > 0).astype(float))
    ws, bs = logit((-Y[:, 0] - COST > 0).astype(float))
    ra, ma = ridge(Y[:, 0])
    rh, mh = ridge(Y[:, 1])
    rl, ml = ridge(Y[:, 2])
    univ, X = feats(last)
    Zt = np.c_[np.ones(len(X)), X]
    k = DT_SHRINK
    pl = 1 / (1 + np.exp(-(bl + k * (Zt @ wl - bl))))
    ps = 1 / (1 + np.exp(-(bs + k * (Zt @ ws - bs))))
    av = ma + k * (Zt @ ra - ma)
    hi = np.maximum(mh + k * (Zt @ rh - mh), 0.0)
    lo = np.minimum(ml + k * (Zt @ rl - ml), 0.0)
    return {i: (float(pl[j]), float(ps[j]), float(av[j]), float(hi[j]), float(lo[j])) for j, i in enumerate(univ)}


def run(D, A_all, say=None):
    T, codes = D.T, D.codes
    N = len(codes)
    FA = []
    val20 = []
    for i, code in enumerate(codes):
        s = D.raw[code]
        FA.append(dt_factors(s, A_all[i], T))
        vv = s["val"]
        val20.append([_sma(vv, 20, t) for t in range(T)])
    if say:
        say("當沖模型：回測與調整權重")
    ic_hist = {k: [] for k in DKEYS}
    comp_ic = []
    keep_from = max(0, T - 130)
    pct_hist, univ_hist = {}, {}
    last_R = last_W = None
    stored = {}
    for t in range(T):
        univ = []
        for i, code in enumerate(codes):
            if is_etf(code):
                continue
            s = D.raw[code]
            c = s["c"][t]
            if isnan(c) or c < DT_MIN_PRICE:
                continue
            v20 = val20[i][t]
            if isnan(v20) or v20 < DT_MIN_VALUE:
                continue
            univ.append(i)
        if len(univ) < 60:
            continue
        R = {}
        for k in DKEYS:
            vals = [(FA[i][k][t], i) for i in univ if not isnan(FA[i][k][t])]
            R[k] = _rank_unit(vals) if len(vals) >= 40 else {}
        out = {}
        if t + 1 < T:
            for i in univ:
                s = D.raw[codes[i]]
                o1, c1 = s["o"][t + 1], s["c"][t + 1]
                if not isnan(o1) and not isnan(c1) and o1 > 0:
                    out[i] = (c1 / o1 - 1, s["h"][t + 1] / o1 - 1, s["l"][t + 1] / o1 - 1)
            if len(out) >= 40:
                yr = _rank_unit([(r[0], i) for i, r in out.items()])
                for k in DKEYS:
                    if not R[k]:
                        continue
                    xs, ys = [], []
                    for i, y in yr.items():
                        x = R[k].get(i)
                        if x is not None:
                            xs.append(x)
                            ys.append(y)
                    cc = _pearson(xs, ys)
                    if cc is not None:
                        ic_hist[k].append((t, cc))
        if t >= keep_from or t == T - 1:
            stored[t] = (univ, {k: [R[k].get(i, 0.0) for i in univ] for k in DKEYS})
            univ_hist[t] = out
        if t == T - 1:
            last_R = R

    # ---- 自動調校：比較不同的權重調整速度，挑實測最準的
    if say:
        say("當沖模型：依實測結果自動調校")
    cfg = _tune(D, stored, univ_hist, ic_hist)
    for t in sorted(stored):
        univ, Rk = stored[t]
        W = _weights(ic_hist, t - 1, cfg["hl"], cfg["sk"])
        comp = _comp(Rk, W, len(univ))
        pr = _rank_unit([(comp[j], univ[j]) for j in range(len(univ))])
        pct = {i: (u + 1) / 2 for i, u in pr.items()}
        pct_hist[t] = pct
        out = univ_hist[t]
        if out:
            xs = [pct[i] for i in out if i in pct]
            ys = [out[i][0] for i in out if i in pct]
            cc = _pearson(xs, ys)
            if cc is not None:
                comp_ic.append((t, cc))
        last_W = W

    # ---- 回測統計（每天：分數前 10% 做多、後 10% 做空）
    longs, shorts, spreads = [], [], []
    for t, pct in pct_hist.items():
        out = univ_hist.get(t) or {}
        if not out:
            continue
        top = [out[i][0] for i, p in pct.items() if p >= 0.9 and i in out]
        bot = [out[i][0] for i, p in pct.items() if p <= 0.1 and i in out]
        if top and bot:
            longs.extend(top)
            shorts.extend(bot)
            spreads.append((t, sum(top) / len(top) - sum(bot) / len(bot)))
    alls = [r[0] for t, o in univ_hist.items() for r in o.values()]

    def side_stats(xs, sign):
        if not xs:
            return None
        net = [sign * x - COST for x in xs]
        return {"n": len(xs), "win": round(sum(1 for x in net if x > 0) / len(net), 4),
                "avg": round(sum(net) / len(net), 5)}
    # ---- 校準（最近 CAL_WIN 天，分十個區間）
    ts = sorted(t for t in pct_hist if univ_hist.get(t))[-CAL_WIN:]
    bins = [[] for _ in range(10)]
    for t in ts:
        out = univ_hist[t]
        for i, p in pct_hist[t].items():
            if i in out:
                bins[min(9, int(p * 10))].append(out[i])
    calib = []
    for b in bins:
        if len(b) < 15:
            calib.append(None)
            continue
        oc = [x[0] for x in b]
        calib.append({
            "n": len(b),
            "win_long": sum(1 for x in oc if x - COST > 0) / len(b),
            "win_short": sum(1 for x in oc if -x - COST > 0) / len(b),
            "avg": sum(oc) / len(b),
            "hi": _q([x[1] for x in b], .5), "lo": _q([x[2] for x in b], .5),
        })
    # ---- 今天的推薦
    # 分數＝「扣成本後勝率」：由分數區間的歷史結果內插而來，是絕對的勝算，不是排名，
    # 所以整體沒有優勢時分數就會偏低，不會出現「100 分卻不建議」的矛盾。
    centers = [(j + 0.5) / 10 for j in range(10)]

    def interp(p, key):
        pts = [(centers[j], calib[j][key]) for j in range(10) if calib[j] and calib[j].get(key) is not None]
        if not pts:
            return None
        if p <= pts[0][0]:
            return pts[0][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if p <= x1:
                return y0 + (y1 - y0) * (p - x0) / (x1 - x0)
        return pts[-1][1]

    last = T - 1
    pct = pct_hist.get(last, {})
    per = _per_stock(stored, pct_hist, univ_hist, ts, last)
    scores = {}
    rows = []
    for i, p in pct.items():
        code = codes[i]
        s = D.raw[code]
        contrib = sorted(((last_W[k] * last_R[k].get(i, 0.0), k) for k in DKEYS), reverse=True)
        pos = [reason(k, FA[i][k][last], w) for w, k in contrib[:6] if w > 0.0003]
        neg = [reason(k, FA[i][k][last], w) for w, k in contrib[::-1][:6] if w < -0.0003]
        wl, ws, av = interp(p, "win_long"), interp(p, "win_short"), interp(p, "avg")
        hi, lo = interp(p, "hi"), interp(p, "lo")
        if per and i in per:      # 逐檔估計（取代「同一個分數區間共用一個數字」）
            wl, ws, av, hi, lo = per[i]
        scores[code] = [None if wl is None else round(wl * 100, 1), None if ws is None else round(ws * 100, 1)]
        rows.append({
            "c": code, "n": D.names.get(code, code), "m": D.market.get(code, ""),
            "px": s["c"][last], "chg": (s["c"][last] / s["ref"][last] - 1) if s["ref"][last] == s["ref"][last] and s["ref"][last] else 0,
            "p": round(p, 4), "atr": None if isnan(FA[i]["atr10"][last]) else round(FA[i]["atr10"][last], 4),
            "val": round(val20[i][last] / 1e8, 2), "wl": wl, "ws": ws, "av": av, "hi": hi, "lo": lo,
            "pos": [x for x in pos if x][:3], "neg": [x for x in neg if x][:3],
        })

    def pick(side):
        key = "wl" if side == "long" else "ws"
        al = getattr(D, "alerts", None) or {"warn": {}, "disp": {}}
        # 處置股採人工撮合、需預收款券，實際上無法當沖，直接排除
        sel = [r for r in rows if r[key] is not None and r["c"] not in al["disp"]]
        sel.sort(key=lambda r: (-r[key], -r["p"] if side == "long" else r["p"]))
        out = []
        for r in sel[:30]:
            if side == "long":
                win, avg, tp, sl, why = r["wl"], (r["av"] or 0) - COST, r["hi"], r["lo"], r["pos"]
            else:
                win, avg, tp, sl, why = r["ws"], -(r["av"] or 0) - COST, r["lo"], r["hi"], r["neg"]
            ok = win > 0.5 and avg > 0
            out.append({"c": r["c"], "n": r["n"], "m": r["m"], "px": r["px"], "chg": round(r["chg"], 4), "ok": ok,
                        "score": round(win * 100, 1), "win": round(win, 3), "avg": round(avg, 4),
                        "tp": None if tp is None else round(tp, 4), "sl": None if sl is None else round(sl, 4),
                        "atr": r["atr"], "val": r["val"], "why": why,
                        "al": 1 if r["c"] in al["warn"] else 0})
        return out

    roll = []
    for j in range(len(comp_ic)):
        w = [c for _, c in comp_ic[max(0, j - 19):j + 1]]
        roll.append([D.days[comp_ic[j][0]], round(sum(w) / len(w), 4)])
    fac = sorted(({"k": k, "name": DNAME[k], "w": round(last_W[k], 4) if last_W else 0,
                   "ic": round(sum(c for _, c in ic_hist[k][-60:]) / max(1, len(ic_hist[k][-60:])), 4)}
                  for k in DKEYS), key=lambda x: -abs(x["w"]))
    base_win = sum(1 for x in alls if x - COST > 0) / len(alls) if alls else None
    L, S = pick("long"), pick("short")
    return {
        "long_ok": sum(1 for r in L if r["ok"]), "short_ok": sum(1 for r in S if r["ok"]),
        "day": D.days[last], "cost": round(COST, 5), "universe": len(pct),
        "long": L, "short": S,
        "model": {
            "eval_days": len(spreads),
            "long": side_stats(longs, 1), "short": side_stats(shorts, -1),
            "base_win": None if base_win is None else round(base_win, 4),
            "spread_avg": round(sum(s for _, s in spreads) / len(spreads), 5) if spreads else None,
            "spread_win": round(sum(1 for _, s in spreads if s > 0) / len(spreads), 4) if spreads else None,
            "ic_roll": roll[-120:], "factors": fac,
            "calib": [None if c is None else {k: (round(v, 4) if isinstance(v, float) else v) for k, v in c.items()} for c in calib],
        },
    }, scores
