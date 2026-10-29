# -*- coding: utf-8 -*-
"""當沖：預測「隔天一整天大概怎麼走」與「高點、低點範圍」。

一、走勢型態（依隔天日 K：開盤 → 最高／最低 → 收盤，分五種）
  一路走高：收盤比開盤高，漲幅占全天高低差一半以上
  一路走低：收盤比開盤低，跌幅占全天高低差一半以上
  先漲後跌：上影線比下影線長（衝高後拉回）
  先跌後漲：下影線比上影線長（探底後回升）
  區間震盪：全天高低差不到平常（近 10 天平均振幅）的 6 成，或收盤和開盤差不多、上下都有影線
  只有日 K 資料、沒有分鐘資料，所以「先漲後跌」指的是全天的高點明顯高於收盤（衝高拉回），不保證高點一定出現在早盤。

  做法：用今天收盤後已知的當沖條件（各因子的排名、振幅、今天 K 棒、大盤當天表現），
  以 LightGBM 學「隔天是哪一種型態」，用過去 120 個交易日訓練、每 5 天重新訓練（walk-forward）。
  把握規則：用最近 100 個已揭曉交易日、模型「當時」的預測檢查每一種型態：
  某型態機率達到門檻的股票，實際真的出現這個型態的比例，要比一般情況高 10 個百分點以上、而且是一般的 1.4 倍以上，
  樣本也要夠（150 檔次以上），才會對這個型態下預測；達不到就寫「沒把握，不預測」。
  實測（兩年 walk-forward）：「區間震盪」與「一路走低」有明顯把握，其他三種目前達不到，不預測。

二、高點、低點範圍（以開盤價為基準）
  最高價比開盤高多少、最低價比開盤低多少，用分位數迴歸估 10%／50%／90% 位置（8 成機會落在範圍內），
  主要依據是這檔近 10 天的平均振幅；並公布過去 100 天的實際涵蓋率。

需要 numpy 與 lightgbm；沒有時回傳 None，當沖頁不顯示這兩項。
"""
import math

NAMES = ["一路走高", "一路走低", "先漲後跌", "先跌後漲", "區間震盪"]
TRAIN = 120
REFIT = 5
TRACK = 100
MIN_N = 150
LIFT_ABS = 0.10       # 實際命中率至少比一般情況高 10 個百分點
LIFT_REL = 1.4        # 而且是一般情況的 1.4 倍以上
FEATS_RAW = ["atr10", "range", "ret1", "clv", "gap", "oc5"]
SHAPE_PARAMS = {"objective": "multiclass", "num_class": 5, "learning_rate": 0.03, "num_leaves": 7, "min_data_in_leaf": 1000,
                "feature_fraction": 0.8, "bagging_fraction": 0.7, "bagging_freq": 1, "lambda_l2": 5, "verbose": -1,
                "num_threads": 2, "seed": 3, "deterministic": True}
Q_PARAMS = {"objective": "quantile", "learning_rate": 0.05, "num_leaves": 7, "min_data_in_leaf": 500, "verbose": -1,
            "num_threads": 2, "seed": 1, "deterministic": True}


def available():
    try:
        import numpy  # noqa: F401
        import lightgbm  # noqa: F401
        return True
    except Exception:
        return False


def label(o, h, l, c, ref, atr):
    """隔天的走勢型態。atr＝前一天的近 10 天平均振幅。回傳 0～4，資料不足為 -1。"""
    import numpy as np
    R = h - l
    with np.errstate(all="ignore"):
        body = (c - o) / R
        uw = (h - np.maximum(o, c)) / R
        lw = (np.minimum(o, c) - l) / R
        narrow = (R / ref) < 0.6 * atr
    y = np.where(uw >= lw, 2, 3)
    y = np.where(body >= 0.5, 0, y)
    y = np.where(body <= -0.5, 1, y)
    y = np.where(narrow | ((np.abs(body) < 0.2) & (np.minimum(uw, lw) >= 0.3)), 4, y)
    y = np.where((R > 0) & ~np.isnan(R) & ~np.isnan(atr), y, -1)
    return y


def run(D, FA, keys, val20, min_val, min_price, say=None):
    import numpy as np
    import lightgbm as lgb
    T, codes = D.T, D.codes
    N = len(codes)
    K = len(keys)
    ki = {k: j for j, k in enumerate(keys)}
    arr = lambda f: np.array([[np.nan if x is None else x for x in D.raw[c][f]] for c in codes], dtype=np.float64)
    o, h, l, c, ref = arr("o"), arr("h"), arr("l"), arr("c"), arr("ref")
    F = np.full((N, T, K), np.nan, dtype=np.float32)
    for i in range(N):
        if FA[i] is None:
            continue
        for k, j in ki.items():
            F[i, :, j] = FA[i][k]
    V = np.array(val20, dtype=np.float64)
    atr = F[:, :, ki["atr10"]].astype(np.float64)
    from util import is_etf
    etf = np.array([is_etf(cd) for cd in codes])
    liq = (V >= min_val) & (c >= min_price) & ~np.isnan(atr) & ~etf[:, None]
    # 隔天的型態、高點／低點（相對開盤，除以近 10 天平均振幅）
    Y = np.full((N, T), -1)
    Y[:, :-1] = label(o[:, 1:], h[:, 1:], l[:, 1:], c[:, 1:], ref[:, 1:], atr[:, :-1])
    with np.errstate(all="ignore"):
        UP = np.c_[(h[:, 1:] / o[:, 1:] - 1) / atr[:, :-1], np.full(N, np.nan)]
        DN = np.c_[(1 - l[:, 1:] / o[:, 1:]) / atr[:, :-1], np.full(N, np.nan)]
    tx = np.array([np.nan if x is None else x for x in D.mkt["taiex"]])
    mret = np.r_[np.nan, tx[1:] / tx[:-1] - 1]

    def rank(x):
        r = np.full(x.shape, np.nan)
        m = ~np.isnan(x)
        if m.sum() > 1:
            r[m] = (np.argsort(np.argsort(x[m])) + 0.5) / m.sum()
        return r
    fnames = ["r:" + k for k in keys] + ["v:" + k for k in FEATS_RAW] + ["m:ret", "m:clv"]

    def feats(t):
        idx = np.where(liq[:, t])[0]
        X = [rank(F[idx, t, j]) for j in range(K)]
        X += [F[idx, t, ki[k]] for k in FEATS_RAW]
        X += [np.full(len(idx), mret[t]), np.full(len(idx), np.nanmean(F[idx, t, ki["clv"]]) if len(idx) else np.nan)]
        return idx, np.array(X, dtype=np.float32).T
    start = max(30, T - 1 - TRACK - TRAIN - 5)
    rows = {t: feats(t) for t in range(start, T)}
    last = T - 1

    # ---- 走勢型態：walk-forward
    track = []
    today = None
    model, lf, base = None, -10 ** 9, None
    for t in range(start + TRAIN, T):
        if model is None or t - lf >= REFIT or t == last:
            tr = range(t - TRAIN, t)          # 第 u 天的答案（u+1 天的 K 棒）在第 t 天收盤時已知
            Xs = np.concatenate([rows[u][1] for u in tr])
            ys = np.concatenate([Y[rows[u][0], u] for u in tr])
            m = ys >= 0
            if m.sum() < 5000:
                continue
            model = lgb.train(SHAPE_PARAMS, lgb.Dataset(Xs[m], ys[m]), 80)
            lf = t
            base = np.bincount(ys[m], minlength=5) / m.sum()
        idx, X = rows[t]
        if not len(idx):
            continue
        p = model.predict(X)
        if t < last:
            y = Y[idx, t]
            mk = y >= 0
            track.append((p[mk], y[mk]))
        else:
            today = (idx, X, p, base)
    if model is None or not track or today is None:
        return None
    track = track[-TRACK:]
    P = np.concatenate([x[0] for x in track])
    Yt = np.concatenate([x[1] for x in track])
    am = P.argmax(1)
    rule = {}
    for k in range(5):
        b = float(np.mean(Yt == k))
        best = None
        for th in np.arange(0.30, 0.551, 0.025):
            sel = (am == k) & (P[:, k] >= th)
            n = int(sel.sum())
            if n < MIN_N:
                break
            prec = float(np.mean(Yt[sel] == k))
            if prec >= max(b + LIFT_ABS, b * LIFT_REL):
                best = {"th": round(float(th), 3), "prec": round(prec, 4), "n": n, "base": round(b, 4),
                        "per_day": round(n / len(track), 1)}
                break
        rule[NAMES[k]] = best or {"th": None, "base": round(b, 4)}

    # ---- 高點／低點範圍：分位數迴歸（今天的模型＋過去 100 天每 20 天重估一次的涵蓋率）
    def fit_q(t):
        tr = range(t - TRAIN, t)
        Xs = np.concatenate([rows[u][1] for u in tr])
        us = np.concatenate([UP[rows[u][0], u] for u in tr])
        ds = np.concatenate([DN[rows[u][0], u] for u in tr])
        m = ~np.isnan(us) & ~np.isnan(ds) & (np.abs(us) < 20) & (np.abs(ds) < 20)
        out = {}
        for q in (0.1, 0.5, 0.9):
            out[("u", q)] = lgb.train(dict(Q_PARAMS, alpha=q), lgb.Dataset(Xs[m], us[m]), 100)
            out[("d", q)] = lgb.train(dict(Q_PARAMS, alpha=q), lgb.Dataset(Xs[m], ds[m]), 100)
        return out
    cov_u, cov_d, nq = 0, 0, 0
    qm = None
    for t in range(last - TRACK, last):
        if t < start + TRAIN:
            continue
        if qm is None or (t - (last - TRACK)) % 20 == 0:
            qm = fit_q(t)
        idx, X = rows[t]
        u, d = UP[idx, t], DN[idx, t]
        mk = ~np.isnan(u) & ~np.isnan(d)
        if not mk.any():
            continue
        lo_u, hi_u = qm[("u", 0.1)].predict(X[mk]), qm[("u", 0.9)].predict(X[mk])
        lo_d, hi_d = qm[("d", 0.1)].predict(X[mk]), qm[("d", 0.9)].predict(X[mk])
        cov_u += int(np.sum((u[mk] >= lo_u) & (u[mk] <= hi_u)))
        cov_d += int(np.sum((d[mk] >= lo_d) & (d[mk] <= hi_d)))
        nq += int(mk.sum())
    qm = fit_q(last)
    idx, X, p, base = today
    a = atr[idx, last]
    qs = {key: m_.predict(X) for key, m_ in qm.items()}
    contrib = model.predict(X, pred_contrib=True)      # 每個條件對每一種型態的貢獻（用來寫依據）
    nf = X.shape[1] + 1
    out = {}
    for j, i in enumerate(idx.tolist()):
        k = int(p[j].argmax())
        r = rule[NAMES[k]]
        sh = None
        if r.get("th") is not None and p[j, k] >= r["th"]:
            cc = contrib[j, k * nf:(k + 1) * nf - 1]
            top = [fnames[f] for f in np.argsort(-cc)[:4] if cc[f] > 0][:2]
            sh = {"k": NAMES[k], "p": round(float(p[j, k]), 3), "prec": r["prec"], "base": r["base"], "f": top}
        up = sorted(max(0.0, float(qs[("u", q)][j]) * float(a[j])) for q in (0.1, 0.5, 0.9))
        dn = sorted(max(0.0, float(qs[("d", q)][j]) * float(a[j])) for q in (0.1, 0.5, 0.9))
        out[i] = {"sh": sh, "dist": [round(float(x), 3) for x in p[j]], "up": [round(x, 4) for x in up],
                  "dn": [round(x, 4) for x in dn]}
    summary = {"mret": None if np.isnan(mret[last]) else float(mret[last]), "rule": rule, "days": len(track), "names": NAMES,
               "cov_up": round(cov_u / nq, 4) if nq else None, "cov_dn": round(cov_d / nq, 4) if nq else None,
               "base_today": [round(float(x), 4) for x in base]}
    if say:
        say("當沖走勢型態：完成")
    return out, summary


def why_text(f, FA_i, t, reason, mret_t=None):
    """把影響最大的條件轉成白話依據。"""
    out = []
    for name in f:
        kind, k = name.split(":")
        if kind == "m":
            if k == "ret" and mret_t is not None and mret_t == mret_t:
                out.append("今天大盤%s %.1f%%" % ("上漲" if mret_t >= 0 else "下跌", abs(mret_t) * 100))
            continue
        v = FA_i[k][t] if FA_i and k in FA_i else None
        txt = reason(k, v, 0)
        if txt and txt not in out:
            out.append(txt)
    return out
