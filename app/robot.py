# -*- coding: utf-8 -*-
"""機器人模擬下單：兩個各 100 萬元的模擬帳戶，完全依程式評分自動下單，不動到真的錢。

- 當沖帳戶：每天收盤後依「當沖」模型挑「推薦」的股票（扣成本後勝算超過一半、平均是賺的），
  最多 5 檔，下一個交易日「開盤價買進（或先賣）、收盤價賣出（或買回）」——這正是當沖模型預測的時段。
  沒有推薦的股票就不下單、整天空手。
- 短線帳戶：每天收盤後依短線評價（建議買優先，其次相對看好，同一級依跑贏大盤機率排序）挑最多 5 檔還沒持有的，
  每檔約總資產的 1/25（每天投入約 1/5，持有約 5 個交易日，所以約有 5 批輪流）。
  買進／賣出時機依評價的「買賣時機」（最近 250 個已揭曉交易日實測最好的組合，例如收盤前買、到期那天開盤賣）。
  持有中的股票短線評價變成「建議賣」時，下一個交易日開盤提早賣出。

公正性：
- 委託在「訊號那天收盤後」決定並存檔，下一個交易日 9:00 開盤後不再修改（和前瞻實測一樣）；
  若雲端排程延遲，委託到開盤（收盤價委託為 13:00）之後才產生，就當作「沒來得及下單」，不成交。
- 只用日線價格撮合：開盤價、收盤價都是集合競價的成交價，所以假設用該價格全部成交；
  開盤（或收盤）就漲停時買不到、跌停時賣不到（先賣後買時，開盤在平盤以下也不先賣）。
- 費用：手續費 0.1425% × 6 折（每筆最低 20 元）；證交稅 一般 0.3%、ETF 0.1%、當沖 0.15%。
- 以「股」為單位下單（不足一張用零股計），不融資、不融券。
"""
import math
import os

from util import DB, RESULTS, is_etf, now_tw, read_json, write_json

PATH = os.path.join(DB, "robot.json")
INIT = 1_000_000
FEE, DISC, FEE_MIN = 0.001425, 0.6, 20
TAX, TAX_ETF, TAX_DT = 0.003, 0.001, 0.0015
DT_MAX = 5           # 當沖每天最多幾檔
ST_MAX = 5           # 短線每天最多新買幾檔
ST_SLOTS = 25        # 短線每檔約總資產的 1/25
ST_H = 5             # 短線持有天數
KEEP = 3000          # 委託、交易紀錄最多保留幾筆
KIND_TXT = {"open": "開盤價", "close": "收盤價"}
KIND_TIME = {"open": "09:00", "close": "13:30"}
DEADLINE = {"open": "09:00", "close": "13:00"}


def isnan(x):
    return x is None or x != x


def fee(amt):
    return max(FEE_MIN, int(math.floor(amt * FEE * DISC)))


def _limit_up(px, ref):
    return not isnan(ref) and ref > 0 and px >= ref * 1.0995


def _limit_dn(px, ref):
    return not isnan(ref) and ref > 0 and px <= ref * 0.9005


def _fmt_day(d):
    return "%s-%s-%s" % (d[:4], d[4:6], d[6:8])


def _new_acct(day, kind):
    return {"kind": kind, "init": INIT, "cash": INIT, "start": day, "pos": [], "pending": [], "orders": [],
            "trades": [], "eq": [], "seq": 0, "fees": 0, "taxes": 0}


def _oid(a):
    a["seq"] += 1
    return "%s%05d" % ("D" if a["kind"] == "dt" else "S", a["seq"])


def _late(o, day):
    """委託是否在該交易日的截止時刻之後才產生（雲端排程延遲）。"""
    return o["made"] >= "%s %s" % (_fmt_day(day), DEADLINE[o["kind"]])


def _finish(a, o, day, st, px=None, qty=None, f=0, tx=0):
    o.update({"fill_day": day, "st": st})
    if px is not None:
        o.update({"px": px, "qty": qty, "fee": f, "tax": tx, "at": "%s %s" % (_fmt_day(day), KIND_TIME[o["kind"]])})
    a["orders"].append(o)


# ====================================================================== 撮合

def _settle_dt(a, D, t):
    day = D.days[t]
    avail = a["cash"]
    for o in a["pending"]:
        s = D.raw.get(o["c"])
        if _late(o, day):
            _finish(a, o, day, "沒有下單（雲端更新延遲，開盤前沒來得及送出）")
            continue
        if not s:
            _finish(a, o, day, "沒有成交（查不到行情）")
            continue
        op, cl, ref = s["o"][t], s["c"][t], s["ref"][t]
        if isnan(op) or isnan(cl) or op <= 0 or cl <= 0:
            _finish(a, o, day, "沒有成交（當天沒有交易）")
            continue
        if o["side"] == "B" and _limit_up(op, ref):
            _finish(a, o, day, "沒有成交（開盤就漲停，買不到）")
            continue
        if o["side"] == "S" and (_limit_dn(op, ref) or (not isnan(ref) and op < ref)):
            _finish(a, o, day, "沒有成交（開盤在平盤以下，不能先賣）")
            continue
        qty = int(o["amt"] // (op * (1 + FEE * DISC)))
        qty = min(qty, int(avail // (op * (1 + FEE * DISC))))
        if qty <= 0:
            _finish(a, o, day, "沒有成交（資金不足）")
            continue
        f1, f2 = fee(op * qty), fee(cl * qty)
        if o["side"] == "B":
            tx = int(math.floor(cl * qty * TAX_DT))
            pnl = (cl - op) * qty - f1 - f2 - tx
            legs = (("買進", op, f1, 0), ("賣出", cl, f2, tx))
        else:
            tx = int(math.floor(op * qty * TAX_DT))
            pnl = (op - cl) * qty - f1 - f2 - tx
            legs = (("先賣", op, f1, tx), ("買回", cl, f2, 0))
        a["cash"] += pnl
        avail -= op * qty + f1
        a["fees"] += f1 + f2
        a["taxes"] += tx
        o2 = dict(o, id=_oid(a), side="S" if o["side"] == "B" else "B", kind="close", act=legs[1][0])
        _finish(a, dict(o, act=legs[0][0]), day, "成交", op, qty, legs[0][2], legs[0][3])
        _finish(a, o2, day, "成交", cl, qty, legs[1][2], legs[1][3])
        cost = op * qty
        a["trades"].append({"c": o["c"], "n": o["n"], "dir": "做多" if o["side"] == "B" else "做空",
                            "in_day": day, "in_at": "%s 09:00" % _fmt_day(day), "in_px": op,
                            "out_day": day, "out_at": "%s 13:30" % _fmt_day(day), "out_px": cl, "qty": qty,
                            "pnl": round(pnl), "ret": round(pnl / cost, 5), "why": o.get("why"), "made": o["made"]})
    a["pending"] = []


def _sell_pos(a, p, D, t, kind, why):
    s = D.raw.get(p["c"])
    day = D.days[t]
    px = s[{"open": "o", "close": "c"}[kind]][t] if s else float("nan")
    ref = s["ref"][t] if s else float("nan")
    if isnan(px) or px <= 0 or _limit_dn(px, ref):
        return False       # 停牌或跌停賣不掉，下一個交易日再賣
    qty = p["qty"]
    f = fee(px * qty)
    tx = int(math.floor(px * qty * (TAX_ETF if is_etf(p["c"]) else TAX)))
    a["cash"] += px * qty - f - tx
    a["fees"] += f
    a["taxes"] += tx
    pnl = px * qty - f - tx - p["cost"]
    o = {"id": _oid(a), "sig": p.get("exit_sig") or day, "made": p.get("exit_made") or p["made"], "c": p["c"], "n": p["n"],
         "side": "S", "kind": kind, "act": "賣出", "why": why}
    _finish(a, o, day, "成交", px, qty, f, tx)
    a["trades"].append({"c": p["c"], "n": p["n"], "dir": "做多", "in_day": p["day"], "in_at": p["at"], "in_px": p["px"],
                        "out_day": day, "out_at": "%s %s" % (_fmt_day(day), KIND_TIME[kind]), "out_px": px, "qty": qty,
                        "pnl": round(pnl), "ret": round(pnl / p["cost"], 5), "why": p.get("why"), "exit_why": why,
                        "made": p["made"]})
    return True


def _settle_st(a, D, t):
    day = D.days[t]
    for p in a["pos"]:
        if p["day"] != day:
            p["left"] -= 1
    pend = a["pending"]
    a["pending"] = []
    for phase in ("open", "close"):
        # 1. 賣出：到期（依計畫的時機）或提早賣出的委託
        keep = []
        for p in a["pos"]:
            due = p["left"] <= 0 and p["exit"] == phase
            early = phase == "open" and p.get("early") and (p.get("exit_made") or "") < "%s 09:00" % _fmt_day(day)
            if (due or early) and _sell_pos(a, p, D, t, phase, "提早賣出：短線評價變成建議賣" if early and not due else
                                           "到期賣出（持有 %d 個交易日）" % ST_H):
                continue
            if p["left"] <= 0 and p["exit"] == "close" and phase == "close":
                p["exit"] = "open"      # 賣不掉，下一個交易日開盤再賣
            keep.append(p)
        a["pos"] = keep
        # 2. 買進
        for o in [x for x in pend if x["side"] == "B" and x["kind"] == phase]:
            s = D.raw.get(o["c"])
            if _late(o, day):
                _finish(a, o, day, "沒有下單（雲端更新延遲，%s前沒來得及送出）" % ("開盤" if phase == "open" else "收盤"))
                continue
            px = s[{"open": "o", "close": "c"}[phase]][t] if s else float("nan")
            ref = s["ref"][t] if s else float("nan")
            if isnan(px) or px <= 0:
                _finish(a, o, day, "沒有成交（當天沒有交易）")
                continue
            if _limit_up(px, ref):
                _finish(a, o, day, "沒有成交（%s漲停，買不到）" % ("開盤" if phase == "open" else "收盤"))
                continue
            if any(p["c"] == o["c"] for p in a["pos"]):
                _finish(a, o, day, "沒有下單（已經持有）")
                continue
            qty = int(min(o["amt"], a["cash"]) // (px * (1 + FEE * DISC)))
            if qty <= 0:
                _finish(a, o, day, "沒有成交（資金不足）")
                continue
            f = fee(px * qty)
            a["cash"] -= px * qty + f
            a["fees"] += f
            _finish(a, dict(o, act="買進"), day, "成交", px, qty, f, 0)
            a["pos"].append({"c": o["c"], "n": o["n"], "qty": qty, "px": px, "cost": px * qty + f, "day": day,
                             "at": "%s %s" % (_fmt_day(day), KIND_TIME[phase]), "left": ST_H, "exit": o["exit"],
                             "why": o.get("why"), "made": o["made"], "last": px})


def _equity(a, D, t):
    v = a["cash"]
    for p in a["pos"]:
        s = D.raw.get(p["c"])
        c = s["c"][t] if s else float("nan")
        if not isnan(c) and c > 0:
            p["last"] = c
        v += p["qty"] * p["last"]
    return v


# ====================================================================== 產生下一個交易日的委託

def _plan_dt(a, dt, made, day):
    out = []
    if not dt:
        return out
    eq = a["cash"]
    cand = [("B", r) for r in dt.get("long", []) if r.get("ok")] + [("S", r) for r in dt.get("short", []) if r.get("ok")]
    cand.sort(key=lambda x: -x[1]["score"])
    for side, r in cand[:DT_MAX]:
        why = "當沖%s勝算 %.0f%%（扣成本後）、平均每筆 %+.2f%%" % ("先買後賣" if side == "B" else "先賣後買", r["win"] * 100, r["avg"] * 100)
        if r.get("why"):
            why += "；" + "、".join(r["why"][:2])
        out.append({"id": _oid(a), "sig": day, "made": made, "c": r["c"], "n": r["n"], "side": side, "kind": "open",
                    "amt": round(eq / DT_MAX), "why": why, "plan": "開盤價%s、收盤價%s" % (("買進", "賣出") if side == "B" else ("先賣", "買回"))})
    return out


def _plan_st(a, stocks, res, recs, made, day, eqv):
    tm = (((recs or {}).get("h") or {}).get("short") or {}).get("timing") or {}
    best = tm.get("best") or "open_close"
    ent, ext = best.split("_")
    held = {p["c"] for p in a["pos"]}
    rr = res.get("_recs") or {}
    cand = []
    for r in stocks:
        ra = r.get("ra") or "NNN"
        if ra[0] not in "Bb" or r["c"] in held or r.get("rn"):
            continue
        hs = ((rr.get(r["c"]) or {}).get("hs") or {}).get("short") or {}
        cand.append((0 if ra[0] == "B" else 1, -(hs.get("pb") or 0), r, hs))
    cand.sort(key=lambda x: (x[0], x[1]))
    out = []
    for lv, _, r, hs in cand[:ST_MAX]:
        why = "短線%s，跑贏大盤機率 %s" % ("建議買" if lv == 0 else "相對看好", "—" if hs.get("pb") is None else "%.0f%%" % (hs["pb"] * 100))
        out.append({"id": _oid(a), "sig": day, "made": made, "c": r["c"], "n": r["n"], "side": "B", "kind": ent, "exit": ext,
                    "amt": round(eqv / ST_SLOTS), "why": why,
                    "plan": "%s買進，第 %d 個交易日%s賣出" % (KIND_TXT[ent], ST_H, KIND_TXT[ext])})
    # 持有中、短線評價變成建議賣 → 下一個交易日開盤提早賣
    by = {r["c"]: r for r in stocks}
    for p in a["pos"]:
        ra = (by.get(p["c"]) or {}).get("ra") or "NNN"
        p["early"] = ra[0] == "S" and p["left"] > 1
        if p["early"]:
            p["exit_sig"], p["exit_made"] = day, made
            out.append({"id": "", "sig": day, "made": made, "c": p["c"], "n": p["n"], "side": "S", "kind": "open",
                        "why": "短線評價變成建議賣", "plan": "開盤價提早賣出", "qty": p["qty"]})
    return out, best


# ====================================================================== 主程式

def run(D, res, stocks, dt, recs):
    st = read_json(PATH, None)
    last = D.T - 1
    day = D.days[last]
    now = now_tw()
    if not st:
        st = {"ver": 1, "start": day, "last": None, "acct": {"dt": _new_acct(day, "dt"), "st": _new_acct(day, "st")}}
    A = st["acct"]
    tx = D.mkt["taiex"]
    # ---- 1. 撮合：處理上次之後的每一個新交易日
    if st["last"] and st["last"] in D.days and st["last"] < day:
        t0 = D.days.index(st["last"]) + 1
        for t in range(t0, last + 1):
            _settle_dt(A["dt"], D, t)
            _settle_st(A["st"], D, t)
            for a in A.values():
                v = _equity(a, D, t)
                a["eq"].append([D.days[t], round(v), None if isnan(tx[t]) else round(tx[t], 2)])
        st["last"] = day
    elif not st["last"]:
        st["last"] = day
        for a in A.values():
            a["eq"].append([day, a["init"], None if isnan(tx[last]) else round(tx[last], 2)])
    elif st["last"] > day:
        return None
    # ---- 2. 下一個交易日的委託（開盤後不再改）
    locked = st.get("plan_day") == day and now.strftime("%Y%m%d") > day and now.weekday() < 5 and now.hour >= 9
    if not locked:
        made = now.strftime("%Y-%m-%d %H:%M")
        dta, sta = A["dt"], A["st"]
        # 這份資料若到「下一個交易日」開盤（收盤價委託為 13:00）之後才分析，委託一定來不及送出：乾脆不產生
        nx = now.strftime("%Y%m%d") > day and now.weekday() < 5
        hm = now.strftime("%H:%M")
        dta["pending"] = [] if nx and hm >= DEADLINE["open"] else _plan_dt(dta, dt, made, day)
        sta["pending"], st["st_timing"] = _plan_st(sta, stocks, res, recs, made, day, _equity(sta, D, last))
        sta["pending"] = [o for o in sta["pending"] if not (nx and hm >= DEADLINE[o["kind"]])]
        st["plan_note"] = "這份收盤資料到 %s 才分析完成，已經來不及在下一個交易日下單" % made if nx and hm >= DEADLINE["open"] else None
        st["plan_day"] = day
    for a in A.values():
        a["orders"] = a["orders"][-KEEP:]
        a["trades"] = a["trades"][-KEEP:]
    write_json(PATH, st)
    out = summary(st, D)
    write_json(os.path.join(RESULTS, "robot.json"), out)
    return out


def _stats(a, tx_last):
    eq = a["eq"]
    v = eq[-1][1] if eq else a["init"]
    peak, mdd = 0, 0.0
    for _, x, _t in eq:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1 if peak else 0)
    tr = a["trades"]
    wins = [x for x in tr if x["pnl"] > 0]
    t0 = next((x[2] for x in eq if x[2]), None)
    bench = (eq[-1][2] / t0 - 1) if eq and t0 and eq[-1][2] else None
    act_days = len({x["in_day"] for x in tr})
    return {"equity": round(v), "ret": round(v / a["init"] - 1, 5), "bench": None if bench is None else round(bench, 5),
            "mdd": round(mdd, 5), "days": max(0, len(eq) - 1), "act_days": act_days, "n": len(tr),
            "win": round(len(wins) / len(tr), 4) if tr else None,
            "avg": round(sum(x["ret"] for x in tr) / len(tr), 5) if tr else None,
            "pnl": round(sum(x["pnl"] for x in tr)), "fees": a["fees"], "taxes": a["taxes"], "cash": round(a["cash"])}


def summary(st, D):
    out = {"start": st["start"], "day": st["last"], "plan_day": st.get("plan_day"), "plan_note": st.get("plan_note"), "st_timing": st.get("st_timing"),
           "generated": now_tw().strftime("%Y-%m-%d %H:%M"), "acct": {}}
    for k, a in st["acct"].items():
        pos = []
        for p in a["pos"]:
            mv = p["qty"] * p["last"]
            f = fee(mv)
            txx = int(math.floor(mv * (TAX_ETF if is_etf(p["c"]) else TAX)))
            pos.append({"c": p["c"], "n": p["n"], "qty": p["qty"], "px": p["px"], "last": p["last"], "cost": round(p["cost"]),
                        "mv": round(mv), "upnl": round(mv - f - txx - p["cost"]), "uret": round((mv - f - txx) / p["cost"] - 1, 5),
                        "at": p["at"], "made": p["made"], "left": max(0, p["left"]), "exit": KIND_TXT[p["exit"]],
                        "early": bool(p.get("early")), "why": p.get("why")})
        pend = [{x: o.get(x) for x in ("c", "n", "side", "kind", "made", "why", "plan", "amt", "qty")} for o in a["pending"]]
        out["acct"][k] = {"init": a["init"], "start": a["start"], "stats": _stats(a, None), "pos": pos, "pending": pend,
                          "orders": a["orders"][-400:][::-1], "trades": a["trades"][-400:][::-1], "eq": a["eq"][-500:]}
    return out
