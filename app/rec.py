# -*- coding: utf-8 -*-
"""買賣建議。

原則：只在「過去實測真的有效」的地方才喊買或賣。
1. 每天把股票依分數分成 10 組，記錄每一組之後真正比大盤多漲（或少漲）多少。
2. 第 t 天要給建議時，只看「結果已經揭曉」的最近 60 個交易日：
   某一組平均比大盤多賺超過門檻 → 這一組的股票標「買進」；少賺超過門檻 → 標「賣出」；其他「觀望」。
3. 模型最近若沒有預測力（分數和實際漲跌的相關係數 ≤ 0），一律觀望，不硬給建議。
4. 門檻有幾種鬆緊，每天用過去照建議操作的實際成績自動挑最準的一種。
5. 同樣的規則套用在過去每一天，公開「照建議操作」的實際成績。
"""
import math

H = {"short": 5, "mid": 20, "long": 60}
HZ_TXT = {"short": "短線（約 1 週）", "mid": "波段（約 1 個月）", "long": "長線（約 3 個月）"}
BASE_THR = {"short": 0.005, "mid": 0.015, "long": 0.03}     # 比大盤多賺／少賺的基本門檻
MULTS = [0.5, 1.0, 1.5, 2.0]
WINS = [60, 120]         # 看最近幾個「已揭曉」的交易日（每天依實測自動挑）
MIN_VAL = 3e7            # 每天平均成交 3000 萬以上才給建議
MARGIN = 0.0005


def isnan(x):
    return x is None or x != x


def _q(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(len(xs) * p)))]


def build(D, A_all, res, stocks, tuning=None):
    pct_hist = res.get("pct_hist") or {}
    comp_ic = res.get("comp_ic") or {}
    last = D.T - 1
    codes = D.codes
    val20 = {}
    v20s = []
    for i, c in enumerate(codes):
        v = D.raw[c]["val"]
        out_ = [0.0] * D.T
        s_, n_ = 0.0, 0
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
    per_stock = {}
    for hn, h in H.items():
        ph = pct_hist.get(hn) or {}
        days = sorted(ph)
        if not days:
            continue
        # ---- 每天每組（10 組）之後的表現
        dec = {}
        for u in days:
            if u + h > last:
                continue
            pct = ph[u]
            rows = []
            for i, p in pct.items():
                if v20s[i][u] < MIN_VAL:
                    continue
                a0, a1 = A_all[i][u], A_all[i][u + h]
                if isnan(a0) or isnan(a1) or a0 <= 0:
                    continue
                rows.append((p, a1 / a0 - 1))
            if len(rows) < 200:
                continue
            mean = sum(r for _, r in rows) / len(rows)
            bins = [[] for _ in range(10)]
            for p, r in rows:
                bins[min(9, int(p * 10))].append(r)
            dec[u] = (mean, [(sum(b) / len(b) - mean) if b else None for b in bins], bins,
                      [(sum(1 for r in b if r > mean) / len(b)) if b else None for b in bins])
        known = sorted(dec)
        # 模型最近的預測力（只用已揭曉的）
        ics = comp_ic.get(hn) or []

        def recent_ic(t):
            xs = [c for u, c in ics if u <= t - h][-60:]
            return sum(xs) / len(xs) if len(xs) >= 20 else None

        def cal_at(t, WIN):
            us = [u for u in known if t - h - WIN < u <= t - h]
            if len(us) < 20:
                return None
            ex, wr = [], []
            for b in range(10):
                vs = [dec[u][1][b] for u in us if dec[u][1][b] is not None]
                ws = [dec[u][3][b] for u in us if dec[u][3][b] is not None]
                ex.append(sum(vs) / len(vs) if vs else 0.0)
                wr.append(sum(ws) / len(ws) if ws else 0.5)
            return ex, wr

        def labels_at(t, thr, WIN, sides=("buy", "sell")):
            cw = cal_at(t, WIN)
            ic = recent_ic(t)
            ex = cw[0] if cw else None
            if cw is None or ic is None or ic <= 0:
                return None, ex, ic
            wr = cw[1]
            # 只在分數最高的 3 組找買進、最低的 3 組找賣出（和分數方向一致），
            # 而且要「平均多賺超過門檻」且「贏過大盤的次數過半」才算數
            lab = []
            for b in range(10):
                if "buy" in sides and b >= 7 and ex[b] >= thr and wr[b] >= 0.5:
                    lab.append("buy")
                elif "sell" in sides and b <= 2 and ex[b] <= -thr and wr[b] <= 0.5:
                    lab.append("sell")
                else:
                    lab.append("hold")
            return lab, ex, ic

        # ---- 回測：每一種設定（看幾天 × 門檻鬆緊），過去照建議操作的成績
        bt = {}
        for WIN in WINS:
            for mlt in MULTS:
                thr = BASE_THR[hn] * mlt
                bx, sx, bwin, swin, bup, nd, nb, ns = [], [], 0, 0, 0, 0, 0, 0
                for t in known:
                    lab, ex, ic = labels_at(t, thr, WIN)
                    if lab is None:
                        continue
                    nd += 1
                    mean, _, bins, _w = dec[t]
                    for bb in range(10):
                        if lab[bb] == "buy":
                            for r in bins[bb]:
                                bx.append(r - mean)
                                bwin += r > mean
                                bup += r > 0
                            nb += len(bins[bb])
                        elif lab[bb] == "sell":
                            for r in bins[bb]:
                                sx.append(r - mean)
                                swin += r < mean
                            ns += len(bins[bb])
                be = sum(bx) / len(bx) if bx else None
                se = sum(sx) / len(sx) if sx else None
                # 這個方向「過去照做真的有效」才開放：買進要平均多賺且過半贏大盤；賣出要平均少賺且多數輸大盤
                buy_ok = be is not None and nb >= 300 and be >= thr / 2 and bwin / nb >= 0.5
                sell_ok = se is not None and ns >= 300 and se <= -thr / 2 and swin / ns >= 0.55
                bt["%d_%s" % (WIN, mlt)] = {
                    "win_days": WIN, "mult": mlt, "days": nd, "buy_n": nb, "sell_n": ns,
                    "buy_ex": None if be is None else round(be, 5), "buy_win": round(bwin / nb, 4) if nb else None,
                    "buy_up": round(bup / nb, 4) if nb else None,
                    "sell_ex": None if se is None else round(se, 5), "sell_win": round(swin / ns, 4) if ns else None,
                    "buy_ok": buy_ok, "sell_ok": sell_ok,
                    "score": (be if buy_ok else 0) - (se if sell_ok else 0),
                }
        # ---- 依實測挑設定（換設定要明顯比較好）
        prev = tun.get(hn) if isinstance(tun.get(hn), dict) else None
        cands = [v for v in bt.values() if v["buy_ok"] or v["sell_ok"]]
        if cands:
            top = max(v["score"] for v in cands)
            # 成績差不多時，選「看比較多天」的設定（比較穩，不會因為最近幾週的雜訊忽有忽無）
            near = [v for v in cands if v["score"] >= top - max(0.002, abs(top) * 0.05)]
            best = max(near, key=lambda v: (v["win_days"], v["score"]))
            cur = next((v for v in cands if prev and v["win_days"] == prev.get("win") and v["mult"] == prev.get("mult")), None)
            chosen = cur if cur and best["score"] - cur["score"] < MARGIN else best
        else:
            chosen = None
        if chosen:
            tun[hn] = {"win": chosen["win_days"], "mult": chosen["mult"]}
            WIN, mlt = chosen["win_days"], chosen["mult"]
            sides = tuple(x for x, ok in (("buy", chosen["buy_ok"]), ("sell", chosen["sell_ok"])) if ok)
        else:
            WIN, mlt, sides = WINS[0], 1.0, ()
        thr = BASE_THR[hn] * mlt
        # ---- 今天的建議
        lab, ex, ic = labels_at(last, thr, WIN, sides) if sides else (None, None, recent_ic(last))
        if ex is None:
            cw = cal_at(last, WIN)
            ex = cw[0] if cw else None
        # 今天每組的停損／目標參考（最近 60 天、已揭曉，該組實際報酬的第 20、80 百分位）
        us = [u for u in known if last - h - WIN < u <= last - h]
        q = []
        for b in range(10):
            pool = [r for u in us for r in dec[u][2][b]]
            q.append((_q(pool, 0.2), _q(pool, 0.8), sum(1 for r in pool if r > 0) / len(pool) if pool else None))
        pct_last = ph.get(last) or {}
        for i, p in pct_last.items():
            b = min(9, int(p * 10))
            d = per_stock.setdefault(codes[i], {})
            d[hn] = {"a": (lab[b] if lab else "hold"), "ex": round(ex[b], 4) if ex else None,
                     "lo": q[b][0], "hi": q[b][1], "up": q[b][2], "b": b, "p": round(p, 4)}
        out["h"][hn] = {"thr": round(thr, 4), "mult": mlt, "win": WIN, "sides": list(sides),
                        "ic": None if ic is None else round(ic, 4),
                        "active": lab is not None, "bt": chosen, "bt_all": bt,
                        "ex": [round(e, 4) for e in ex] if ex else None,
                        "buy_bins": [b for b in range(10) if lab and lab[b] == "buy"],
                        "sell_bins": [b for b in range(10) if lab and lab[b] == "sell"]}
    # ---- 每檔股票的綜合建議
    by = {r["c"]: r for r in stocks}
    alerts = getattr(D, "alerts", {"disp": {}, "warn": {}})
    buys, sells = [], []
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
        r["ra"] = "".join({"buy": "B", "sell": "S"}.get(hs.get(hn, {}).get("a"), "N") if ok else "N" for hn in H)
        r["rx"] = [hs.get(hn, {}).get("ex") for hn in H]
        if not ok:
            r["rn"] = rec.get("why")
        res.setdefault("_recs", {})[code] = rec
        det = (res.get("details") or {}).get(code)
        if det and rec.get("h"):
            hz = det[1].get(rec["h"]) or {}
            rec["why"] = (hz.get("pos") if rec["a"] == "買進" else hz.get("neg")) or []
            rec["why"] = rec["why"][:3]
        if rec["a"] == "買進":
            buys.append(rec | {"c": code, "n": r["n"], "px": px, "chg": r["chg"], "ind": r.get("ind"), "s": r["s"]})
        elif rec["a"] == "賣出":
            sells.append(rec | {"c": code, "n": r["n"], "px": px, "chg": r["chg"], "ind": r.get("ind"), "s": r["s"]})
    # 排序：越多期間一致的越前面，其次看分數排名（買進由高到低、賣出由低到高）
    buys.sort(key=lambda x: (-x.get("k", 1), -(x.get("p") or 0)))
    sells.sort(key=lambda x: (-x.get("k", 1), x.get("p") or 1))
    out["buys"] = buys[:150]
    out["sells"] = sells[:150]
    out["n_buy"], out["n_sell"] = len(buys), len(sells)
    return out, tun


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
    if not pick:
        return {"a": "觀望", "why": "目前沒有明顯的優勢", "k": 0, "hs": hs}
    # 選「超出門檻最多」的期間當主要建議
    best = max(pick, key=lambda hn: abs(hs[hn]["ex"] or 0) / BASE_THR[hn])
    x = hs[best]
    act = "買進" if buy else "賣出"
    out = {"a": act, "h": best, "htxt": HZ_TXT[best], "k": len(pick), "ex": x["ex"], "up": x["up"], "hs": hs,
           "p": x.get("p")}
    if px:
        if act == "買進":
            out["stop"] = round(px * (1 + min(x["lo"] or -0.05, -0.02)), 2)
            out["target"] = round(px * (1 + max(x["hi"] or 0.05, 0.02)), 2)
        else:
            out["stop"] = round(px * (1 + max(x["hi"] or 0.05, 0.02)), 2)     # 放空／避開時的反向停損
            out["target"] = round(px * (1 + min(x["lo"] or -0.05, -0.02)), 2)
    out["strength"] = "強" if len(pick) >= 2 else "中"
    return out
