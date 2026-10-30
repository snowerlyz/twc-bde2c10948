# -*- coding: utf-8 -*-
"""買賣建議（每檔股票、每個期間：建議買／相對看好／中立／相對看淡／建議賣）。

原則：只在「過去實測真的有效」的地方才喊買或賣，而且每天檢查準確度。
1. 「大盤」＝加權指數。建議買對＝之後跑贏加權指數；建議賣對＝之後跑輸加權指數。
2. 篩選嚴格度有幾種（分數排名前 30%、20%、10%、5%、2%；建議賣是後段同樣比例）。
   第 t 天只看「結果已經揭曉」的最近 60 個交易日，算每一種嚴格度的準確度：
   有 60% 以上的就挑最寬的那一種；沒有的話挑最準的一種，但至少要 55%。
3. 同樣的規則套用在過去每一天（walk-forward，只用當時已知資料），公開照做的實際成績；
   最近 60 天的實際成績（有前瞻實測時取較低者）低於 55% → 不標建議，改標「相對看好／看淡」。
4. 達不到 55% 時，分數最前（最後）的一批改標「相對看好／相對看淡」，並寫明準確度，
   讓清單不會是空的，但也不假裝有把握。
"""
import math
import os

H = {"short": 5, "mid": 20, "long": 60}
HZ_TXT = {"short": "短線（約 1 週）", "mid": "波段（約 1 個月）", "long": "長線（約 3 個月）"}
BASE_THR = {"short": 0.005, "mid": 0.015, "long": 0.03}     # 只用來比較不同期間的預期差距大小
MIN_VAL = 3e7            # 每天平均成交 3000 萬以上才給建議
# 準確度臨界值（使用者 2026-10-28 設定）
ACC_PASS = 0.60          # 60% 以上合格
ACC_FAIL = 0.55          # 低於 55% 不合格 → 不標「建議」，改標「相對看好／看淡」
ACC_DAYS = 60            # 看最近 60 個已揭曉的交易日
ACC_MIN_N = 300          # 前瞻實測樣本（檔次）太少不下判斷
CUTS = [0.70, 0.80, 0.90, 0.95, 0.98]   # 篩選嚴格度：分數排名百分位
CUT_MIN_N = 100          # 某種嚴格度在 60 天內至少要有這麼多檔次才評估
WATCH_MIN_CUT = 0.90     # 「相對看好／看淡」只在前（後）10% 以內挑
RANK_LIQ = os.environ.get("TWC_RANK_LIQ") == "1"   # 研究開關：只在成交足夠的股票之間排名


def isnan(x):
    return x is None or x != x


def _q(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(len(xs) * p)))]


def _status(rate):
    if rate is None:
        return "資料不足"
    return "合格" if rate >= ACC_PASS else ("警示" if rate >= ACC_FAIL else "不合格")


def _choose(acc):
    """依最近 60 天各嚴格度的準確度挑一種。回傳 (嚴格度, "ok"／"watch"／None)。"""
    ok = [c for c in CUTS if acc.get(c, 0) >= ACC_PASS]
    if ok:
        return ok[0], "ok"
    if acc:
        c = max(acc, key=lambda k: (acc[k], k))
        if acc[c] >= ACC_FAIL:
            return c, "ok"
        cs = [k for k in acc if k >= WATCH_MIN_CUT]
        if cs:
            return max(cs, key=lambda k: (acc[k], k)), "watch"
    return None, None


def build(D, A_all, res, stocks, tuning=None, live=None):
    if os.environ.get("TWC_REC_DUMP"):      # 研究用：把輸入存起來，方便離線做實驗
        import pickle
        with open(os.environ["TWC_REC_DUMP"], "wb") as f:
            pickle.dump({"days": D.days, "codes": D.codes, "pct_hist": res.get("pct_hist"), "comp_ic": res.get("comp_ic"),
                         "A": [list(a) for a in A_all], "val": [list(D.raw[c]["val"]) for c in D.codes],
                         "tx": list(D.mkt["taiex"])}, f)
    pct_hist = res.get("pct_hist") or {}
    last = D.T - 1
    codes = D.codes
    tx = D.mkt["taiex"]
    val20 = {}
    v20s = []
    for i, c in enumerate(codes):
        v = D.raw[c]["val"]
        out_ = [0.0] * D.T
        s_ = 0.0
        q_ = []
        for t in range(D.T):
            x = v[t]
            x = 0.0 if isnan(x) else x
            q_.append(x)
            s_ += x
            if len(q_) > 20:
                s_ -= q_.pop(0)
            out_[t] = s_ / len(q_)
        v20s.append(out_)
        val20[i] = out_[-1]
    out = {"day": D.days[last], "h": {}}
    tun = dict((tuning or {}).get("rec") or {})
    # ---- 逐檔的「跑贏加權指數」機率（有 numpy 時）；評價的排序改用這個機率
    PB = None
    try:
        import prob as _pb
        if _pb.available() and os.environ.get("TWC_NO_PB") != "1":
            PB = _pb.build(D, A_all, pct_hist, v20s, MIN_VAL)
    except Exception as e:  # 機率模型失敗時，退回原本的分組統計
        import traceback
        from util import log
        log("跑贏大盤機率模型失敗：%s\n%s" % (e, traceback.format_exc()))
        PB = None
    per_stock = {}
    for hn, h in H.items():
        ph = pct_hist.get(hn) or {}
        if not ph:
            continue
        pbh = (PB or {}).get(hn, {}).get("pb") or {}

        def rank_of(u):
            """第 u 天的排序依據：有機率就用機率的排名，沒有就用綜合分數的排名。"""
            pb = pbh.get(u)
            if not pb:
                return ph[u]
            if RANK_LIQ:
                # 只在成交足夠（會給評價）的股票之間排名；成交太少的放中間（反正一律中立）
                order = sorted((i for i in pb if v20s[i][u] >= MIN_VAL), key=lambda i: pb[i])
                n = len(order)
                rk = {i: 0.5 for i in pb}
                rk.update({i: (j + 1) / n for j, i in enumerate(order)})
                return rk
            order = sorted(pb, key=lambda i: pb[i])
            n = len(order)
            return {i: (j + 1) / n for j, i in enumerate(order)}
        # ---- 每天（結果已揭曉的）：每檔 (分數百分位, 報酬, 比加權指數多賺)
        data = {}
        for u in sorted(ph):
            if u + h > last or isnan(tx[u]) or isnan(tx[u + h]) or tx[u] <= 0:
                continue
            bm = tx[u + h] / tx[u] - 1
            rows = []
            for i, p in rank_of(u).items():
                if v20s[i][u] < MIN_VAL:
                    continue
                a0, a1 = A_all[i][u], A_all[i][u + h]
                if isnan(a0) or isnan(a1) or a0 <= 0:
                    continue
                r = a1 / a0 - 1
                rows.append((p, r, r - bm))
            if len(rows) >= 200:
                data[u] = rows
        known = sorted(data)

        def pick(rows, sd, c):
            return [x for x in rows if (x[0] >= c if sd == "buy" else x[0] <= 1 - c)]

        st = {}
        for sd in ("buy", "sell"):
            for c in CUTS:
                dd = {}
                for u in known:
                    xs = pick(data[u], sd, c)
                    good = sum(1 for x in xs if (x[2] > 0 if sd == "buy" else x[2] < 0))
                    dd[u] = (good, len(xs), sum(x[2] for x in xs), sum(1 for x in xs if x[1] > 0))
                st[(sd, c)] = dd

        def trail(t, sd):
            tr = [u for u in known if t - h - ACC_DAYS < u <= t - h]
            acc = {}
            if len(tr) >= 20:
                for c in CUTS:
                    w = sum(st[(sd, c)][u][0] for u in tr)
                    n = sum(st[(sd, c)][u][1] for u in tr)
                    if n >= CUT_MIN_N:
                        acc[c] = w / n
            return acc, tr

        # ---- walk-forward：過去每一天照「當時」的規則挑，之後真正的成績
        wf = {"buy": {}, "sell": {}}
        for sd in ("buy", "sell"):
            for t in known:
                acc, _ = trail(t, sd)
                c, kind = _choose(acc)
                if c is not None:
                    wf[sd][t] = (kind, c) + st[(sd, c)][t]
        lv = (((live or {}).get("rh") or {}).get(hn) or {})
        gate, label, sides, bt = {}, {}, [], {"days": 0}
        for sd in ("buy", "sell"):
            ok_days = [t for t in known if t in wf[sd] and wf[sd][t][0] == "ok"]
            rec_days = [t for t in ok_days if t in set(known[-ACC_DAYS:])]

            def agg(ts):
                w = sum(wf[sd][t][2] for t in ts)
                n = sum(wf[sd][t][3] for t in ts)
                return (w / n if n else None), n, (sum(wf[sd][t][4] for t in ts) / n if n else None), \
                    (sum(wf[sd][t][5] for t in ts) / n if n else None)
            r_all, n_all, ex_all, up_all = agg(ok_days)
            r_60, n_60, _, _ = agg(rec_days)
            lx = lv.get(sd) or {}
            r_lv = lx.get("win") if (lx.get("n") or 0) >= ACC_MIN_N else None
            rates = [x for x in ((r_60 if n_60 >= CUT_MIN_N else None), r_lv) if x is not None]
            rate = min(rates) if rates else None
            acc, tr = trail(last, sd)
            c, kind = _choose(acc)
            off = kind == "ok" and rate is not None and rate < ACC_FAIL
            if off:
                cs = [k for k in acc if k >= WATCH_MIN_CUT]
                c = max(cs, key=lambda k: (acc[k], k)) if cs else c
                kind = "watch"
            t0 = last - h
            td = wf[sd].get(t0)
            # 今天的參考數字：所選嚴格度在最近 60 天的實際表現
            pool = [x for u in tr for x in pick(data[u], sd, c)] if c is not None else []
            label[sd] = {"c": c, "kind": kind,
                         # 用中位數（典型的一檔），不用平均數：平均數容易被少數大漲股拉高，和準確度方向矛盾
                         "ex": _q([x[2] for x in pool], 0.5),
                         "up": sum(1 for x in pool if x[1] > 0) / len(pool) if pool else None,
                         "lo": _q([x[1] for x in pool], 0.2), "hi": _q([x[1] for x in pool], 0.8)}
            if kind == "ok":
                sides.append(sd)
            gate[sd] = {"rate": None if rate is None else round(rate, 4),
                        "bt": None if r_60 is None else round(r_60, 4), "bt_n": n_60,
                        "bt_all": None if r_all is None else round(r_all, 4), "bt_all_n": n_all,
                        "live": None if r_lv is None else round(r_lv, 4), "live_n": lx.get("n") or 0,
                        "status": _status(rate) if kind == "ok" or off else ("相對" if kind == "watch" else "資料不足"),
                        "off": off, "mode": {"ok": "建議", "watch": "相對"}.get(kind),
                        "cut": c, "trail": None if c is None or c not in acc else round(acc[c], 4),
                        "today": round(td[2] / td[3], 4) if td and td[3] and td[0] == "ok" else None,
                        "today_n": td[3] if td and td[0] == "ok" else 0}
            bt["days"] = max(bt["days"], len(ok_days))
            bt[sd + "_win"] = None if r_all is None else round(r_all, 4)
            bt[sd + "_ex"] = None if ex_all is None else round(ex_all, 5)
            bt[sd + "_up"] = None if up_all is None else round(up_all, 4)
            bt[sd + "_n"] = n_all
            bt[sd + "_ok"] = kind == "ok"
        tun[hn] = {"cut": {sd: label[sd]["c"] for sd in label}, "kind": {sd: label[sd]["kind"] for sd in label}}
        timing = _timing(D, A_all, rank_of, sorted(ph), h, last, v20s)
        # ---- 今天每檔股票
        pbt = (PB or {}).get(hn, {}).get("today") or {}
        for i, p in (rank_of(last) if last in ph else {}).items():
            a = "hold"
            for sd in ("buy", "sell"):
                L_ = label[sd]
                if L_["c"] is None:
                    continue
                if (p >= L_["c"]) if sd == "buy" else (p <= 1 - L_["c"]):
                    a = sd if L_["kind"] == "ok" else "w" + sd
                    x = L_
            d = per_stock.setdefault(codes[i], {})
            if a == "hold":
                d[hn] = {"a": "hold", "ex": None, "lo": None, "hi": None, "up": None, "p": round(p, 4)}
            else:
                d[hn] = {"a": a, "ex": None if x["ex"] is None else round(x["ex"], 4), "lo": x["lo"], "hi": x["hi"],
                         "up": None if x["up"] is None else round(x["up"], 3), "p": round(p, 4)}
            q = pbt.get(i)
            if q:      # 逐檔的機率與預期（取代整組共用的數字）
                d[hn].update({"pb": q["pb"], "up": q["pu"], "ex": q["ex"], "lo": q["lo"], "hi": q["hi"]})
        out["h"][hn] = {"sides": sides, "active": bool(sides), "gate": gate, "bt": bt, "timing": timing,
                        "prob": (PB or {}).get(hn, {}).get("track"),
                        "watch": [sd for sd in ("buy", "sell") if label[sd]["kind"] == "watch"]}
    # ---- 每檔股票的綜合建議
    by = {r["c"]: r for r in stocks}
    alerts = getattr(D, "alerts", {"disp": {}, "warn": {}})
    buys, sells, wbuys, wsells = [], [], [], []
    for code, hs in per_stock.items():
        r = by.get(code)
        if not r or r.get("etf"):
            continue
        i = D.idx.get(code)
        px = r.get("px")
        v20 = val20.get(i, 0)
        rec = _combine(hs, px, v20, code in alerts.get("disp", {}), r)
        r["rec"] = {"a": rec["a"], "h": rec.get("h"), "ex": rec.get("ex")}
        # 每個期間各自的評價：B＝建議買、S＝建議賣、N＝中立（成交太少、處置股一律中立）
        ok = "hs" in rec or rec["a"] != "觀望"
        r["ra"] = "".join({"buy": "B", "sell": "S", "wbuy": "b", "wsell": "s"}.get(hs.get(hn, {}).get("a"), "N") if ok else "N"
                          for hn in H)
        r["rx"] = [hs.get(hn, {}).get("ex") for hn in H]
        r["rb"] = [hs.get(hn, {}).get("pb") for hn in H]
        if not ok:
            r["rn"] = rec.get("why")
        res.setdefault("_recs", {})[code] = rec
        det = (res.get("details") or {}).get(code)
        if det and rec.get("h"):
            hz = det[1].get(rec["h"]) or {}
            rec["why"] = (hz.get("pos") if rec["a"] in ("買進", "相對看好") else hz.get("neg")) or []
            rec["why"] = rec["why"][:3]
        if rec["a"] == "買進":
            buys.append(rec | {"c": code, "n": r["n"], "px": px, "chg": r["chg"], "ind": r.get("ind"), "s": r["s"]})
        elif rec["a"] == "賣出":
            sells.append(rec | {"c": code, "n": r["n"], "px": px, "chg": r["chg"], "ind": r.get("ind"), "s": r["s"]})
        elif rec["a"] == "相對看好":
            wbuys.append(rec | {"c": code, "n": r["n"], "px": px, "chg": r["chg"], "ind": r.get("ind"), "s": r["s"]})
        elif rec["a"] == "相對看淡":
            wsells.append(rec | {"c": code, "n": r["n"], "px": px, "chg": r["chg"], "ind": r.get("ind"), "s": r["s"]})
    # 排序：越多期間一致的越前面，其次看分數排名（買進由高到低、賣出由低到高）
    buys.sort(key=lambda x: (-x.get("k", 1), -(x.get("p") or 0)))
    sells.sort(key=lambda x: (-x.get("k", 1), x.get("p") or 1))
    wbuys.sort(key=lambda x: -(x.get("p") or 0))
    wsells.sort(key=lambda x: x.get("p") or 1)
    out["wbuys"], out["wsells"] = wbuys[:150], wsells[:150]
    out["buys"] = buys[:150]
    out["sells"] = sells[:150]
    out["n_buy"], out["n_sell"] = len(buys), len(sells)
    out["acc_rule"] = {"pass": ACC_PASS, "fail": ACC_FAIL, "days": ACC_DAYS}
    # 每天的準確度紀錄（看趨勢用，保留最近 120 天）
    lg = dict(tun.get("acc_log") or {})
    lg[out["day"]] = {hn: {sd: [g["rate"], g["today"], g["status"]] for sd, g in (x.get("gate") or {}).items()}
                      for hn, x in out["h"].items()}
    tun["acc_log"] = {k: lg[k] for k in sorted(lg)[-120:]}
    out["acc_log"] = tun["acc_log"]
    return out, tun


TM_COST = 0.001425 * 2 * 0.6 + 0.003
TM_DAYS = 250
TM_CUT = 0.95


def _timing(D, A_all, rank_of, days, h, last, v20s):
    """買賣時機：用最近 250 個已揭曉交易日的訊號（排名前 5%／後 5%），比較
    「隔天開盤買 or 隔天收盤前買」×「到期那天開盤賣 or 收盤賣」，以及賣出訊號「隔天開盤賣 or 收盤賣」。
    全部用當時已經揭曉的結果（walk-forward），每天重算。"""
    codes = D.codes
    known = [u for u in days if u + 1 + h <= last][-TM_DAYS:]
    combos = {"open_close": [], "close_close": [], "open_open": [], "close_open": []}
    sell_diff = []
    for u in known:
        rk = rank_of(u)
        e0, e1 = u + 1, u + 1 + h
        for i, p in rk.items():
            if v20s[i][u] < MIN_VAL or (p < TM_CUT and p > 1 - TM_CUT):
                continue
            s = D.raw[codes[i]]
            A = A_all[i]
            o0, c0, o1, c1 = s["o"][e0], s["c"][e0], s["o"][e1], s["c"][e1]
            if any(isnan(x) or x <= 0 for x in (o0, c0, o1, c1, A[e0], A[e1])):
                continue
            ent = {"open": o0 * A[e0] / c0, "close": A[e0]}
            ext = {"open": o1 * A[e1] / c1, "close": A[e1]}
            if p >= TM_CUT:
                for k in combos:
                    a, b = k.split("_")
                    combos[k].append(ext[b] / ent[a] - 1 - TM_COST)
            else:
                sell_diff.append(o0 / c0 - 1)          # 隔天開盤賣比收盤賣多拿（正＝開盤賣比較好）
    if not combos["open_close"]:
        return None
    avg = {k: sum(v) / len(v) for k, v in combos.items()}
    win = {k: sum(1 for x in v if x > 0) / len(v) for k, v in combos.items()}
    best = max(avg, key=avg.get)
    # 收盤買比開盤買好的比例（逐筆）
    better_close = sum(1 for a, b in zip(combos["close_close"], combos["open_close"]) if a > b) / len(combos["open_close"])
    return {"n": len(combos["open_close"]), "days": len(known), "from": D.days[known[0]], "to": D.days[known[-1]],
            "avg": {k: round(v, 4) for k, v in avg.items()}, "win": {k: round(v, 3) for k, v in win.items()},
            "best": best, "better_close": round(better_close, 3),
            "sell_n": len(sell_diff), "sell_open_gain": round(sum(sell_diff) / len(sell_diff), 4) if sell_diff else None,
            "sell_open_better": round(sum(1 for x in sell_diff if x > 0) / len(sell_diff), 3) if sell_diff else None}


def _combine(hs, px, v20, disposed, row):
    """把三個期間的看法合成一個建議。"""
    if v20 < MIN_VAL:
        return {"a": "觀望", "why": "成交量太小，不給建議", "k": 0}
    if disposed:
        return {"a": "觀望", "why": "處置股，交易受限制", "k": 0}
    buy = [hn for hn in H if hs.get(hn, {}).get("a") == "buy"]
    sell = [hn for hn in H if hs.get(hn, {}).get("a") == "sell"]
    if buy and sell:
        return {"a": "觀望", "why": "短中長期看法不一致", "k": 0, "hs": hs}
    pick = buy or sell
    act = "買進" if buy else "賣出"
    if not pick:
        wb = [hn for hn in H if hs.get(hn, {}).get("a") == "wbuy"]
        ws = [hn for hn in H if hs.get(hn, {}).get("a") == "wsell"]
        if (wb and ws) or not (wb or ws):
            return {"a": "觀望", "why": "目前沒有明顯的優勢", "k": 0, "hs": hs}
        pick = wb or ws
        act = "相對看好" if wb else "相對看淡"
    # 選「超出門檻最多」的期間當主要建議
    best = max(pick, key=lambda hn: abs(hs[hn]["ex"] or 0) / BASE_THR[hn])
    x = hs[best]
    out = {"a": act, "h": best, "htxt": HZ_TXT[best], "k": len(pick), "ex": x["ex"], "up": x["up"], "pb": x.get("pb"), "hs": hs,
           "p": x.get("p")}
    if px:
        if act in ("買進", "相對看好"):
            out["stop"] = round(px * (1 + min(x["lo"] or -0.05, -0.02)), 2)
            out["target"] = round(px * (1 + max(x["hi"] or 0.05, 0.02)), 2)
        else:
            out["stop"] = round(px * (1 + max(x["hi"] or 0.05, 0.02)), 2)     # 放空／避開時的反向停損
            out["target"] = round(px * (1 + min(x["lo"] or -0.05, -0.02)), 2)
    out["strength"] = "強" if len(pick) >= 2 else "中"
    return out
