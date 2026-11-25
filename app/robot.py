# -*- coding: utf-8 -*-
"""機器人模擬下單：兩個各 100 萬元的模擬帳戶，完全依程式評分自動下單，不動到真的錢。

- 當沖帳戶：每天收盤後依「當沖」模型挑「推薦」的股票（扣成本後勝算超過一半、平均是賺的），
  依勝算排序，前 5 檔是主單、後面最多 5 檔是備選（2026-11-17 起）。
  開盤前（只能預估）：主單「先買」用開盤價買；「先賣」掛平盤價——開盤在平盤以上就用開盤價成交，開低就繼續掛著，
  盤中漲回平盤以上才成交。開盤後（看到開盤價再調整）：主單在開盤沒成交幾檔，就依序改下幾檔備選，
  備選買進限開盤價（盤中跌破開盤價才成交）、先賣限開盤價且不低於平盤（盤中漲過才成交）。一律收盤價出場。
  沒有推薦的股票就不下單、整天空手。
- 短線帳戶：每天收盤後依短線評價（建議買優先，其次相對看好，同一級依跑贏大盤機率排序）挑最多 5 檔還沒持有的，
  每檔約總資產的 1/25（每天投入約 1/5，持有約 5 個交易日，所以約有 5 批輪流）。
  買進／賣出時機依評價的「買賣時機」（最近 250 個已揭曉交易日實測最好的組合，例如收盤前買、到期那天開盤賣）。
  持有中的股票短線評價變成「建議賣」時，下一個交易日開盤提早賣出。
  另排最多 5 檔備選（2026-11-17 起）：主單在下單時刻（例如收盤前）漲停買不到，就依序改買備選。

公正性：
- 委託在「訊號那天收盤後」決定並存檔，下一個交易日 9:00 開盤後不再修改（和前瞻實測一樣）；
  若雲端排程延遲，委託到開盤（收盤價委託為 13:00）之後才產生，就當作「沒來得及下單」，不成交。
- 只用日線價格撮合：開盤價、收盤價都是集合競價的成交價，所以假設用該價格全部成交；
  開盤（或收盤）就漲停時買不到、跌停時賣不到；先賣一律不低於平盤價。
  盤中限價單只看當天最高／最低價：要「超過」限價才算成交（等於有排隊），成交價就是限價。
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
DT_BACKUP = 5        # 當沖備選幾檔（主單開盤沒成交時，開盤後依序補上）
ST_BACKUP = 5        # 短線備選幾檔（主單漲停買不到時改買）
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


def _finish(a, o, day, st, px=None, qty=None, f=0, tx=0, at=None):
    o.update({"fill_day": day, "st": st})
    if px is not None:
        o.update({"px": px, "qty": qty, "fee": f, "tax": tx, "at": "%s %s" % (_fmt_day(day), at or KIND_TIME[o["kind"]])})
    a["orders"].append(o)


# ====================================================================== 撮合

def _dt_open(o, s, t):
    """開盤（09:00 集合競價）能不能成交；回傳 (價格, 時刻) 或 (None, 原因)。"""
    op, ref = s["o"][t], s["ref"][t]
    if o["side"] == "B":
        if _limit_up(op, ref):
            return None, "開盤就漲停，買不到"
        return (op, "09:00"), None
    if _limit_dn(op, ref) or (not isnan(ref) and op < ref):
        return None, "開盤在平盤以下，不能先賣"
    if _limit_up(op, ref):
        # 2026-11-25 起（法規與實際可行性）：開盤就漲停，收盤常常鎖住漲停買不回；
        # 現股當沖先賣後買不回會違約交割（限空令期間也不能改列融券），所以不先賣
        return None, "開盤就漲停，可能整天鎖住買不回，不先賣"
    return (op, "09:00"), None


def _dt_intra(o, s, t, backup):
    """盤中限價單：只看當天最高／最低價，要「超過」限價才算成交（等於有排隊）。"""
    op, hi, lo, ref = s["o"][t], s.get("h", [float("nan")] * (t + 1))[t], s.get("l", [float("nan")] * (t + 1))[t], s["ref"][t]
    if isnan(hi) or isnan(lo) or isnan(ref):
        return None
    if o["side"] == "B":       # 只有備選會在盤中買：限開盤價，盤中跌破開盤價才成交
        if backup and not _limit_up(op, ref) and lo < op:
            return op, "盤中（跌回開盤價）"
        return None
    if _limit_up(op, ref):     # 開盤就漲停不先賣（同 _dt_open）
        return None
    P = max(op, ref) if backup else ref
    if hi > P:
        return P, "盤中（漲回%s）" % ("開盤價" if backup and op > ref else "平盤價")
    return None


def _settle_dt(a, D, t):
    day = D.days[t]
    avail = a["cash"]
    pend = a["pending"]
    a["pending"] = []
    new_rule = any(o.get("role") for o in pend)     # 2026-11-17 起：主單＋備選、開盤後調整
    mains = [o for o in pend if o.get("role", "main") == "main"]
    backs = [o for o in pend if o.get("role") == "backup"]
    fills = []          # (委託, 價格, 時刻)
    misses = []         # 主單在開盤沒成交的
    for o in mains:
        s = D.raw.get(o["c"])
        if _late(o, day):
            _finish(a, o, day, "沒有下單（雲端更新延遲，開盤前沒來得及送出）")
            continue
        if not s:
            _finish(a, o, day, "沒有成交（查不到行情）")
            continue
        op, cl = s["o"][t], s["c"][t]
        if isnan(op) or isnan(cl) or op <= 0 or cl <= 0:
            _finish(a, o, day, "沒有成交（當天沒有交易）")
            continue
        r, why = _dt_open(o, s, t)
        if r:
            fills.append((o, r[0], r[1]))
        else:
            misses.append((o, why))
    if new_rule:
        # 開盤後：先賣的主單繼續掛平盤價；開盤沒成交幾檔，就依序改下幾檔備選
        slots = len(misses)
        left = []
        for o, why in misses:
            r = _dt_intra(o, D.raw[o["c"]], t, False) if o["side"] == "S" else None
            if r and len(fills) < DT_MAX:
                fills.append((o, r[0], r[1]))
            else:
                left.append((o, why + ("，盤中也沒有漲回平盤" if o["side"] == "S" else "")))
        misses = left
        for o in backs:
            if slots <= 0 or len(fills) >= DT_MAX:
                break
            s = D.raw.get(o["c"])
            if _late(o, day) or not s or isnan(s["o"][t]) or isnan(s["c"][t]) or s["o"][t] <= 0:
                continue
            if any(f[0]["c"] == o["c"] for f in fills):
                continue
            slots -= 1
            r = _dt_intra(o, s, t, True)
            if r:
                fills.append((o, r[0], r[1]))
            else:
                _finish(a, dict(o, act="備選" + ("買進" if o["side"] == "B" else "先賣")), day,
                        "沒有成交（開盤後改下這檔備選，但盤中價格沒到限價）")
    for o, why in misses:
        _finish(a, o, day, "沒有成交（%s）" % why)
    for o, op, at in fills:
        s = D.raw[o["c"]]
        cl = s["c"][t]
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
        tag = "備選" if o.get("role") == "backup" else ""
        _finish(a, dict(o, act=tag + legs[0][0]), day, "成交", op, qty, legs[0][2], legs[0][3], at)
        _finish(a, o2, day, "成交", cl, qty, legs[1][2], legs[1][3])
        a["trades"].append({"c": o["c"], "n": o["n"], "dir": "做多" if o["side"] == "B" else "做空",
                            "in_day": day, "in_at": "%s %s" % (_fmt_day(day), at), "in_px": op,
                            "out_day": day, "out_at": "%s 13:30" % _fmt_day(day), "out_px": cl, "qty": qty,
                            "pnl": round(pnl), "ret": round(pnl / (op * qty), 5), "why": o.get("why"), "made": o["made"],
                            "role": o.get("role") or "main"})


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
        # 2. 買進（主單漲停買不到時，依序改買備選）
        slots = 0
        for o in [x for x in pend if x["side"] == "B" and x["kind"] == phase]:
            bk = o.get("role") == "backup"
            if bk and slots <= 0:
                continue
            s = D.raw.get(o["c"])
            if _late(o, day):
                if not bk:
                    _finish(a, o, day, "沒有下單（雲端更新延遲，%s前沒來得及送出）" % ("開盤" if phase == "open" else "收盤"))
                continue
            px = s[{"open": "o", "close": "c"}[phase]][t] if s else float("nan")
            ref = s["ref"][t] if s else float("nan")
            if isnan(px) or px <= 0:
                if not bk:
                    _finish(a, o, day, "沒有成交（當天沒有交易）")
                continue
            if _limit_up(px, ref):
                if bk:
                    slots -= 1
                    _finish(a, dict(o, act="備選買進"), day, "沒有成交（改買這檔備選，但也漲停）")
                else:
                    slots += 1
                    _finish(a, o, day, "沒有成交（%s漲停，買不到%s）" % ("開盤" if phase == "open" else "收盤",
                                                              "，改買備選" if any(x.get("role") == "backup" for x in pend) else ""))
                continue
            if bk:
                slots -= 1
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
            _finish(a, dict(o, act="備選買進" if bk else "買進"), day, "成交", px, qty, f, 0)
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
    for k, (side, r) in enumerate(cand[:DT_MAX + DT_BACKUP]):
        why = "當沖%s勝算 %.0f%%（扣成本後）、平均每筆 %+.2f%%" % ("先買後賣" if side == "B" else "先賣後買", r["win"] * 100, r["avg"] * 100)
        if r.get("why"):
            why += "；" + "、".join(r["why"][:2])
        if k < DT_MAX:
            role = "main"
            plan = ("開盤價買進（開盤就漲停則放棄）、收盤價賣出" if side == "B" else
                    "開盤前掛平盤價先賣：開在平盤以上就用開盤價成交，開低就繼續掛著、盤中漲回平盤才成交；收盤價買回")
        else:
            role = "backup"
            plan = "備選第 %d 順位：主單開盤沒成交時才改下，%s；收盤價%s" % (
                k - DT_MAX + 1, "限開盤價買進（盤中跌破開盤價才成交）" if side == "B" else "限開盤價先賣、不低於平盤（盤中漲過才成交）",
                "賣出" if side == "B" else "買回")
        out.append({"id": _oid(a), "sig": day, "made": made, "c": r["c"], "n": r["n"], "side": side, "kind": "open",
                    "amt": round(eq / DT_MAX), "why": why, "plan": plan, "role": role, "rank": k + 1})
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
    for k, (lv, _, r, hs) in enumerate(cand[:ST_MAX + ST_BACKUP]):
        why = "短線%s，跑贏大盤機率 %s" % ("建議買" if lv == 0 else "相對看好", "—" if hs.get("pb") is None else "%.0f%%" % (hs["pb"] * 100))
        plan = "%s買進，第 %d 個交易日%s賣出" % (KIND_TXT[ent], ST_H, KIND_TXT[ext])
        if k >= ST_MAX:
            plan = "備選第 %d 順位：主單%s漲停買不到時才改買；%s" % (k - ST_MAX + 1, KIND_TXT[ent].replace("價", ""), plan)
        out.append({"id": _oid(a), "sig": day, "made": made, "c": r["c"], "n": r["n"], "side": "B", "kind": ent, "exit": ext,
                    "amt": round(eqv / ST_SLOTS), "why": why, "plan": plan,
                    "role": "main" if k < ST_MAX else "backup", "rank": k + 1})
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
    # 盤中即時觀察（robot_live.py）查行情時要知道上市或上櫃
    mk = getattr(D, "market", None) or {}
    cs = {o["c"] for a in A.values() for o in a["pending"]} | {p["c"] for a in A.values() for p in a["pos"]}
    st["mkt"] = {c: ("otc" if mk.get(c) == "上櫃" else "tse") for c in sorted(cs) if mk.get(c)}
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
        pend = [{x: o.get(x) for x in ("c", "n", "side", "kind", "made", "why", "plan", "amt", "qty", "role", "rank")} for o in a["pending"]]
        out["acct"][k] = {"init": a["init"], "start": a["start"], "stats": _stats(a, None), "pos": pos, "pending": pend,
                          "orders": a["orders"][-400:][::-1], "trades": a["trades"][-400:][::-1], "eq": a["eq"][-500:]}
    return out
