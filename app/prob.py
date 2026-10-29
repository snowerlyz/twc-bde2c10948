# -*- coding: utf-8 -*-
"""每檔股票「跑贏加權指數」與「上漲」的機率（逐檔計算，不是同一組共用一個數字）。

做法（全程只用當時已知的資料，walk-forward）：
1. 每檔股票的條件：綜合分數排名、和加權指數的連動（beta、相關係數）、
   近 3 個月比加權指數多漲多少、成交金額大小。
2. 用「之前約 250 個交易日、結果已經揭曉」的資料做邏輯迴歸，估計每檔跑贏加權指數、上漲的機率；
   每 10 個交易日重新估一次。
3. 實測發現模型對極端值太有自信（大盤主導的行情會突然轉向），所以把機率往「過去平均」收斂：
   短中期保留 70%、長期保留 50% 的差距。（兩年 walk-forward 實測，收斂後的預測最接近實際結果）
4. 「預期比大盤」：取過去條件相近那一組股票「比加權指數多賺多少」的分布形狀，平移到跑贏機率＝這檔的機率，
   再取中間值（所以機率低於 50% 時一定是少賺，兩個數字一致）；停損／目標參考是同一組報酬的 20%／80% 位置（同樣平移）。

需要 numpy；沒有安裝時回傳 None，評價改用原本的分組統計。
"""

H = {"short": 5, "mid": 20, "long": 60}
TRAIN_DAYS = 250
MIN_TRAIN = 40
REFIT = 10
SHRINK = {"short": 0.7, "mid": 0.7, "long": 0.5}
NBIN = 10
import os
# 研究開關：額外條件（逗號列出 ivol、max），預設不開
EXTRA = set(x for x in os.environ.get("TWC_PB_EXTRA", "").split(",") if x)


def available():
    try:
        import numpy  # noqa: F401
        return True
    except Exception:
        return False


def _irls(X, y, l2=1.0, it=25):
    import numpy as np
    Z = np.c_[np.ones(len(X)), X]
    w = np.zeros(Z.shape[1])
    reg = l2 * np.diag(np.r_[0.0, np.ones(Z.shape[1] - 1)])
    for _ in range(it):
        p = 1.0 / (1.0 + np.exp(-np.clip(Z @ w, -30, 30)))
        g = Z.T @ (p - y) + reg @ w
        Hm = (Z * (p * (1 - p))[:, None]).T @ Z + reg
        step = np.linalg.solve(Hm, g)
        w -= step
        if np.abs(step).max() < 1e-6:
            break
    return w


def build(D, A_all, pct_hist, v20, min_val, say=None):
    """回傳 {期間: {"pb": {t: {i: 機率}}, "today": {i: {...}}, "track": {...}}}。"""
    import numpy as np
    N, T = len(A_all), len(A_all[0])
    A = np.array([list(a) for a in A_all], dtype=np.float64)
    tx = np.array([np.nan if x is None else x for x in D.mkt["taiex"]], dtype=np.float64)
    V = np.array(v20, dtype=np.float64)
    with np.errstate(all="ignore"):
        ra = np.log(A[:, 1:] / A[:, :-1])
        rt = np.log(tx[1:] / tx[:-1])
    days = sorted(set().union(*[set(pct_hist.get(hn) or {}) for hn in H]))
    if not days:
        return None
    last = T - 1

    # ---- 每天每檔的條件（和加權指數的連動、近 3 個月相對強弱、成交金額）
    ext = {}
    for t in days:
        w = slice(max(0, t - 60), t)
        x = ra[:, w]
        m = rt[w]
        with np.errstate(all="ignore"):
            ok = ~np.isnan(x) & ~np.isnan(m)[None, :]
            n = ok.sum(1)
            xm = np.where(ok, x, 0.0)
            mm = np.where(ok, m[None, :], 0.0)
            mx = xm.sum(1) / np.maximum(n, 1)
            my = mm.sum(1) / np.maximum(n, 1)
            dx = np.where(ok, x - mx[:, None], 0.0)
            dy = np.where(ok, m[None, :] - my[:, None], 0.0)
            cov = (dx * dy).sum(1)
            vy = (dy * dy).sum(1)
            vx = (dx * dx).sum(1)
            beta = np.where((vy > 0) & (n >= 20), cov / np.where(vy > 0, vy, 1), np.nan)
            corr = np.where((vy > 0) & (vx > 0) & (n >= 20), cov / np.sqrt(np.where(vx * vy > 0, vx * vy, 1)), np.nan)
            rs60 = (np.log(A[:, t] / A[:, t - 60]) - np.log(tx[t] / tx[t - 60])) if t >= 60 else np.full(N, np.nan)
            lval = np.log1p(np.nan_to_num(V[:, t]))
        cols = [np.clip(np.nan_to_num(beta, nan=1.0), -1, 3), np.nan_to_num(corr), np.clip(np.nan_to_num(rs60), -1, 1),
                (lval - 18.0) / 2.0]
        if "ivol" in EXTRA:      # 特有波動（扣掉大盤連動後的波動）；文獻：Ang 等 2006，預期越高越差
            with np.errstate(all="ignore"):
                rv = np.where((vy > 0) & (n >= 20), (vx - cov * cov / np.where(vy > 0, vy, 1)) / np.maximum(n, 1), np.nan)
                iv = np.sqrt(np.clip(rv, 0, None))
            cols.append(np.clip(np.nan_to_num(iv * 40.0, nan=1.0), 0, 4))
        if "max" in EXTRA:       # 近 20 天最大單日漲幅（樂透股）；文獻：Bali 等 2011，預期越高越差
            seg = ra[:, max(0, t - 20):t]
            with np.errstate(all="ignore"):
                mx20 = np.where(np.isnan(seg), -np.inf, seg).max(axis=1) if seg.shape[1] else np.full(N, -np.inf)
            cols.append(np.clip(np.where(np.isfinite(mx20), mx20, 0.0) * 10.0, 0, 1.5))
        ext[t] = np.c_[tuple(cols)]

    out = {}
    for hn, h in H.items():
        ph = pct_hist.get(hn) or {}
        rows = {}
        for t in sorted(ph):
            p = ph[t]
            idx = np.fromiter(p.keys(), dtype=np.int64)
            pc = np.fromiter(p.values(), dtype=np.float64)
            X = np.c_[pc - 0.5, ext[t][idx]]
            liq = V[idx, t] >= min_val
            if t + h <= last and not np.isnan(tx[t]) and not np.isnan(tx[t + h]):
                with np.errstate(all="ignore"):
                    r = A[idx, t + h] / A[idx, t] - 1
                ex = r - (tx[t + h] / tx[t] - 1)
            else:
                r = ex = np.full(len(idx), np.nan)
            rows[t] = (idx, X, liq, r, ex)
        known = [t for t in sorted(rows) if t + h <= last]
        pb_hist, today, fit, last_fit = {}, {}, None, -10 ** 9
        trk = []
        for t in sorted(rows):
            if fit is None or t - last_fit >= REFIT:
                tr = [u for u in known if t - h - TRAIN_DAYS < u <= t - h][::2]
                if len(tr) >= MIN_TRAIN:
                    Xs, rs, es = [], [], []
                    for u in tr:
                        idx, X, liq, r, ex = rows[u]
                        mk = liq & ~np.isnan(r) & ~np.isnan(ex)
                        Xs.append(X[mk])
                        rs.append(r[mk])
                        es.append(ex[mk])
                    Xs, rs, es = np.concatenate(Xs), np.concatenate(rs), np.concatenate(es)
                    if len(rs) >= 2000:
                        yb, yu = (es > 0).astype(float), (rs > 0).astype(float)
                        k = SHRINK[hn]
                        f = {}
                        for name, y in (("b", yb), ("u", yu)):
                            w = _irls(Xs, y)
                            base = min(0.99, max(0.01, y.mean()))
                            f[name] = (w, np.log(base / (1 - base)), k)
                        zb = np.c_[np.ones(len(Xs)), Xs] @ f["b"][0]
                        pbt = 1 / (1 + np.exp(-(f["b"][1] + k * (zb - f["b"][1]))))
                        edges = np.quantile(pbt, np.linspace(0, 1, NBIN + 1))
                        bi = np.clip(np.searchsorted(edges, pbt, side="right") - 1, 0, NBIN - 1)
                        stats = []
                        for j in range(NBIN):
                            sel = bi == j
                            if sel.sum() < 30:
                                stats.append(None)
                                continue
                            # 保留這一組「比大盤多賺」和報酬的分布形狀（等距取 199 個位置）
                            qs = np.linspace(0.005, 0.995, 199)
                            stats.append((np.quantile(es[sel], qs), float(np.quantile(rs[sel], 0.2)), float(np.quantile(rs[sel], 0.8))))
                        f["edges"], f["stats"] = edges, stats
                        fit, last_fit = f, t
            if fit is None:
                continue
            idx, X, liq, r, ex = rows[t]
            Z = np.c_[np.ones(len(X)), X]
            prob = {}
            for name in ("b", "u"):
                w, bl, k = fit[name]
                prob[name] = 1 / (1 + np.exp(-(bl + k * (np.clip(Z @ w, -30, 30) - bl))))
            pb_hist[t] = dict(zip(idx.tolist(), prob["b"].tolist()))
            if t + h <= last:
                mk = liq & ~np.isnan(ex)
                trk.append((t, prob["b"][mk], (ex[mk] > 0)))
            if t == last:
                # 預期比大盤、停損／目標參考：取過去條件相近那一組的分布形狀，
                # 再整體平移到「跑贏機率＝這檔的機率」——這樣機率低於 50% 時預期一定是少賺，兩個數字不會矛盾
                qs = np.linspace(0.005, 0.995, 199)
                for j, i in enumerate(idx.tolist()):
                    pbj = float(prob["b"][j])
                    bj = int(np.clip(np.searchsorted(fit["edges"], pbj, side="right") - 1, 0, NBIN - 1))
                    st = fit["stats"][bj] or next((x for x in fit["stats"][::-1] if x), None)
                    if st:
                        eq = st[0]
                        shift = -float(np.interp(1 - pbj, qs, eq))       # 平移後 P(多賺 > 0) = pbj
                        exm = float(np.interp(0.5, qs, eq)) + shift
                        lo_, hi_ = st[1] + shift, st[2] + shift
                    today[i] = {"pb": round(pbj, 3), "pu": round(float(prob["u"][j]), 3),
                                "ex": None if not st else round(exm, 4),
                                "lo": None if not st else round(lo_, 4), "hi": None if not st else round(hi_, 4)}
        # ---- 實測：過去預測的機率和實際結果（最近 120 個已揭曉的交易日）
        track = None
        if trk:
            rec = trk[-120:]
            P = np.concatenate([x[1] for x in rec])
            Y = np.concatenate([x[2] for x in rec])
            bins = []
            for lo, hi in ((0, 0.3), (0.3, 0.4), (0.4, 0.5), (0.5, 1.01)):
                sel = (P >= lo) & (P < hi)
                if sel.sum():
                    bins.append({"lo": lo, "hi": min(hi, 1.0), "n": int(sel.sum()), "pred": round(float(P[sel].mean()), 4),
                                 "real": round(float(Y[sel].mean()), 4)})
            top = []
            for _, p_, y_ in rec:
                if len(p_) >= 50:
                    o = np.argsort(-p_)[: max(1, len(p_) // 10)]
                    top.append(y_[o].mean())
            track = {"days": len(rec), "from": D.days[rec[0][0]], "to": D.days[rec[-1][0]], "bins": bins,
                     "base": round(float(Y.mean()), 4), "brier": round(float(np.mean((P - Y) ** 2)), 4),
                     "brier_base": round(float(np.mean((Y.mean() - Y) ** 2)), 4),
                     "top10": round(float(np.mean(top)), 4) if top else None,
                     "max_today": round(max((x["pb"] for x in today.values()), default=0), 3)}
        out[hn] = {"pb": pb_hist, "today": today, "track": track}
        if say:
            say("跑贏大盤機率：%s 完成" % hn)
    return out
