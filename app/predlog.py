# -*- coding: utf-8 -*-
"""前瞻實測：每天把「當天收盤後的預測」原封不動存下來，之後再用真正的行情對答案。

和回測不同，這些預測在存檔當下完全不知道未來，也不會因為之後換模型而改變，
所以是判斷模型有沒有真的進步最公正的依據。
"""
import os

from util import DB, read_json, write_json

LOG_DIR = os.path.join(DB, "predlog")
H = {"short": 5, "mid": 20, "long": 60}
COST = 0.001425 * 2 * 0.6 + 0.0015


def isnan(x):
    return x is None or x != x


def save(D, res, stocks, dt, sectors=None):
    day = D.days[-1]
    path = os.path.join(LOG_DIR, day + ".json.gz")
    # 同一天收盤後可以更新預測（例如晚上補上融資資料、早上補上美股收盤），
    # 但下一個交易日 9:00 開盤之後就不再改，確保紀錄是「事前」的
    from util import now_tw
    now = now_tw()
    if os.path.exists(path) and now.strftime("%Y%m%d") > day and now.weekday() < 5 and now.hour >= 9:
        return
    pct_hist = res.get("pct_hist") or {}
    last = D.T - 1
    liquid = {r["c"] for r in stocks if not r.get("etf") and (r.get("val") or 0) >= 0.05}
    pct = {}
    for hn in H:
        p = pct_hist.get(hn, {}).get(last) or {}
        pct[hn] = {D.codes[i]: round(v, 3) for i, v in p.items() if D.codes[i] in liquid}
    obj = {
        "day": day, "engine": res.get("model", {}).get("version"),
        "mkt": {hn: res["market"]["horizons"][hn]["score"] for hn in H},
        "pct": pct,
        "score": {r["c"]: r["s"] for r in stocks if r.get("s")},
        "sec": {s["ind"]: s["s"] for s in (sectors or [])},
        "dt": {"long": [r["c"] for r in (dt or {}).get("long", []) if r.get("ok")],
               "short": [r["c"] for r in (dt or {}).get("short", []) if r.get("ok")],
               "long_all": [r["c"] for r in (dt or {}).get("long", [])[:10]],
               "short_all": [r["c"] for r in (dt or {}).get("short", [])[:10]]},
    }
    write_json(path, obj, gz=True)


def _rank(vals):
    vals = sorted(vals)
    n = len(vals)
    out = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and vals[j + 1][0] == vals[i][0]:
            j += 1
        r = (i + j) / 2.0 / max(1, n - 1)
        for k in range(i, j + 1):
            out[vals[k][1]] = r
        i = j + 1
    return out


def _corr(a, b):
    n = len(a)
    if n < 30:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    sab = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    saa = sum((x - ma) ** 2 for x in a)
    sbb = sum((y - mb) ** 2 for y in b)
    if saa <= 0 or sbb <= 0:
        return None
    return sab / (saa * sbb) ** 0.5


def evaluate(D, A_all):
    """用目前的行情，替所有已存的預測對答案。"""
    if not os.path.isdir(LOG_DIR):
        return {"start": None, "days": 0}
    files = sorted(f[:8] for f in os.listdir(LOG_DIR) if f.endswith(".json.gz"))
    pos = {d: t for t, d in enumerate(D.days)}
    last = D.T - 1
    tx = D.mkt["taiex"]
    out = {"start": files[0] if files else None, "days": len(files), "h": {}, "mkt": {}, "dt": {}}
    rows = {hn: [] for hn in H}
    mrows = {hn: [] for hn in H}
    dtrows = {"long": [], "short": []}
    for d in files:
        t0 = pos.get(d)
        if t0 is None:
            continue
        P = read_json(os.path.join(LOG_DIR, d + ".json.gz"), {}) or {}
        for hn, h in H.items():
            if t0 + h > last:
                continue
            p = (P.get("pct") or {}).get(hn) or {}
            xs, rs = [], []
            for c, v in p.items():
                i = D.idx.get(c)
                if i is None:
                    continue
                a0, a1 = A_all[i][t0], A_all[i][t0 + h]
                if isnan(a0) or isnan(a1) or a0 <= 0:
                    continue
                xs.append(v)
                rs.append(a1 / a0 - 1)
            if len(xs) >= 100:
                rr = _rank([(r, k) for k, r in enumerate(rs)])
                ic = _corr(xs, [rr[k] for k in range(len(rs))])
                order = sorted(range(len(xs)), key=lambda k: xs[k])
                n5 = len(order) // 5
                top = [rs[k] for k in order[-n5:]]
                bot = [rs[k] for k in order[:n5]]
                rows[hn].append({"d": d, "ic": ic, "spread": sum(top) / n5 - sum(bot) / n5,
                                 "top_up": sum(1 for x in top if x > 0) / n5, "all_up": sum(1 for x in rs if x > 0) / len(rs)})
            ms = (P.get("mkt") or {}).get(hn)
            if ms is not None and not isnan(tx[t0]) and not isnan(tx[t0 + h]):
                mrows[hn].append({"d": d, "s": ms, "r": tx[t0 + h] / tx[t0] - 1})
        if t0 + 1 <= last:
            for side, sign in (("long", 1), ("short", -1)):
                picks = (P.get("dt") or {}).get(side) or []
                rr = []
                for c in picks:
                    s = D.raw.get(c)
                    if not s:
                        continue
                    o, cl = s["o"][t0 + 1], s["c"][t0 + 1]
                    if isnan(o) or isnan(cl) or o <= 0:
                        continue
                    rr.append(sign * (cl / o - 1) - COST)
                if rr:
                    dtrows[side].append({"d": d, "n": len(rr), "win": sum(1 for x in rr if x > 0), "sum": sum(rr)})
    for hn in H:
        rs = rows[hn]
        if rs:
            ics = [r["ic"] for r in rs if r["ic"] is not None]
            out["h"][hn] = {"n": len(rs), "ic": round(sum(ics) / len(ics), 4) if ics else None,
                            "spread": round(sum(r["spread"] for r in rs) / len(rs), 5),
                            "win": round(sum(1 for r in rs if r["spread"] > 0) / len(rs), 4),
                            "top_up": round(sum(r["top_up"] for r in rs) / len(rs), 4),
                            "all_up": round(sum(r["all_up"] for r in rs) / len(rs), 4),
                            "rows": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in rs[-120:]]}
        else:
            out["h"][hn] = {"n": 0}
        ms = mrows[hn]
        calls = [m for m in ms if m["s"] >= 55 or m["s"] <= 45]
        hit = sum(1 for m in calls if (m["s"] >= 55) == (m["r"] > 0))
        out["mkt"][hn] = {"n": len(ms), "calls": len(calls), "hit": round(hit / len(calls), 4) if calls else None,
                          "base_up": round(sum(1 for m in ms if m["r"] > 0) / len(ms), 4) if ms else None}
    for side in ("long", "short"):
        rs = dtrows[side]
        n = sum(r["n"] for r in rs)
        out["dt"][side] = {"days": len(rs), "n": n, "win": round(sum(r["win"] for r in rs) / n, 4) if n else None,
                           "avg": round(sum(r["sum"] for r in rs) / n, 5) if n else None}
    return out
