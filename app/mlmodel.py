# -*- coding: utf-8 -*-
"""機器學習（LightGBM）輔助模型。

做法：每隔 15 個交易日，用「之前約 250 個交易日、結果已經揭曉」的資料重新訓練一次，
預測每天每檔股票之後的報酬排名，再和原本的加權分數「各占一半」合併。
全程只用當時已知的資料（walk-forward）。用兩年資料實測，合併後比單用加權分數準。

需要 numpy 與 lightgbm；沒有安裝時自動略過，只用原本的加權分數。
"""

RETRAIN = 15
TRAIN_DAYS = 250
MIN_TRAIN = 40


def available():
    try:
        import numpy  # noqa: F401
        import lightgbm  # noqa: F401
        return True
    except Exception:
        return False


def _rank01(vals):
    """vals: list of (value, key) → {key: (0,1] 的排名}"""
    vals = sorted(vals, key=lambda p: p[0])
    n = len(vals)
    out = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and vals[j + 1][0] == vals[i][0]:
            j += 1
        r = ((i + j) / 2.0 + 1) / n
        for k in range(i, j + 1):
            out[vals[k][1]] = r
        i = j + 1
    return out


def blend(store, fstore, pct_hist, H, keys, say=None):
    """就地修改 pct_hist（加權分數 → 加權分數與機器學習各半），回傳各期間的實測比較。"""
    import numpy as np
    import lightgbm as lgb
    days = sorted(store)
    report = {}
    for hn, h in H.items():
        cache = {}

        def X_of(t):
            if t not in cache:
                alive, Rk = store[t]
                X = np.array([Rk[k] for k in keys], dtype=np.float32).T
                y = fstore.get((t, hn))
                cache[t] = (alive, X, None if y is None else np.array(y, dtype=np.float32))
            return cache[t]

        model, last_train = None, -10 ** 9
        ic_lin, ic_mix = [], []
        for t in days:
            if model is None or t - last_train >= RETRAIN:
                tr = [u for u in days if t - h - TRAIN_DAYS <= u <= t - h and (u, hn) in fstore][::2]
                if len(tr) >= MIN_TRAIN:
                    Xs, Ys = [], []
                    for u in tr:
                        _, X, y = X_of(u)
                        m = ~np.isnan(y)
                        Xs.append(X[m])
                        Ys.append(y[m])
                    model = lgb.LGBMRegressor(n_estimators=150, learning_rate=0.03, num_leaves=15,
                                              min_child_samples=200, subsample=0.7, subsample_freq=1,
                                              colsample_bytree=0.7, reg_lambda=5.0, verbose=-1, n_jobs=2)
                    model.fit(np.vstack(Xs), np.concatenate(Ys))
                    last_train = t
                    if say:
                        say("機器學習模型：%s 第 %d 天重新訓練" % (hn, t))
            if model is None:
                continue
            alive, X, y = X_of(t)
            pred = model.predict(X)
            lin = pct_hist[hn].get(t)
            if not lin:
                continue
            mlr = _rank01([(float(p), i) for p, i in zip(pred, alive)])
            comb = [((lin.get(i, 0.5) + mlr[i]) / 2, i) for i in alive]
            newp = _rank01(comb)
            if y is not None:
                m = ~np.isnan(y)
                if m.sum() >= 100:
                    yy = y[m]
                    a = np.array([lin.get(i, 0.5) for i in alive], dtype=np.float64)[m]
                    b = np.array([newp[i] for i in alive], dtype=np.float64)[m]
                    ic_lin.append(float(np.corrcoef(a, yy)[0, 1]))
                    ic_mix.append(float(np.corrcoef(b, yy)[0, 1]))
            pct_hist[hn][t] = newp
        report[hn] = {"n": len(ic_lin),
                      "ic_lin": round(sum(ic_lin) / len(ic_lin), 4) if ic_lin else None,
                      "ic_mix": round(sum(ic_mix) / len(ic_mix), 4) if ic_mix else None,
                      "better": round(sum(1 for a, b in zip(ic_lin, ic_mix) if b > a) / len(ic_lin), 3) if ic_lin else None}
        cache.clear()
    return report
