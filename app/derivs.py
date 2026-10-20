# -*- coding: utf-8 -*-
"""權證與期貨評估。"""
import datetime as dt
import math
import os

from util import DB, parse_ymd, read_json

R_FREE = 0.015
NAN = float("nan")


# ====================================================================== Black-Scholes

def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _npdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def bs(S, K, T, sig, call=True, r=R_FREE):
    if T <= 0 or sig <= 0:
        return max(0.0, (S - K) if call else (K - S)), (1.0 if (call and S > K) else (-1.0 if (not call and S < K) else 0.0)), 0.0
    sq = sig * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sig * sig) * T) / sq
    d2 = d1 - sq
    if call:
        price = S * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d2)
        delta = _ncdf(d1)
        theta = -S * _npdf(d1) * sig / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * _ncdf(d2)
    else:
        price = K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1)
        delta = _ncdf(d1) - 1
        theta = -S * _npdf(d1) * sig / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * _ncdf(-d2)
    return price, delta, theta / 365.0


def implied_vol(price, S, K, T, call):
    intrinsic = max(0.0, (S - K) if call else (K - S))
    if price <= intrinsic * 1.0001 or T <= 0:
        return None
    lo, hi = 0.01, 4.0
    if bs(S, K, T, hi, call)[0] < price:
        return None
    for _ in range(50):
        mid = (lo + hi) / 2
        if bs(S, K, T, mid, call)[0] > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-4:
            break
    return (lo + hi) / 2


def hist_vol(A, n=60):
    rets = []
    for t in range(max(1, len(A) - n), len(A)):
        a0, a1 = A[t - 1], A[t]
        if a0 == a0 and a1 == a1 and a0 > 0:
            rets.append(math.log(a1 / a0))
    if len(rets) < 20:
        return None
    m = sum(rets) / len(rets)
    return math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1) * 252)


# ====================================================================== 權證

def _lin(x, pts):
    """分段線性：pts = [(x0,y0),(x1,y1),...]（x 遞增）"""
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def evaluate_warrants(day, hv_of, score_of, name_to_code):
    """hv_of(code)->年化歷史波動；score_of(code)->(短,中,長)分數 或 None"""
    snap = read_json(os.path.join(DB, "snapshot", "warrants.json.gz"), {}) or {}
    ws = snap.get("w", {})
    if not ws:
        return {}, []
    today = parse_ymd(day)
    rows = []
    for code, w in ws.items():
        call = w.get("t") == "C"
        S = w.get("s")
        K = w.get("k")
        ratio = w.get("r")
        u = w.get("u") or name_to_code.get(w.get("un", ""), "")
        if not (S and K and ratio and S > 0 and K > 0 and ratio > 0):
            continue
        b, a, c = w.get("b"), w.get("a"), w.get("c")
        b = b if b and b > 0 else None
        a = a if a and a > 0 else None
        if b and a:
            P = (a + b) / 2
        else:
            P = c or a or b
        if not P or P <= 0:
            continue
        days = (parse_ymd(w["last"]) - today).days
        if days <= 0:
            continue
        Ty = days / 365.0
        iv = implied_vol(P / ratio, S, K, Ty, call)
        hv = hv_of(u)
        sig = iv or hv or 0.4
        _, delta, theta = bs(S, K, Ty, sig, call)
        lev = abs(delta) * S * ratio / P
        theta_pct = (theta * ratio / P) if P else 0  # 每日損耗（佔價格比例，負值）
        money = (S / K - 1) if call else (K / S - 1)  # >0 價內
        spread = ((a - b) / a) if (a and b) else None
        rows.append({
            "c": code, "n": w.get("n"), "t": "C" if call else "P", "u": u, "un": w.get("un"),
            "S": S, "K": K, "r": ratio, "P": round(P, 3), "b": b, "a": a, "v": int((w.get("v") or 0) / 1000),
            "days": days, "last": w["last"], "iv": iv, "hv": hv, "delta": delta,
            "lev": lev, "theta": theta_pct, "money": money, "spread": spread,
            "cat": w.get("cat", ""), "lp": w.get("lp", ""),
        })
    # 同標的同方向的隱含波動排名（越低越便宜）
    groups = {}
    for r in rows:
        if r["iv"]:
            groups.setdefault((r["u"], r["t"]), []).append(r)
    for g in groups.values():
        g.sort(key=lambda r: r["iv"])
        n = len(g)
        for j, r in enumerate(g):
            r["iv_rank"] = 1 - j / max(1, n - 1) if n > 1 else 0.5
    for r in rows:
        r["q"], r["why"] = quality(r)
        sc = score_of(r["u"])
        r["us"] = sc
        fit = None
        if sc and sc[1] is not None:
            m = (sc[0] + 2 * sc[1]) / 3 if sc[0] is not None else sc[1]
            fit = (m - 50) / 50 if r["t"] == "C" else (50 - m) / 50
        r["fit"] = fit
        r["rec"] = round(r["q"] * (0.5 + 0.5 * max(0.0, min(1.0, fit if fit is not None else 0))), 1)
    by_u = {}
    for r in rows:
        by_u.setdefault(r["u"], []).append(r)
    out = {}
    for u, lst in by_u.items():
        calls = sorted([r for r in lst if r["t"] == "C"], key=lambda r: -r["q"])[:40]
        puts = sorted([r for r in lst if r["t"] == "P"], key=lambda r: -r["q"])[:40]
        out[u] = {"calls": [_slim(r) for r in calls], "puts": [_slim(r) for r in puts],
                  "n_call": sum(1 for r in lst if r["t"] == "C"), "n_put": sum(1 for r in lst if r["t"] == "P")}
    picks = [r for r in rows if r["q"] >= 60 and r["fit"] is not None and r["fit"] >= 0.3 and r["v"] > 0]
    picks.sort(key=lambda r: -r["rec"])
    seen = set()
    top = []
    for r in picks:
        key = (r["u"], r["t"])
        if key in seen:
            continue
        seen.add(key)
        top.append(_slim(r))
        if len(top) >= 40:
            break
    return out, top


def quality(r):
    why = []
    # 1. 價格合理（隱含波動相對歷史波動、相對同標的其他權證）
    if r["iv"] and r["hv"]:
        ratio = r["iv"] / r["hv"]
        s1 = _lin(ratio, [(0.8, 100), (1.1, 85), (1.5, 50), (2.2, 10)])
        s1 = 0.6 * s1 + 0.4 * (r.get("iv_rank", 0.5) * 100)
        if ratio < 1.1:
            why.append("價格合理偏便宜（權證價格反映的波動 %.0f%%，跟股票實際波動 %.0f%% 差不多）" % (r["iv"] * 100, r["hv"] * 100))
        elif ratio > 1.6:
            why.append("價格偏貴（權證價格反映的波動比股票實際波動高 %.0f%%）" % ((ratio - 1) * 100))
    elif r["iv"]:
        s1 = r.get("iv_rank", 0.5) * 100
    else:
        s1 = 30
        why.append("價格資訊不足，無法判斷貴不貴")
    # 2. 買賣價差
    if r["spread"] is None:
        s2 = 15
        why.append("目前沒有完整的買賣報價")
    else:
        s2 = _lin(r["spread"], [(0.01, 100), (0.03, 75), (0.06, 40), (0.12, 0)])
        if r["spread"] > 0.06:
            why.append("買價賣價差太多（%.1f%%），一買一賣就先虧" % (r["spread"] * 100))
    # 3. 剩餘天數
    s3 = _lin(r["days"], [(15, 0), (45, 50), (90, 90), (150, 100), (360, 90)])
    if r["days"] < 45:
        why.append("只剩 %d 天到期，價值會掉得很快" % r["days"])
    # 4. 價內外程度：略價外到價平最有效率
    s4 = _lin(r["money"], [(-0.35, 5), (-0.20, 45), (-0.10, 90), (0.0, 100), (0.10, 85), (0.25, 55)])
    if r["money"] < -0.2:
        why.append("離履約價還很遠（差 %.0f%%），股價要大漲（跌）才有價值" % (-r["money"] * 100))
    # 5. 每日時間價值損耗
    s5 = _lin(-r["theta"], [(0.003, 100), (0.01, 70), (0.02, 35), (0.04, 0)])
    # 6. 槓桿
    s6 = _lin(r["lev"], [(1.5, 20), (3, 80), (5, 100), (9, 90), (15, 50), (25, 20)])
    q = 0.25 * s1 + 0.20 * s2 + 0.15 * s3 + 0.15 * s4 + 0.15 * s5 + 0.10 * s6
    if len(why) < 2:
        good = []
        if r["spread"] is not None and r["spread"] <= 0.015:
            good.append("買價賣價很接近（只差 %.1f%%）" % (r["spread"] * 100))
        if r["days"] >= 90:
            good.append("還有 %d 天才到期，時間充裕" % r["days"])
        if -0.12 <= r["money"] <= 0.05:
            good.append("履約價接近現在股價，跟著股價動得靈敏")
        if 3 <= r["lev"] <= 9:
            good.append("槓桿 %.1f 倍，不會太大或太小" % r["lev"])
        if -r["theta"] <= 0.005:
            good.append("每天的時間耗損少")
        why.extend(good[:3 - len(why)])
    if not why:
        why.append("各方面條件都還可以")
    return round(q, 1), why


def _slim(r):
    def rd(x, d):
        return None if x is None else round(x, d)
    return {"c": r["c"], "n": r["n"], "t": r["t"], "u": r["u"], "un": r["un"], "S": r["S"], "K": rd(r["K"], 2),
            "r": rd(r["r"], 4), "P": r["P"], "b": r["b"], "a": r["a"], "v": r["v"], "days": r["days"],
            "iv": rd(r["iv"], 3), "hv": rd(r["hv"], 3), "lev": rd(r["lev"], 1), "theta": rd(r["theta"], 4),
            "money": rd(r["money"], 3), "spread": rd(r["spread"], 3), "q": r["q"], "rec": r["rec"],
            "why": r["why"], "us": r.get("us"), "delta": rd(r["delta"], 3)}


# ====================================================================== 期貨

INDEX_FUT = [("TX", "臺股期貨（大台）"), ("MTX", "小型臺指（小台）"), ("TMF", "微型臺指"),
             ("TE", "電子期貨"), ("TF", "金融期貨"), ("XIF", "非金電期貨"), ("G2F", "富櫃200期貨")]


def evaluate_futures(D, mkt, score_of, close_of):
    T = D.T
    last = T - 1
    lastfut = D.fut.get(last) or {}
    prevfut = D.fut.get(last - 1) or {}
    from engine import front_month
    idx = []
    for cid, name in INDEX_FUT:
        recs = lastfut.get(cid)
        if not recs:
            continue
        fm = front_month(recs)
        prev = front_month(prevfut.get(cid) or []) if prevfut.get(cid) else None
        chg = None
        if prev and prev[4] and fm[4] and prev[0] == fm[0]:
            chg = fm[4] / prev[4] - 1
        idx.append({"c": cid, "n": name, "month": fm[0], "close": fm[4], "settle": fm[6], "vol": fm[5],
                    "oi": sum((r[7] or 0) for r in recs), "chg": chg})
    sf = read_json(os.path.join(DB, "snapshot", "stockfut.json"), {}) or {}
    stock_rows = []
    for fcode, info in sf.items():
        recs = lastfut.get(fcode)
        if not recs:
            continue
        fm = front_month(recs)
        stock = info["stock"]
        spot = close_of(stock)
        sc = score_of(stock)
        basis = (fm[4] / spot - 1) if (fm[4] and spot) else None
        prev = prevfut.get(fcode)
        oi_now = sum((r[7] or 0) for r in recs)
        oi_prev = sum((r[7] or 0) for r in prev) if prev else None
        stock_rows.append({"c": fcode, "stock": stock, "n": info["name"], "month": fm[0], "close": fm[4],
                           "vol": fm[5], "oi": oi_now, "oi_chg": (oi_now - oi_prev) if oi_prev is not None else None,
                           "spot": spot, "basis": round(basis, 4) if basis is not None else None, "s": sc})
    stock_rows.sort(key=lambda r: -(r["vol"] or 0))
    # 外資與三大法人台指期留倉
    inst = []
    for d in D.days[-20:]:
        x = D.txf.get(d)
        if x:
            inst.append({"d": d, "foreign": x.get("foreign", [None, None])[1],
                         "trust": x.get("trust", [None, None])[1], "dealer": x.get("dealer", [None, None])[1]})
    return {"index": idx, "stock": stock_rows, "inst": inst, "market": {
        hn: mkt["horizons"][hn] for hn in mkt["horizons"]}}
