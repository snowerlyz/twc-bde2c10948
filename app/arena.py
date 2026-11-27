# -*- coding: utf-8 -*-
"""人格競賽（2026-11-27 起，使用者要求「當沖、短線各設定三種人格，以合理但不同的交易邏輯持續交易競爭；
獨立於目前的作業之外；其中必須有每天只操作三個以內標的的人格；設定須對未來有參考價值，選擇不同典型」）。

和 robot.py（正式的兩個機器人帳戶）完全分開：狀態存在 db/arena.json、網頁資料 results/arena.json，
不讀也不改 db/robot.json。撮合規則、費用、公平性（收盤後決定、隔天 9:00 後不改、雲端延遲不補單）
直接沿用 robot.py 的函式，所以成績可以和機器人、彼此公平比較。

六個人格（各 100 萬，規則在開戶前就定好，之後不為了成績調參數；要改就記在研究筆記並註明日期）：
當沖（隔天開盤進場、收盤出場）
- 狙擊手（模型派・集中）：當沖模型勝算最高、且扣成本勝算 ≥55%、平均每筆 ≥0.3% 的，每天最多 3 檔、每檔 1/3；沒達標就空手。
- 追強者（動能派・只看價量）：今天漲 4% 以上、收盤接近最高價、成交量至少是平常 2 倍，依量增倍數挑最多 5 檔，隔天開盤買、收盤賣。
- 接刀客（反轉派・只看價格）：今天跌 5% 以上（含跌停），依跌幅挑最多 5 檔，隔天開盤買、收盤賣。
短線（收盤價買、開盤價賣）
- 精選家（模型派・集中）：短線評價看好中跑贏大盤機率最高、中期評價不是看淡的，每天最多 3 檔、每檔 1/15，持有 5 個交易日；跌 8% 停損。
- 趨勢派（動能派）：股價站上 20 日與 60 日均線且 20 日線在 60 日線之上、距一年高點 5% 內，依 60 天漲幅每天最多 2 檔、每檔 1/20；
  收盤跌破 20 日均線就賣，最多抱 40 個交易日。
- 撿便宜（逆勢・價值派）：近 20 天跌 15% 以上、但長期評價不是看淡且長期分數 60 以上，依跌幅每天最多 3 檔、每檔 1/20；
  賺 10% 停利、賠 12% 停損，最多抱 20 個交易日。
"""
import math
import os

import robot as rb
from util import DB, RESULTS, is_etf, now_tw, read_json, write_json

PATH = os.path.join(DB, "arena.json")
MIN_VAL = 1e8        # 20 日平均成交金額至少 1 億（流動性）
MIN_PX = 10.0
KEEP = 1500

P = [
    {"id": "dt_snipe", "kind": "dt", "name": "狙擊手", "style": "模型派・集中", "max": 3, "slots": 3,
     "line": "只做當沖模型最有把握的 3 檔以內，沒把握就空手",
     "rules": ["每天收盤後看當沖模型，只挑「扣掉成本後賺錢機會 ≥55%、平均每筆 ≥0.3%」的股票，依平均每筆排序，最多 3 檔、每檔約總資產 1/3。",
               "方向跟著模型：模型看漲就先買後賣、看跌就先賣後買；沒有達標的就整天空手。",
               "沒有備選，主單開盤沒成交（例如開在平盤以下不能先賣）就放棄。"]},
    {"id": "dt_mom", "kind": "dt", "name": "追強者", "style": "動能派・只看價量", "max": 5, "slots": 5,
     "line": "追今天放量大漲、收在高點的強勢股，賭隔天繼續強",
     "rules": ["條件：今天漲 4% 以上、收盤在今天高低價的上 40% 以內、成交量至少是近 20 天平均的 2 倍。",
               "依量增倍數排序最多 5 檔，每檔約總資產 1/5；隔天開盤價買進（開盤就漲停則放棄），收盤價賣出。",
               "不看任何模型分數，用來對照「模型是否比簡單規則好」。"]},
    {"id": "dt_rev", "kind": "dt", "name": "接刀客", "style": "反轉派・只看價格", "max": 5, "slots": 5,
     "line": "買今天跌最兇的股票，賭隔天跌深反彈",
     "rules": ["條件：今天跌 5% 以上（含跌停）。",
               "依跌幅排序最多 5 檔，每檔約總資產 1/5；隔天開盤價買進，收盤價賣出。",
               "不看任何模型分數；這是短期反轉（跌多會彈）的典型做法。"]},
    {"id": "st_snipe", "kind": "st", "name": "精選家", "style": "模型派・集中", "max": 3, "slots": 15, "hold": 5, "stop": -0.08,
     "line": "每天只買評分最好的 3 檔以內，抱 5 天",
     "rules": ["每天收盤後從短線評價「建議買／相對看好」的股票中，排除中期評價看淡的，依跑贏大盤機率挑最多 3 檔，每檔約總資產 1/15。",
               "下一個交易日收盤價買進，第 5 個交易日開盤價賣出。",
               "收盤價比買進價跌 8% 以上，下一個交易日開盤停損。"]},
    {"id": "st_trend", "kind": "st", "name": "趨勢派", "style": "動能派", "max": 2, "slots": 20, "hold": 40,
     "line": "只買創高、均線多頭排列的強勢股，趨勢不壞就一直抱",
     "rules": ["條件：收盤價在 20 日與 60 日均線之上、20 日線在 60 日線之上、離一年內最高價不到 5%。",
               "依近 60 天漲幅排序，每天最多新買 2 檔，每檔約總資產 1/20；下一個交易日收盤價買進。",
               "收盤跌破 20 日均線就在下一個交易日開盤賣出；最多抱 40 個交易日。不看模型分數。"]},
    {"id": "st_value", "kind": "st", "name": "撿便宜", "style": "逆勢・價值派", "max": 3, "slots": 20, "hold": 20,
     "stop": -0.12, "take": 0.10,
     "line": "買近期跌很深、但長期評分還不錯的股票，等它回神",
     "rules": ["條件：近 20 個交易日跌 15% 以上，而且長期評價不是看淡、長期分數 60 分以上（長期條件沒有變壞）。",
               "依跌幅排序，每天最多 3 檔，每檔約總資產 1/20；下一個交易日收盤價買進。",
               "賺 10% 停利、賠 12% 停損（收盤判斷、下一個交易日開盤賣），最多抱 20 個交易日。"]},
]
PBY = {p["id"]: p for p in P}


def isnan(x):
    return x is None or x != x


def _sma(x, n, t):
    if t < n - 1:
        return float("nan")
    w = x[t - n + 1:t + 1]
    if any(isnan(v) for v in w):
        return float("nan")
    return sum(w) / n


def _liquid(s, t):
    c = s["c"][t]
    v = _sma(s["val"], 20, t) if s.get("val") else float("nan")
    return not isnan(c) and c >= MIN_PX and not isnan(v) and v >= MIN_VAL


def _universe(D):
    al = getattr(D, "alerts", None) or {}
    disp = al.get("disp") or {}
    t = D.T - 1
    out = []
    for c in D.codes if hasattr(D, "codes") else list(D.raw):
        if is_etf(c) or c in disp:
            continue
        s = D.raw.get(c)
        if s and _liquid(s, t):
            out.append(c)
    return out


def _name(D, c):
    return (getattr(D, "names", None) or {}).get(c, c)


# ====================================================================== 選股（收盤後）

def _pick_dt(pid, D, dt):
    t = D.T - 1
    if pid == "dt_snipe":
        cand = [("B", r) for r in (dt or {}).get("long", [])] + [("S", r) for r in (dt or {}).get("short", [])]
        cand = [x for x in cand if x[1].get("win", 0) >= 0.55 and x[1].get("avg", 0) >= 0.003]
        cand.sort(key=lambda x: -x[1]["avg"])
        return [(side, r["c"], r.get("n") or r["c"], "%s：扣成本後勝算 %.0f%%、平均每筆 %+.2f%%" % (
            "先買後賣" if side == "B" else "先賣後買", r["win"] * 100, r["avg"] * 100)) for side, r in cand[:3]]
    out = []
    for c in _universe(D):
        s = D.raw[c]
        cl, ref, hi, lo, v = s["c"][t], s["ref"][t], s["h"][t], s["l"][t], s.get("v")
        if isnan(ref) or ref <= 0 or isnan(cl):
            continue
        r1 = cl / ref - 1
        if pid == "dt_mom":
            if r1 < 0.04 or isnan(hi) or isnan(lo) or hi <= lo or not v:
                continue
            clv = (cl - lo) / (hi - lo)
            v20 = _sma(v, 20, t - 1) if t >= 1 else float("nan")
            if clv < 0.6 or isnan(v20) or v20 <= 0 or v[t] < 2 * v20:
                continue
            out.append((-v[t] / v20, ("B", c, _name(D, c), "今天漲 %.1f%%、收在高點附近、成交量是平常的 %.1f 倍" % (r1 * 100, v[t] / v20))))
        elif pid == "dt_rev":
            if r1 > -0.05:
                continue
            out.append((r1, ("B", c, _name(D, c), "今天跌 %.1f%%，賭隔天反彈" % (-r1 * 100))))
    out.sort(key=lambda x: x[0])
    return [x[1] for x in out[:PBY[pid]["max"]]]


def _pick_st(pid, D, A_of, stocks, res, held):
    t = D.T - 1
    by = {r["c"]: r for r in stocks or []}
    rr = (res or {}).get("_recs") or {}
    out = []
    if pid == "st_snipe":
        for r in stocks or []:
            ra = r.get("ra") or "NNN"
            if r.get("etf") or ra[0] not in "Bb" or ra[1] in "Ss" or r.get("rn") or r["c"] in held:
                continue
            pb = (((rr.get(r["c"]) or {}).get("hs") or {}).get("short") or {}).get("pb")
            out.append((0 if ra[0] == "B" else 1, -(pb or 0), r["c"], r.get("n") or r["c"],
                        "短線%s，跑贏大盤機率 %s" % ("建議買" if ra[0] == "B" else "相對看好", "—" if pb is None else "%.0f%%" % (pb * 100))))
        out.sort()
        return [x[2:] for x in out[:3]]
    for c in _universe(D):
        if c in held:
            continue
        A = A_of(c)
        if A is None or t < 60 or isnan(A[t]):
            continue
        if pid == "st_trend":
            m20, m60 = _sma(A, 20, t), _sma(A, 60, t)
            w = [x for x in A[max(0, t - 249):t + 1] if not isnan(x)]
            if isnan(m20) or isnan(m60) or len(w) < 120 or isnan(A[t - 60]) or A[t - 60] <= 0:
                continue
            if not (A[t] > m20 > m60 and A[t] >= max(w) * 0.95):
                continue
            r60 = A[t] / A[t - 60] - 1
            out.append((-r60, c, _name(D, c), "均線多頭排列、離一年高點 %.1f%% 內、近 60 天漲 %.0f%%" % ((1 - A[t] / max(w)) * 100, r60 * 100)))
        elif pid == "st_value":
            r = by.get(c) or {}
            ra = r.get("ra") or "NNN"
            sc = (r.get("s") or [None, None, None])[2]
            if isnan(A[t - 20]) or A[t - 20] <= 0 or ra[2] in "Ss" or sc is None or sc < 60 or r.get("rn"):
                continue
            r20 = A[t] / A[t - 20] - 1
            if r20 > -0.15:
                continue
            out.append((r20, c, _name(D, c), "近 20 天跌 %.0f%%，長期分數 %.0f" % (-r20 * 100, sc)))
    out.sort()
    return [x[1:] for x in out[:PBY[pid]["max"]]]


# ====================================================================== 撮合

def _settle_st(a, D, t):
    day = D.days[t]
    for p in a["pos"]:
        if p["day"] != day:
            p["held"] = p.get("held", 0) + 1
    pend = a["pending"]
    a["pending"] = []
    keep = []
    for p in a["pos"]:          # 開盤：收盤後已決定要賣的
        if p.get("sell") and (p.get("exit_made") or "") < "%s 09:00" % rb._fmt_day(day) and rb._sell_pos(a, p, D, t, "open", p["sell"]):
            continue
        keep.append(p)
    a["pos"] = keep
    for o in [x for x in pend if x["side"] == "B" and x["kind"] == "close"]:
        s = D.raw.get(o["c"])
        if rb._late(o, day):
            rb._finish(a, o, day, "沒有下單（雲端更新延遲，收盤前沒來得及送出）")
            continue
        px = s["c"][t] if s else float("nan")
        ref = s["ref"][t] if s else float("nan")
        if isnan(px) or px <= 0:
            rb._finish(a, o, day, "沒有成交（當天沒有交易）")
            continue
        if rb._limit_up(px, ref):
            rb._finish(a, o, day, "沒有成交（收盤漲停，買不到）")
            continue
        if any(p["c"] == o["c"] for p in a["pos"]):
            rb._finish(a, o, day, "沒有下單（已經持有）")
            continue
        qty = int(min(o["amt"], a["cash"]) // (px * (1 + rb.FEE * rb.DISC)))
        if qty <= 0:
            rb._finish(a, o, day, "沒有成交（資金不足）")
            continue
        f = rb.fee(px * qty)
        a["cash"] -= px * qty + f
        a["fees"] += f
        rb._finish(a, dict(o, act="買進"), day, "成交", px, qty, f, 0)
        a["pos"].append({"c": o["c"], "n": o["n"], "qty": qty, "px": px, "cost": px * qty + f, "day": day,
                         "at": "%s 13:30" % rb._fmt_day(day), "held": 0, "exit": "open",
                         "why": o.get("why"), "made": o["made"], "last": px})


def _exit_rule(pp, p, D, A_of):
    """收盤後判斷持股要不要在下一個交易日開盤賣；回傳理由或 None。"""
    t = D.T - 1
    ret = p["last"] / p["px"] - 1
    if p.get("held", 0) + 1 >= pp["hold"]:
        return "到期賣出（持有 %d 個交易日）" % pp["hold"]
    if pp.get("take") is not None and ret >= pp["take"]:
        return "停利（收盤比買進價漲 %.1f%%）" % (ret * 100)
    if pp.get("stop") is not None and ret <= pp["stop"]:
        return "停損（收盤比買進價跌 %.1f%%）" % (-ret * 100)
    if pp["id"] == "st_trend":
        A = A_of(p["c"])
        if A is not None and t >= 20:
            m20 = _sma(A, 20, t)
            if not isnan(m20) and not isnan(A[t]) and A[t] < m20:
                return "收盤跌破 20 日均線，趨勢轉弱"
    return None


# ====================================================================== 主程式

def run(D, res, stocks, dt, A_all=None):
    st = read_json(PATH, None)
    last = D.T - 1
    day = D.days[last]
    now = now_tw()
    idx = {c: i for i, c in enumerate(getattr(D, "codes", []) or [])}

    def A_of(c):
        if A_all is not None and c in idx:
            return A_all[idx[c]]
        s = D.raw.get(c)
        return s["c"] if s else None
    if not st:
        st = {"ver": 1, "start": day, "last": None, "acct": {}}
    A = st["acct"]
    for pp in P:
        if pp["id"] not in A:
            A[pp["id"]] = rb._new_acct(day, pp["kind"])
            A[pp["id"]]["start"] = day
    tx = D.mkt["taiex"]
    if st["last"] and st["last"] in D.days and st["last"] < day:
        t0 = D.days.index(st["last"]) + 1
        for t in range(t0, last + 1):
            for pp in P:
                a = A[pp["id"]]
                if pp["kind"] == "dt":
                    rb._settle_dt(a, D, t)
                else:
                    _settle_st(a, D, t)
                a["eq"].append([D.days[t], round(rb._equity(a, D, t)), None if isnan(tx[t]) else round(tx[t], 2)])
        st["last"] = day
    elif not st["last"]:
        st["last"] = day
    elif st["last"] > day:
        return None
    _reviews(st, D)
    for pp in P:        # 新開戶：第一筆總資產
        a = A[pp["id"]]
        if not a["eq"]:
            a["eq"].append([day, a["init"], None if isnan(tx[last]) else round(tx[last], 2)])
    locked = st.get("plan_day") == day and now.strftime("%Y%m%d") > day and now.weekday() < 5 and now.hour >= 9
    if not locked:
        made = now.strftime("%Y-%m-%d %H:%M")
        nx = now.strftime("%Y%m%d") > day and now.weekday() < 5
        hm = now.strftime("%H:%M")
        for pp in P:
            a = A[pp["id"]]
            eqv = rb._equity(a, D, last)
            out = []
            if pp["kind"] == "dt":
                if not (nx and hm >= rb.DEADLINE["open"]):
                    for k, (side, c, n, why) in enumerate(_pick_dt(pp["id"], D, dt)):
                        out.append({"id": rb._oid(a), "sig": day, "made": made, "c": c, "n": n, "side": side, "kind": "open",
                                    "amt": round(eqv / pp["slots"]), "why": why, "role": "main", "rank": k + 1,
                                    "plan": "開盤價買進（開盤就漲停則放棄）、收盤價賣出" if side == "B" else
                                    "掛平盤價先賣（開在平盤以上用開盤價成交、開低就等盤中漲回平盤；開盤漲停不先賣），收盤價買回"})
            else:
                for p in a["pos"]:
                    why = _exit_rule(pp, p, D, A_of)
                    p["sell"] = why
                    if why:
                        p["exit_sig"], p["exit_made"] = day, made
                        out.append({"id": "", "sig": day, "made": made, "c": p["c"], "n": p["n"], "side": "S", "kind": "open",
                                    "why": why, "plan": "開盤價賣出", "qty": p["qty"]})
                held = {p["c"] for p in a["pos"]}
                if not (nx and hm >= rb.DEADLINE["close"]):
                    for k, (c, n, why) in enumerate(_pick_st(pp["id"], D, A_of, stocks, res, held)):
                        out.append({"id": rb._oid(a), "sig": day, "made": made, "c": c, "n": n, "side": "B", "kind": "close",
                                    "amt": round(eqv / pp["slots"]), "why": why, "role": "main", "rank": k + 1,
                                    "plan": "收盤價買進（收盤漲停就放棄）"})
            a["pending"] = out
        st["plan_note"] = "這份收盤資料到 %s 才分析完成，當沖委託來不及在下一個交易日送出" % made if nx and hm >= rb.DEADLINE["open"] else None
        st["plan_day"] = day
    for a in A.values():
        a["orders"] = a["orders"][-KEEP:]
        a["trades"] = a["trades"][-KEEP:]
    write_json(PATH, st)
    out = summary(st)
    write_json(os.path.join(RESULTS, "arena.json"), out)
    return out


def summary(st):
    out = {"start": st["start"], "day": st["last"], "plan_day": st.get("plan_day"), "plan_note": st.get("plan_note"),
           "generated": now_tw().strftime("%Y-%m-%d %H:%M"), "p": []}
    for pp in P:
        a = st["acct"][pp["id"]]
        pos = []
        for p in a["pos"]:
            mv = p["qty"] * p["last"]
            f = rb.fee(mv)
            txx = int(math.floor(mv * rb.TAX))
            pos.append({"c": p["c"], "n": p["n"], "qty": p["qty"], "px": p["px"], "last": p["last"], "mv": round(mv),
                        "upnl": round(mv - f - txx - p["cost"]), "uret": round((mv - f - txx) / p["cost"] - 1, 5),
                        "at": p["at"], "held": p.get("held", 0), "sell": p.get("sell")})
        pend = [{x: o.get(x) for x in ("c", "n", "side", "kind", "why", "plan", "amt", "qty")} for o in a["pending"]]
        s = rb._stats(a, None)
        s["max_day"] = max([v for v in _per_day(a).values()] or [0])
        s["today_n"] = sum(1 for tr in a["trades"] if tr["out_day"] == st["last"])
        s["today_pnl"] = sum(tr["pnl"] for tr in a["trades"] if tr["out_day"] == st["last"])
        out["p"].append({k: pp[k] for k in ("id", "kind", "name", "style", "max", "line", "rules")} | {
            "start": a["start"], "stats": s, "pos": pos, "pending": pend, "rev": (st.get("rev") or {}).get(pp["id"], [])[::-1],
            "trades": a["trades"][-200:][::-1], "orders": a["orders"][-200:][::-1], "eq": a["eq"][-500:]})
    return out


def _per_day(a):
    c = {}
    for tr in a["trades"]:
        c[tr["in_day"]] = c.get(tr["in_day"], 0) + 1
    return c


# ====================================================================== 每週策略整理（人格自己寫的週記）
# 每週第一次執行時，替每個人格整理「到上週為止」的成績與心得，用白話寫在網頁上。
# 只整理、不改規則：規則固定，才能長期比較哪一種典型有效；要改規則由每日調校驗證後記在研究筆記。

def _week(d):
    import datetime as _d
    y, w, _ = _d.date(int(d[:4]), int(d[4:6]), int(d[6:8])).isocalendar()
    return "%d-W%02d" % (y, w)


def _pct(x, d=1):
    return ("%+." + str(d) + "f%%") % (x * 100)


def _review(pp, a, D, wk, upto):
    """寫一篇週記：upto＝上週最後一個交易日。"""
    tr = [x for x in a["trades"] if x["out_day"] <= upto]
    wtr = [x for x in tr if _week(x["out_day"]) == wk]
    eq = [x for x in a["eq"] if x[0] <= upto]
    lines = ["我的做法：%s。" % pp["line"]]
    if not tr:
        lines.append("還沒有完成的交易，下週照原本的規則繼續等機會。")
    else:
        v, t0 = eq[-1], next((x for x in eq if x[2]), None)
        ret = v[1] / a["init"] - 1
        bench = v[2] / t0[2] - 1 if t0 and v[2] else None
        wp = sum(x["pnl"] for x in wtr)
        lines.append("這週完成 %d 筆，賺錢 %d 筆，損益 %s 元。" % (len(wtr), sum(1 for x in wtr if x["pnl"] > 0), "{:+,}".format(round(wp)))
                     if wtr else "這週沒有完成的交易。")
        lines.append("開戶以來 %d 筆，賺錢比例 %.0f%%，平均每筆 %s；總報酬 %s%s。" % (
            len(tr), 100 * sum(1 for x in tr if x["pnl"] > 0) / len(tr), _pct(sum(x["ret"] for x in tr) / len(tr), 2), _pct(ret),
            "" if bench is None else "，同期加權指數 %s（%s）" % (_pct(bench), "贏大盤" if ret > bench else "輸大盤")))
        # 跟大盤方向的關係（當沖看當天、短線看持有期間）
        tx = dict((x[0], x[2]) for x in a["eq"] if x[2])
        days = D.days
        up, dn = [], []
        for x in tr:
            try:
                i0 = days.index(x["in_day"])
            except ValueError:
                continue
            b0 = tx.get(days[i0 - 1]) if pp["kind"] == "dt" and i0 > 0 else tx.get(x["in_day"])
            b1 = tx.get(x["out_day"])
            if not b0 or not b1:
                continue
            (up if b1 >= b0 else dn).append(x["pnl"] > 0)
        if up and dn:
            lines.append("大盤上漲時我賺錢的比例 %.0f%%（%d 筆），大盤下跌時 %.0f%%（%d 筆）——%s" % (
                100 * sum(up) / len(up), len(up), 100 * sum(dn) / len(dn), len(dn),
                "我比較適合跌的行情。" if sum(dn) / len(dn) > sum(up) / len(up) + 0.15 else
                "我比較適合漲的行情。" if sum(up) / len(up) > sum(dn) / len(dn) + 0.15 else "漲跌行情差不多。"))
        gross = sum(x["pnl"] for x in tr) + a["fees"] + a["taxes"]
        if gross > 0 and (a["fees"] + a["taxes"]) / gross > 0.3:
            lines.append("手續費加稅吃掉了 %.0f%% 的毛利，交易次數多是我的弱點。" % (100 * (a["fees"] + a["taxes"]) / gross))
        best = max(tr, key=lambda x: x["ret"])
        worst = min(tr, key=lambda x: x["ret"])
        lines.append("最好的一筆：%s %s；最差的一筆：%s %s。" % (best["n"], _pct(best["ret"]), worst["n"], _pct(worst["ret"])))
        if pp["kind"] == "st":
            why = {}
            for x in tr:
                k = (x.get("exit_why") or "").split("（")[0]
                why.setdefault(k, []).append(x["ret"])
            lines.append("出場方式：" + "、".join("%s %d 筆（平均 %s）" % (k, len(v_), _pct(sum(v_) / len(v_))) for k, v_ in sorted(why.items(), key=lambda z: -len(z[1]))) + "。")
    miss = {}
    for o in a["orders"]:
        if o.get("fill_day", "") <= upto and _week(o.get("fill_day", "00000101")) == wk and o.get("st", "").startswith("沒有"):
            k = o["st"].split("（")[-1].rstrip("）") if "（" in o["st"] else o["st"]
            miss[k] = miss.get(k, 0) + 1
    if miss:
        lines.append("這週沒成交：" + "、".join("%s %d 次" % kv for kv in sorted(miss.items(), key=lambda z: -z[1])) + "。")
    lines.append("樣本還少（不到 30 筆），先不下結論；下週照原本的規則操作。" if len(tr) < 30 else
                 "下週照原本的規則操作（規則固定不變，才能公平比較哪一種做法有效）。")
    return {"week": wk, "upto": upto, "made": now_tw().strftime("%Y-%m-%d %H:%M"), "lines": lines}


def _reviews(st, D):
    wk_now = _week(D.days[-1])
    rv = st.setdefault("rev", {})
    if st.get("rev_week") == wk_now:
        return
    prev = [d for d in D.days if _week(d) < wk_now]
    if not prev:
        st["rev_week"] = wk_now
        return
    upto = prev[-1]
    wk = _week(upto)
    for pp in P:
        a = st["acct"].get(pp["id"])
        if not a or a["start"] > upto:
            continue
        lst = rv.setdefault(pp["id"], [])
        if lst and lst[-1]["week"] == wk:
            continue
        lst.append(_review(pp, a, D, wk, upto))
        rv[pp["id"]] = lst[-26:]
    st["rev_week"] = wk_now
