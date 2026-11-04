# -*- coding: utf-8 -*-
"""大跌風險（加權指數）：估計「一週內跌 4% 以上」與「下個交易日跌 2% 以上」的機率，並給出應對方式。

為什麼不是預測「明天會不會跌」：大盤方向很難預測（模型實測很難贏過「一律猜漲」），
但「大幅波動」會群聚——剛跌過、波動變大、離高點越遠時，接下來再大跌的機會明顯變高。
所以這裡估的是「風險高不高」，不是「會不會跌」。

做法（全程只用當時已知的資料，walk-forward）：
1. 條件（方向事前依常理／文獻決定，模型只估大小）：近 20 天波動（越大越危險）、近 5 天波動相對近 20 天
   （突然變大）、近 20 天相對近一年波動、離近 60 天高點多遠、離季線多遠、今天漲跌、近 5 天漲跌。
2. 用加權指數 2000 年以來的每日收盤，邏輯迴歸，每 20 個交易日用「之前已經揭曉」的資料重估一次。
3. 下個交易日：早上 07:35 美股收盤後，再加上隔夜的台積電 ADR 與費城半導體漲跌（兩者平均；
   美股資料只有約兩年，用這兩年已揭曉的資料估計），台股開盤前更新。
4. 風險等級：今天的機率在過去所有日子（當時算出來的機率）中的位置：
   後 50% 低、50%～75% 正常、75%～90% 偏高、前 10% 高。並附上每個等級過去實際發生大跌的比例。
5. 應對：用同樣的 walk-forward 機率回測「高風險時持股減半」對報酬與最大回落的影響，數字照實顯示。
"""
import math
import os

from util import log

W5_H, W5_DROP = 5, -0.04
D1_DROP = -0.02
START = 260
FIRST = START + 250 * 4          # 第一次預測（約 2005 年初），之前只用來估計
REFIT = 20
LEVELS = [(0.0, "低"), (0.5, "正常"), (0.75, "偏高"), (0.9, "高")]
US_SYMS = ("TSM", "^SOX")


def _irls(np, X, y, l2=1.0, it=40):
    Z = np.c_[np.ones(len(X)), X]
    w = np.zeros(Z.shape[1])
    R = l2 * np.diag(np.r_[0.0, np.ones(Z.shape[1] - 1)])
    for _ in range(it):
        p = 1.0 / (1.0 + np.exp(-np.clip(Z @ w, -30, 30)))
        g = Z.T @ (p - y) + R @ w
        Hm = (Z * (p * (1 - p))[:, None]).T @ Z + R
        s = np.linalg.solve(Hm, g)
        w -= s
        if np.abs(s).max() < 1e-8:
            break
    return w


def _level(pct):
    lv = LEVELS[0][1]
    for lo, name in LEVELS:
        if pct is not None and pct >= lo:
            lv = name
    return lv


def _series(D):
    """加權指數長期收盤（db/twii_long.json），缺的日子用本地收盤補上。"""
    from util import DB, read_json
    s = dict((read_json(os.path.join(DB, "twii_long.json"), {}) or {}).get("s") or {})
    last = D.days[-1]
    s = {d: v for d, v in s.items() if d <= last and v}
    for t, d in enumerate(D.days):
        v = D.mkt["taiex"][t]
        if d not in s and v == v and v:
            s[d] = v
    return s


def _walk(np, X, y, valid, hz, n):
    """逐日 walk-forward：每 REFIT 天用已揭曉資料重估一次。回傳每天的機率。"""
    P = np.full(n, np.nan)
    w = None
    for i in range(FIRST, n):
        if w is None or (i - FIRST) % REFIT == 0:
            tr = np.arange(START, max(START, i - hz))
            tr = tr[valid[tr] & ~np.isnan(X[tr]).any(1)]
            if len(tr) < 500:
                continue
            w = _irls(np, X[tr], y[tr].astype(float))
        if w is not None and not np.isnan(X[i]).any():
            P[i] = 1.0 / (1.0 + math.exp(-float(np.r_[1.0, X[i]] @ w)))
    return P


def _pct_hist(np, P):
    """每天的機率在「當時以前」所有機率中的位置（只用過去）。"""
    out = np.full(len(P), np.nan)
    seen = []
    import bisect
    for i in range(len(P)):
        if np.isnan(P[i]):
            continue
        if len(seen) >= 250:
            out[i] = bisect.bisect_left(seen, P[i]) / len(seen)
        bisect.insort(seen, P[i])
    return out


def _bt(np, f1, pct, mask):
    def one(e):
        r = e[mask] * f1[mask]
        if len(r) < 100:
            return None
        eq = np.cumprod(1 + r)
        yrs = len(r) / 250.0
        return {"cagr": round(float(eq[-1] ** (1 / yrs) - 1), 4),
                "vol": round(float(r.std() * math.sqrt(250)), 4),
                "mdd": round(float((eq / np.maximum.accumulate(eq) - 1).min()), 4)}
    half = np.where(pct >= 0.9, 0.5, 1.0)
    return {"hold": one(np.ones(len(f1))), "half": one(half)}


def build(D, A_all=None, stock_codes=None):
    try:
        import numpy as np
    except Exception:
        return None, {}
    s = _series(D)
    ds = sorted(s)
    n = len(ds)
    if n < FIRST + 300:
        return None, {}
    c = np.array([s[d] for d in ds], dtype=float)
    r = np.r_[0.0, np.log(c[1:] / c[:-1])]

    def rstd(w):
        out = np.full(n, np.nan)
        cs, cs2 = np.r_[0, np.cumsum(r)], np.r_[0, np.cumsum(r * r)]
        for i in range(w, n):
            m = (cs[i + 1] - cs[i + 1 - w]) / w
            out[i] = math.sqrt(max(1e-12, (cs2[i + 1] - cs2[i + 1 - w]) / w - m * m))
        return out
    rv20, rv250 = rstd(20) * math.sqrt(250), rstd(250) * math.sqrt(250)
    rv5 = np.full(n, np.nan)
    for i in range(5, n):
        rv5[i] = math.sqrt(float((r[i - 4:i + 1] ** 2).mean()) * 250)
    mx60 = np.array([c[max(0, i - 59):i + 1].max() for i in range(n)])
    ma60 = np.array([c[max(0, i - 59):i + 1].mean() for i in range(n)])
    dd60, g60 = c / mx60 - 1, c / ma60 - 1
    ret5 = np.r_[np.full(5, np.nan), c[5:] / c[:-5] - 1]
    X = np.c_[np.log(rv20), np.log(rv5 + 1e-4) - np.log(rv20), np.log(rv20) - np.log(rv250), dd60 * 10,
              np.clip(g60, -0.3, 0.3) * 10, r * 50, np.clip(ret5, -0.3, 0.3) * 10]
    fmin = np.full(n, np.nan)
    for i in range(n - W5_H):
        fmin[i] = c[i + 1:i + 1 + W5_H].min() / c[i] - 1
    f1 = np.r_[c[1:] / c[:-1] - 1, np.nan]
    y5, v5 = fmin <= W5_DROP, ~np.isnan(fmin)
    y1, v1 = f1 <= D1_DROP, ~np.isnan(f1)
    P5 = _walk(np, X, y5, v5, W5_H, n)
    P1 = _walk(np, X, y1, v1, 1, n)
    pc5, pc1 = _pct_hist(np, P5), _pct_hist(np, P1)
    last = n - 1

    # ---- 各等級過去實際發生的比例（walk-forward 機率，2006 年起）
    def by_level(pc, y, v, P):
        rows = []
        bounds = [x[0] for x in LEVELS] + [1.01]
        for k, (lo, name) in enumerate(LEVELS):
            m = v & ~np.isnan(pc) & (pc >= lo) & (pc < bounds[k + 1])
            if m.sum():
                rows.append({"lv": name, "days": int(m.sum()), "rate": round(float(y[m].mean()), 4),
                             "p": round(float(P[m].mean()), 4)})
        m = v & ~np.isnan(pc)
        return rows, round(float(y[m].mean()), 4) if m.sum() else None
    lv5, base5 = by_level(pc5, y5, v5, P5)
    lv1, base1 = by_level(pc1, y1, v1, P1)

    # ---- 隔夜美股（台積電 ADR、費城半導體）：下個交易日
    graw = getattr(D, "glob_raw", {}) or {}
    ov = np.full(n, np.nan)
    ov_info = None
    rets = {}
    for sym in US_SYMS:
        x = (graw.get(sym) or {}).get("s") or {}
        ks = sorted(k for k, v in x.items() if v)
        rets[sym] = (ks, {ks[j]: math.log(x[ks[j]] / x[ks[j - 1]]) for j in range(1, len(ks))})
    if all(len(rets[s_][0]) > 300 for s_ in US_SYMS):
        import bisect
        for i in range(n):
            vals = []
            for sym in US_SYMS:
                ks, rr = rets[sym]
                if ds[i] < ks[1]:
                    break
                hi = ds[i + 1] if i + 1 < n else "99999999"
                a, b = bisect.bisect_left(ks, ds[i]), bisect.bisect_left(ks, hi)
                vals.append(sum(rr.get(k, 0.0) for k in ks[a:b]))
            if len(vals) == len(US_SYMS):
                ov[i] = sum(vals) / len(vals)
        # 今天之後還沒有美股收盤（下午的更新）：沒有隔夜資訊
        if all(rets[s_][0][-1] < ds[last] for s_ in US_SYMS):
            ov[last] = np.nan
        else:
            ov_info = {"day": max(rets[s_][0][-1] for s_ in US_SYMS),
                       "chg": round(float(math.exp(ov[last]) - 1), 4) if not np.isnan(ov[last]) else None,
                       "by": {s_: round(float(math.exp(sum(v for k, v in rets[s_][1].items() if k >= ds[last])) - 1), 4)
                              for s_ in US_SYMS}}
    lg1 = np.log(P1 / (1 - P1))
    Xo = np.c_[lg1, np.clip(ov, -0.15, 0.15) * 30]
    okk = ~np.isnan(Xo).any(1)
    idx = np.where(okk & v1)[0]
    P1o = np.full(n, np.nan)
    ov_stat = None
    if len(idx) > 200:
        w = None
        first = 120
        for k in range(first, len(idx)):
            i = idx[k]
            if w is None or (k - first) % 10 == 0:
                tr = idx[:k - 1]
                w = _irls(np, Xo[tr], y1[tr].astype(float))
            P1o[i] = 1 / (1 + math.exp(-float(np.r_[1.0, Xo[i]] @ w)))
        m = idx[first:]
        yy, pp, pb = y1[m], P1o[m], P1[m]
        q_o, q_b = np.quantile(pp, 0.9), np.quantile(pb, 0.9)
        ov_stat = {"n": int(len(m)), "events": int(yy.sum()), "base": round(float(yy.mean()), 4),
                   "top_o": round(float(yy[pp >= q_o].mean()), 4), "top_b": round(float(yy[pb >= q_b].mean()), 4),
                   "brier_o": round(float(np.mean((pp - yy) ** 2)), 5), "brier_b": round(float(np.mean((pb - yy) ** 2)), 5),
                   "from": ds[m[0]], "to": ds[m[-1]]}
        wf = _irls(np, Xo[idx], y1[idx].astype(float))
        if okk[last]:
            P1o[last] = 1 / (1 + math.exp(-float(np.r_[1.0, Xo[last]] @ wf)))
    p1_today = float(P1o[last]) if (ov_info and not np.isnan(P1o[last])) else float(P1[last])
    hist1 = P1[~np.isnan(P1)][:-1]
    pc1_today = float((hist1 < p1_today).mean()) if len(hist1) else None

    # ---- 應對的回測：高風險（一週風險前 10%）時持股減半
    mk = ~np.isnan(pc5) & ~np.isnan(f1)
    bt = {"all": _bt(np, f1, pc5, mk), "y2": _bt(np, f1, pc5, mk & (np.arange(n) >= n - 500)),
          "from": ds[int(np.where(mk)[0][0])] if mk.any() else None}
    # 高風險日的隔天平均漲跌（風險高≠一定跌）
    hm = mk & (pc5 >= 0.9)
    bt["hi_next_avg"] = round(float(f1[hm].mean()), 4) if hm.any() else None
    bt["hi_next_up"] = round(float((f1[hm] > 0).mean()), 4) if hm.any() else None

    # ---- 最近 30 個交易日的紀錄（當時算的機率 vs 後來真的有沒有大跌）
    track = []
    for i in range(max(FIRST, n - 30), n):
        track.append({"d": ds[i], "c": round(float(c[i]), 2), "p5": None if np.isnan(P5[i]) else round(float(P5[i]), 4),
                      "lv": None if np.isnan(pc5[i]) else _level(float(pc5[i])),
                      "min5": None if np.isnan(fmin[i]) else round(float(fmin[i]), 4),
                      "next": None if np.isnan(f1[i]) else round(float(f1[i]), 4)})

    lv_w5 = _level(float(pc5[last])) if not np.isnan(pc5[last]) else None
    lv_d1 = _level(pc1_today)
    order = [x[1] for x in LEVELS]
    level = max([lv for lv in (lv_w5, lv_d1) if lv], key=order.index, default=None)
    why = []
    if not np.isnan(rv20[last]) and not np.isnan(rv250[last]) and rv250[last] > 0:
        k = rv20[last] / rv250[last]
        if k >= 1.2:
            why.append("最近一個月上下震盪是近一年平常的 %.1f 倍" % k)
        elif k <= 0.8:
            why.append("最近一個月震盪比近一年平常小")
    if dd60[last] <= -0.03:
        why.append("比近 3 個月高點低 %.1f%%" % (-dd60[last] * 100))
    else:
        why.append("離近 3 個月高點不遠")
    if not np.isnan(ret5[last]):
        why.append("近 5 天%s %.1f%%" % ("漲" if ret5[last] >= 0 else "跌", abs(ret5[last]) * 100))
    if ov_info and ov_info.get("chg") is not None:
        why.append("隔夜台積電 ADR %s、費城半導體 %s" % tuple(
            ("%+.1f%%" % (ov_info["by"][s_] * 100)) for s_ in US_SYMS))

    out = {
        "day": ds[last], "level": level, "why": why,
        "w5": {"p": round(float(P5[last]), 4), "pct": round(float(pc5[last]), 3), "lv": lv_w5, "base": base5,
               "levels": lv5, "drop": W5_DROP, "h": W5_H},
        "d1": {"p": round(p1_today, 4), "p_tw": round(float(P1[last]), 4), "pct": round(pc1_today, 3), "lv": lv_d1,
               "base": base1, "levels": lv1, "drop": D1_DROP, "ov": ov_info, "ov_stat": ov_stat},
        "bt": bt, "track": track, "since": ds[FIRST][:4],
    }
    # ---- 每檔股票和大盤的連動（近 120 天 beta）：大盤大跌時這檔大約跌多少
    beta = {}
    if A_all is not None and stock_codes is not None:
        try:
            T = len(A_all[0])
            tx = np.array([np.nan if (v is None or v != v) else v for v in D.mkt["taiex"]], dtype=float)
            A = np.array([list(a) for a in A_all], dtype=float)
            w0 = max(1, T - 120)
            with np.errstate(all="ignore"):
                ra = A[:, w0:] / A[:, w0 - 1:-1] - 1
                rt = tx[w0:] / tx[w0 - 1:-1] - 1
            for i, code in enumerate(stock_codes):
                x = ra[i]
                ok = ~np.isnan(x) & ~np.isnan(rt)
                if ok.sum() < 60:
                    continue
                mx, my = rt[ok].mean(), x[ok].mean()
                vx = ((rt[ok] - mx) ** 2).sum()
                if vx > 0:
                    beta[code] = round(float(((rt[ok] - mx) * (x[ok] - my)).sum() / vx), 2)
        except Exception as e:
            log("個股連動計算失敗：%s" % e)
    return out, beta
