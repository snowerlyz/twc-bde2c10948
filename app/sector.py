# -*- coding: utf-8 -*-
"""類股、國際股市、消息影響、盤後綜合報告。

全部用已經載入的資料計算（不另外抓網路）：
- 類股：每天的類股指數（成員等權平均）、漲跌、資金、法人、平均分數、新聞氣氛、和國際股市的連動。
- 類股排名實測：過去每天依「類股平均分數」排名，之後真正漲跌的對照。
- 國際股市：各市場趨勢、和台股的連動（美歐看「隔夜」影響、亞洲看「同一天」的連動）。
- 消息影響：新聞發布後，該股相對大盤的實際表現（資料逐日累積）。
- 盤後綜合報告：把以上整理成白話摘要。
"""
import bisect
import math

NAN = float("nan")


def isnan(x):
    return x is None or x != x


def _mean(xs):
    xs = [x for x in xs if not isnan(x)]
    return sum(xs) / len(xs) if xs else NAN


def _ols(xs, ys):
    """回傳 (beta, corr, n)。"""
    n = len(xs)
    if n < 40:
        return None, None, n
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx <= 0 or syy <= 0:
        return None, None, n
    return sxy / sxx, sxy / math.sqrt(sxx * syy), n


def _nz(x):
    return 0.0 if isnan(x) else x


def _r(x, d=4):
    return None if isnan(x) else round(x, d)


SECTOR_ALIAS = {"金融業": "金融保險業"}
SKIP_SECTORS = {"", "ETF", "存託憑證", "其他"}

# 國際市場分組：美歐收盤在台股收盤之後 → 看「隔夜」影響；亞洲和台股同時交易 → 看同一天的連動
OVERNIGHT = ["^SOX", "^IXIC", "^GSPC", "^DJI", "TSM", "NVDA", "^VIX", "^TNX", "DX-Y.NYB", "CL=F", "GC=F", "^GDAXI", "TWD=X"]
ASIA = ["^N225", "^KS11", "^HSI", "000001.SS"]
REGION = {"^SOX": "美國", "^IXIC": "美國", "^GSPC": "美國", "^DJI": "美國", "TSM": "美國", "NVDA": "美國",
          "^VIX": "美國", "^TNX": "美國", "DX-Y.NYB": "美國", "CL=F": "商品", "GC=F": "商品", "^GDAXI": "歐洲",
          "TWD=X": "匯率", "^N225": "亞洲", "^KS11": "亞洲", "^HSI": "亞洲", "000001.SS": "亞洲"}
GNAME = {"^SOX": "費城半導體", "^IXIC": "那斯達克", "^GSPC": "標普 500", "^DJI": "道瓊工業", "TSM": "台積電 ADR",
         "NVDA": "輝達", "^VIX": "美股恐慌指數", "^TNX": "美國 10 年債利率", "DX-Y.NYB": "美元指數", "CL=F": "國際油價",
         "GC=F": "黃金", "^GDAXI": "德國股市", "TWD=X": "美元兌新台幣", "^N225": "日本股市", "^KS11": "韓國股市",
         "^HSI": "香港股市", "000001.SS": "上海股市"}
# 這些用「變化量」而不是漲跌幅
LEVEL = {"^VIX", "^TNX"}


def _pct(x, d=1):
    return "%.*f%%" % (d, abs(x) * 100)


def _ud(x, up="漲", dn="跌"):
    return up if x >= 0 else dn


def _yi(x):
    """元 → 「x 億」或「x 兆」"""
    a = abs(x) / 1e8
    if a >= 10000:
        return "%.2f 兆" % (a / 10000)
    return ("%.0f 億" if a >= 100 else "%.1f 億") % a


# ====================================================================== 主程式

def build(D, A_all, res, stocks, dt=None):
    T, days, last = D.T, D.days, D.T - 1
    idx = D.idx
    by_code = {r["c"]: r for r in stocks}
    # ---- 每檔每天的報酬
    rets = {}
    for code, i in idx.items():
        A = A_all[i]
        s = D.raw[code]
        r = [NAN] * T
        for t in range(1, T):
            a0, a1 = A[t - 1], A[t]
            if not isnan(a0) and not isnan(a1) and a0 > 0 and not isnan(s["c"][t]):
                r[t] = max(-0.11, min(0.11, a1 / a0 - 1))
        rets[code] = r
    tx = D.mkt["taiex"]
    tx_ret = [NAN] + [(tx[t] / tx[t - 1] - 1) if not isnan(tx[t]) and not isnan(tx[t - 1]) and tx[t - 1] else NAN
                      for t in range(1, T)]
    # ---- 類股成員（最近 20 天平均成交 500 萬以上）
    members = {}
    for code, i in idx.items():
        ind = SECTOR_ALIAS.get(D.industry.get(code, ""), D.industry.get(code, ""))
        if ind in SKIP_SECTORS:
            continue
        val = D.raw[code]["val"]
        v20 = _mean(val[-20:])
        if isnan(v20) or v20 < 5e6:
            continue
        members.setdefault(ind, []).append(code)
    members = {k: v for k, v in members.items() if len(v) >= 4}
    # 類股每日報酬（等權）
    sret = {}
    for ind, cs in members.items():
        sret[ind] = [NAN] + [_mean([rets[c][t] for c in cs]) for t in range(1, T)]
    glob = getattr(D, "glob", {}) or {}
    graw = getattr(D, "glob_raw", {}) or {}

    def g_overnight_series(sym):
        x = glob.get(sym)
        if not x:
            return None
        out = [NAN] * T
        for t in range(1, T):
            a, b = x[t - 1], x[t]
            if isnan(a) or isnan(b) or a == 0:
                continue
            out[t] = (b - a) if sym in LEVEL else (b / a - 1)
        return out

    gser = {sym: g_overnight_series(sym) for sym in OVERNIGHT}
    gser = {k: v for k, v in gser.items() if v}
    # 最新的隔夜變化：海外收盤日期 >= 台股最後一天
    overnight = {}
    for sym in OVERNIGHT:
        x = graw.get(sym)
        if not x or not x.get("s") or sym not in glob:
            continue
        ds = sorted(x["s"])
        if ds[-1] >= days[last]:
            base = glob[sym][last]
            v = x["s"][ds[-1]]
            if not isnan(base) and base:
                overnight[sym] = {"day": ds[-1], "chg": (v - base) if sym in LEVEL else (v / base - 1)}

    sectors = _sectors(D, members, sret, rets, by_code, gser, overnight, tx_ret)
    check = _sector_check(D, A_all, res, members)
    glob_out = _global(D, graw, glob, gser, overnight, tx_ret, sectors)
    impact = _news_impact(D, rets, tx_ret, members)
    report = _report(D, stocks, by_code, sectors, glob_out, impact, res, dt, rets)
    return {"day": days[last], "days": days[-120:], "sectors": sectors, "check": check, "impact": impact}, glob_out, report


# ====================================================================== 類股

def _sectors(D, members, sret, rets, by_code, gser, overnight, tx_ret):
    T, days, last = D.T, D.days, D.T - 1
    out = []
    tot_val_today = sum(_nz(D.raw[c]["val"][last]) for cs in members.values() for c in cs)
    tot_val_20 = sum(_nz(_mean(D.raw[c]["val"][-20:])) for cs in members.values() for c in cs)
    news_items = getattr(D, "news_items", None) or []
    mops = getattr(D, "mops_items", None) or []
    cut = days[max(0, last - 2)]
    for ind, cs in members.items():
        r = sret[ind]
        # 類股指數（最近 250 天）
        lvl, v = [], 100.0
        for t in range(T):
            if not isnan(r[t]):
                v *= 1 + r[t]
            lvl.append(v)

        def mom(n):
            return lvl[last] / lvl[last - n] - 1 if last - n >= 0 else NAN
        ma20 = _mean(lvl[-20:])
        ma60 = _mean(lvl[-60:])
        up = sum(1 for c in cs if not isnan(rets[c][last]) and rets[c][last] > 0.0005)
        dn = sum(1 for c in cs if not isnan(rets[c][last]) and rets[c][last] < -0.0005)
        val_today = sum(_nz(D.raw[c]["val"][last]) for c in cs)
        val20 = sum(_nz(_mean(D.raw[c]["val"][-20:])) for c in cs)
        share = val_today / tot_val_today if tot_val_today else NAN
        share20 = val20 / tot_val_20 if tot_val_20 else NAN

        def flow(key, n):
            s = 0.0
            for c in cs:
                raw = D.raw[c]
                for t in range(max(0, last - n + 1), last + 1):
                    f, px = raw[key][t], raw["c"][t]
                    if not isnan(f) and not isnan(px):
                        s += f * px
            return s
        fi1, fi5, it1, it5 = flow("fi", 1), flow("fi", 5), flow("it", 1), flow("it", 5)
        rows = [by_code[c] for c in cs if c in by_code]
        sc = [_mean([x["s"][j] for x in rows if x["s"][j] is not None]) for j in range(3)]
        bull = [sum(1 for x in rows if x["s"][j] is not None and x["s"][j] >= 55) for j in range(3)]
        bear = [sum(1 for x in rows if x["s"][j] is not None and x["s"][j] <= 45) for j in range(3)]
        top_mid = sorted([x for x in rows if x["s"][1] is not None], key=lambda x: -x["s"][1])
        movers = sorted([x for x in rows if x.get("val") and x["val"] >= 0.3], key=lambda x: -(x["chg"] or 0))
        # 新聞
        cset = set(cs)
        nl = [it for it in news_items if it.get("d", "") >= cut and cset.intersection(it.get("codes") or [])]
        ml = [m for m in mops if (m.get("d") or "") >= cut and m.get("c") in cset]
        sents = [it.get("sent", 0) for it in nl] + [m.get("sent", 0) for m in ml]
        pos = sum(1 for x in sents if x > 0.05)
        neg = sum(1 for x in sents if x < -0.05)
        heads = sorted(nl, key=lambda it: (-abs(it.get("sent", 0)), -(it.get("at") or 0)))[:4]
        # 國際連動
        links = []
        for sym, g in gser.items():
            xs, ys = [], []
            for t in range(max(1, last - 200), last + 1):
                if not isnan(g[t]) and not isnan(r[t]) and g[t] != 0:
                    xs.append(g[t])
                    ys.append(r[t])
            b, c, n = _ols(xs, ys)
            if b is not None:
                links.append({"sym": sym, "name": GNAME.get(sym, sym), "beta": b, "corr": c, "n": n})
        links.sort(key=lambda x: -abs(x["corr"]))
        top_links = [x for x in links if abs(x["corr"]) >= 0.15][:3]
        exp = None
        eq = [x for x in top_links if x["sym"] in ("^SOX", "^IXIC", "^GSPC", "^DJI", "TSM", "NVDA")]
        if eq and "^GSPC" in overnight and eq[0]["sym"] in overnight:
            L = eq[0]
            exp = {"sym": L["sym"], "name": L["name"], "move": overnight[L["sym"]]["chg"],
                   "exp": L["beta"] * overnight[L["sym"]]["chg"], "day": overnight[L["sym"]]["day"]}
        o = {
            "ind": ind, "n": len(cs),
            "chg1": _r(r[last]), "chg5": _r(mom(5)), "chg20": _r(mom(20)), "chg60": _r(mom(60)),
            "ma20": _r(lvl[last] / ma20 - 1 if ma20 else NAN), "ma60": _r(lvl[last] / ma60 - 1 if ma60 else NAN),
            "up": up, "dn": dn,
            "val": round(val_today / 1e8, 1), "share": _r(share), "share20": _r(share20),
            "fi1": round(fi1 / 1e8, 2), "fi5": round(fi5 / 1e8, 2), "it1": round(it1 / 1e8, 2), "it5": round(it5 / 1e8, 2),
            "s": [_r(x, 1) for x in sc], "bull": bull, "bear": bear,
            "top": [{"c": x["c"], "n": x["n"], "s": x["s"][1], "chg": x["chg"]} for x in top_mid[:5]],
            "bot": [{"c": x["c"], "n": x["n"], "s": x["s"][1], "chg": x["chg"]} for x in top_mid[-3:][::-1]],
            "movers": [{"c": x["c"], "n": x["n"], "chg": x["chg"]} for x in movers[:3]],
            "losers": [{"c": x["c"], "n": x["n"], "chg": x["chg"]} for x in movers[-3:][::-1]],
            "news": {"n": len(sents), "pos": pos, "neg": neg, "mood": _r(_mean(sents) if sents else 0.0, 3),
                     "heads": [{"t": it["t"], "u": it.get("url"), "s": it.get("sent", 0), "at": it.get("at"),
                                "src": it.get("src")} for it in heads],
                     "mops": [{"c": m["c"], "n": D.names.get(m["c"], m["c"]), "t": m["t"], "s": m.get("sent", 0)}
                              for m in sorted(ml, key=lambda m: -abs(m.get("sent", 0)))[:3]]},
            "links": [{"sym": x["sym"], "name": x["name"], "beta": round(x["beta"], 3), "corr": round(x["corr"], 3)}
                      for x in top_links],
            "exp": None if not exp else {k: (round(v, 4) if isinstance(v, float) else v) for k, v in exp.items()},
            "spark": [round(x, 2) for x in lvl[-120:]],
            "codes": cs,
        }
        o["trend"] = _trend_label(o)
        o["text"] = _sector_text(o)
        out.append(o)
    out.sort(key=lambda x: -(x["s"][1] if x["s"][1] is not None else 0))
    return out


def _trend_label(o):
    a, b = o.get("ma20"), o.get("ma60")
    if a is None or b is None:
        return "資料不足"
    if a > 0 and b > 0:
        return "多頭（站上月線、季線）"
    if a < 0 and b < 0:
        return "空頭（跌破月線、季線）"
    if a > 0:
        return "短線轉強（站上月線）"
    return "短線轉弱（跌破月線）"


def _score_word(s):
    if s is None:
        return "資料不足"
    if s >= 75:
        return "強烈看多"
    if s >= 60:
        return "偏多"
    if s > 40:
        return "中立"
    if s > 25:
        return "偏空"
    return "強烈看空"


def _sector_text(o):
    parts = []
    if o["chg1"] is not None:
        parts.append("今天平均%s %s" % (_ud(o["chg1"]), _pct(o["chg1"], 2)))
    if o["chg20"] is not None:
        parts.append("近一個月%s %s，%s" % (_ud(o["chg20"]), _pct(o["chg20"]), o["trend"].split("（")[0]))
    fi = o["fi5"]
    if abs(fi) >= 1:
        parts.append("外資近 5 天%s約 %s" % ("買進" if fi > 0 else "賣出", _yi(fi * 1e8)))
    if o["share"] is not None and o["share20"]:
        ch = o["share"] / o["share20"] - 1
        if abs(ch) >= 0.15:
            parts.append("成交金額占比%s（資金%s）" % ("明顯放大" if ch > 0 else "明顯縮小", "流入" if ch > 0 else "流出"))
    s1 = o["s"][1]
    if s1 is not None:
        parts.append("未來 1 個月平均 %.0f 分（%s）" % (s1, _score_word(s1)))
    nw = o["news"]
    if nw["n"] >= 3:
        mood = "偏樂觀" if nw["mood"] > 0.05 else "偏悲觀" if nw["mood"] < -0.05 else "好壞參半"
        parts.append("近 3 天 %d 則相關新聞，%s" % (nw["n"], mood))
    if o["links"]:
        L = o["links"][0]
        parts.append("和%s連動最強（%s 漲 1%%，隔天平均%s %.2f%%）" % (
            L["name"], L["name"], "跟著漲" if L["beta"] >= 0 else "反而跌", abs(L["beta"])) if L["sym"] not in LEVEL
                     else "和%s連動最強" % L["name"])
    return "；".join(parts) + "。"


def _sector_check(D, A_all, res, members):
    """類股排名實測：每天依類股平均百分位排名，之後實際漲跌（前 5 名 vs 後 5 名）。"""
    from engine import H, HN
    pct_hist = res.get("pct_hist") or {}
    last = D.T - 1
    idx = D.idx
    out = {}
    for hn in HN:
        h = H[hn]
        ph = pct_hist.get(hn) or {}
        spreads, top_up, top_n, hits = [], 0, 0, []
        for t in sorted(ph):
            if t + h > last:
                continue
            pct = ph[t]
            rows = []
            for ind, cs in members.items():
                ps, fr = [], []
                for c in cs:
                    i = idx.get(c)
                    if i is None or i not in pct:
                        continue
                    a0, a1 = A_all[i][t], A_all[i][t + h]
                    if isnan(a0) or isnan(a1) or a0 <= 0:
                        continue
                    ps.append(pct[i])
                    fr.append(a1 / a0 - 1)
                if len(ps) >= 3:
                    rows.append((sum(ps) / len(ps), sum(fr) / len(fr)))
            if len(rows) < 12:
                continue
            rows.sort(key=lambda x: -x[0])
            top, bot = rows[:5], rows[-5:]
            ta, ba = sum(r for _, r in top) / 5, sum(r for _, r in bot) / 5
            allavg = sum(r for _, r in rows) / len(rows)
            spreads.append(ta - ba)
            top_n += 5
            top_up += sum(1 for _, r in top if r > allavg)
        if spreads:
            out[hn] = {"n": len(spreads), "spread": round(sum(spreads) / len(spreads), 5),
                       "win": round(sum(1 for x in spreads if x > 0) / len(spreads), 4),
                       "top_beat": round(top_up / top_n, 4) if top_n else None}
    return out


# ====================================================================== 國際股市

def _series(graw, sym):
    x = graw.get(sym)
    if not x or not x.get("s"):
        return [], []
    ds = sorted(x["s"])
    return ds, [x["s"][d] for d in ds]


def _global(D, graw, glob, gser, overnight, tx_ret, sectors):
    T, days, last = D.T, D.days, D.T - 1
    rows = []
    for sym in OVERNIGHT + ASIA:
        ds, vs = _series(graw, sym)
        if len(vs) < 70:
            continue
        v = vs[-1]
        lvl = sym in LEVEL

        def ch(n):
            if len(vs) <= n:
                return None
            return (vs[-1] - vs[-1 - n]) if lvl else (vs[-1] / vs[-1 - n] - 1)
        ma20 = sum(vs[-20:]) / 20
        ma60 = sum(vs[-60:]) / 60
        hi, lo = max(vs[-250:]), min(vs[-250:])
        pos52 = (v - lo) / (hi - lo) if hi > lo else 0.5
        if v > ma20 and v > ma60 and ma20 > ma60:
            trend = "多頭"
        elif v < ma20 and v < ma60 and ma20 < ma60:
            trend = "空頭"
        elif v > ma20:
            trend = "反彈中"
        else:
            trend = "回檔中"
        # 和台股的連動
        link = None
        if sym in gser:
            g = gser[sym]
            xs, ys = [], []
            for t in range(max(1, last - 200), last + 1):
                if not isnan(g[t]) and not isnan(tx_ret[t]) and g[t] != 0:
                    xs.append(g[t])
                    ys.append(tx_ret[t])
            b, c, n = _ols(xs, ys)
            if b is not None:
                link = {"kind": "隔夜", "beta": round(b, 3), "corr": round(c, 3), "n": n}
        elif sym in ASIA:
            m = dict(zip(ds, vs))
            xs, ys = [], []
            for t in range(max(1, last - 200), last + 1):
                d = days[t]
                if d not in m or isnan(tx_ret[t]):
                    continue
                j = bisect.bisect_left(ds, d) - 1
                if j < 0 or not vs[j]:
                    continue
                xs.append(m[d] / vs[j] - 1)
                ys.append(tx_ret[t])
            b, c, n = _ols(xs, ys)
            if b is not None:
                link = {"kind": "同一天", "beta": round(b, 3), "corr": round(c, 3), "n": n}
        sens = []
        for s in sectors:
            for L in s["links"]:
                if L["sym"] == sym:
                    sens.append({"ind": s["ind"], "beta": L["beta"], "corr": L["corr"]})
        sens.sort(key=lambda x: -abs(x["corr"]))
        ov = overnight.get(sym)
        row = {"sym": sym, "name": GNAME.get(sym, sym), "region": REGION.get(sym, ""), "day": ds[-1], "v": round(v, 4),
               "c1": _r(ch(1)), "c5": _r(ch(5)), "c20": _r(ch(20)), "c60": _r(ch(60)),
               "ma20": _r(v / ma20 - 1), "ma60": _r(v / ma60 - 1), "pos52": round(pos52, 3), "trend": trend,
               "unit": "pt" if lvl else "", "link": link, "sectors": sens[:5], "spark": vs[-120:],
               "overnight": None if not ov else {"day": ov["day"], "chg": round(ov["chg"], 4)}}
        row["text"] = _global_text(row)
        rows.append(row)
    # 預估：用連動最強的幾個美國指標估計台股下一個交易日
    exp = None
    # 只用美股主要指數與台積電 ADR（同一個收盤日），避免用到還沒收盤的報價
    us_closed = "^GSPC" in overnight
    cands = [r for r in rows if us_closed and r["sym"] in ("^SOX", "^IXIC", "^GSPC", "^DJI", "TSM") and r["overnight"]
             and r["link"] and r["link"]["kind"] == "隔夜" and abs(r["link"]["corr"]) >= 0.2]
    if cands:
        best = max(cands, key=lambda r: abs(r["link"]["corr"]))
        exp = {"sym": best["sym"], "name": best["name"], "move": best["overnight"]["chg"],
               "exp": round(best["link"]["beta"] * best["overnight"]["chg"], 4), "corr": best["link"]["corr"],
               "day": best["overnight"]["day"]}
    summary = _global_summary(rows, exp, us_closed, days[last])
    sec_exp = [{"ind": s["ind"], "exp": s["exp"]["exp"], "name": s["exp"]["name"], "move": s["exp"]["move"]}
               for s in sectors if s.get("exp")]
    sec_exp.sort(key=lambda x: -x["exp"])
    return {"day": days[last], "at": graw.get("_at"), "rows": rows, "exp": exp, "us_closed": us_closed,
            "summary": summary, "sector_exp": sec_exp}


def _global_text(r):
    lvl = r["unit"] == "pt"
    parts = []
    if r["c5"] is not None:
        if lvl:
            parts.append("近一週%s %.2f" % ("上升" if r["c5"] >= 0 else "下降", abs(r["c5"])))
        else:
            parts.append("近一週%s %s" % (_ud(r["c5"]), _pct(r["c5"])))
    if r["c20"] is not None and not lvl:
        parts.append("近一個月%s %s" % (_ud(r["c20"]), _pct(r["c20"])))
    parts.append({"多頭": "站上月線與季線，趨勢向上", "空頭": "跌破月線與季線，趨勢向下",
                  "反彈中": "站回月線，短線反彈", "回檔中": "跌破月線，短線回檔"}[r["trend"]])
    if r["pos52"] >= 0.9:
        parts.append("接近一年高點")
    elif r["pos52"] <= 0.1:
        parts.append("接近一年低點")
    L = r["link"]
    if L and abs(L["corr"]) >= 0.2:
        strength = "很高" if abs(L["corr"]) >= 0.5 else "中等" if abs(L["corr"]) >= 0.35 else "有一些"
        if lvl:
            parts.append("和台股連動%s（它上升時台股%s容易跌）" % (strength, "比較" if L["beta"] < 0 else "比較不"))
        elif L["kind"] == "隔夜":
            parts.append("和台股連動%s：它漲 1%%，台股隔天平均%s %.2f%%" % (strength, "漲" if L["beta"] >= 0 else "跌", abs(L["beta"])))
        else:
            parts.append("和台股同一天的連動%s" % strength)
    elif L:
        parts.append("和台股的連動不明顯")
    return "，".join(parts) + "。"


def _nm(n):
    """名稱結尾是英數字時補空白，例如「標普 500 漲」。"""
    return n + " " if n and (n[-1].isascii() and n[-1].isalnum()) else n


def _global_summary(rows, exp, us_closed, day):
    get = {r["sym"]: r for r in rows}
    lines = []
    us = [get[s] for s in ("^DJI", "^GSPC", "^IXIC", "^SOX") if s in get]
    if us:
        when = "昨晚美股" if us_closed else "前一晚美股（已反映在今天的台股）"
        lines.append("%s：%s。" % (when, "、".join("%s%s %s" % (_nm(r["name"]), _ud(r["c1"] or 0), _pct(r["c1"] or 0))
                                                   for r in us if r["c1"] is not None)))
    t = [get[s] for s in ("TSM", "NVDA") if s in get]
    if t:
        lines.append("、".join("%s%s %s" % (_nm(r["name"]), _ud(r["c1"] or 0), _pct(r["c1"] or 0)) for r in t if r["c1"] is not None) + "。")
    asia = [get[s] for s in ASIA if s in get]
    if asia:
        lines.append("亞洲股市：%s。" % "、".join("%s%s %s" % (r["name"], _ud(r["c1"] or 0), _pct(r["c1"] or 0))
                                              for r in asia if r["c1"] is not None))
    other = []
    if "^VIX" in get and get["^VIX"]["c1"] is not None:
        v = get["^VIX"]
        other.append("恐慌指數 %.1f（%s）" % (v["v"], "偏高，市場緊張" if v["v"] >= 22 else "偏低，市場平靜" if v["v"] <= 16 else "普通"))
    if "TWD=X" in get and get["TWD=X"]["c5"] is not None:
        v = get["TWD=X"]
        other.append("新台幣近一週%s %s" % ("貶值" if v["c5"] >= 0 else "升值", _pct(v["c5"])))
    if "^TNX" in get and get["^TNX"]["c5"] is not None:
        v = get["^TNX"]
        other.append("美債利率 %.2f%%（近一週%s %.2f 個百分點）" % (v["v"], "上升" if v["c5"] >= 0 else "下降", abs(v["c5"])))
    if other:
        lines.append("、".join(other) + "。")
    if exp:
        lines.append("依過去的連動估算，%s的變化對台股下一個交易日的影響約 %s%s（只是參考，開盤還會受其他消息影響）。" % (
            exp["name"], "+" if exp["exp"] >= 0 else "−", _pct(exp["exp"], 2)))
    elif not us_closed:
        lines.append("今晚美股收盤後（早上 7:35 左右）會再更新，屆時提供對台股下一個交易日的影響估算。")
    return lines


# ====================================================================== 消息影響

def _news_impact(D, rets, tx_ret, members):
    """新聞發布後，個股相對大盤的實際表現（用已經揭曉的日子統計）。"""
    days, T, last = D.days, D.T, D.T - 1
    items = getattr(D, "news_items", None) or []
    mops = getattr(D, "mops_items", None) or []
    ind_of = {}
    for ind, cs in members.items():
        for c in cs:
            ind_of[c] = ind
    events = []
    seen = set()

    def add(code, d, hhmm, sent, src):
        if code not in rets:
            return
        # 開盤前（9:00 前）發布的消息從當天算反應；盤中、盤後發布的從下一個交易日算，
        # 避免把「股價先動、新聞才寫」的情況誤算成消息的影響
        t0 = bisect.bisect_left(days, d)
        if t0 < len(days) and days[t0] == d and hhmm >= 900:
            t0 += 1
        if t0 >= T:
            return
        key = (code, t0, round(sent, 2))
        if key in seen:
            return
        seen.add(key)
        r = rets[code]

        def ex(n):
            if t0 + n - 1 > last:
                return None
            s = 0.0
            for t in range(t0, t0 + n):
                if isnan(r[t]) or isnan(tx_ret[t]):
                    return None
                s += r[t] - tx_ret[t]
            return s
        events.append({"c": code, "t0": t0, "sent": sent, "e1": ex(1), "e5": ex(5), "ind": ind_of.get(code), "src": src})

    import datetime as _dt
    for it in items:
        at = it.get("at") or 0
        if not at:
            continue
        tw = _dt.datetime.utcfromtimestamp(at + 8 * 3600)
        for c in it.get("codes") or []:
            add(c, tw.strftime("%Y%m%d"), tw.hour * 100 + tw.minute, it.get("sent", 0), "新聞")
    for m in mops:
        if m.get("d"):
            add(m["c"], m["d"], 1400, m.get("sent", 0), "公告")

    def stat(evs, key):
        xs = [e[key] for e in evs if e[key] is not None]
        if not xs:
            return {"n": 0}
        return {"n": len(xs), "avg": round(sum(xs) / len(xs), 5), "beat": round(sum(1 for x in xs if x > 0) / len(xs), 4)}
    groups = {"利多": [e for e in events if e["sent"] > 0.05], "利空": [e for e in events if e["sent"] < -0.05],
              "中性": [e for e in events if -0.05 <= e["sent"] <= 0.05]}
    out = {"events": len(events), "first": days[min(e["t0"] for e in events)] if events else None,
           "groups": {k: {"d1": stat(v, "e1"), "d5": stat(v, "e5")} for k, v in groups.items()}}
    by_ind = {}
    for e in events:
        if e["ind"] and e["sent"] != 0 and e["e1"] is not None:
            by_ind.setdefault(e["ind"], []).append(e)
    rows = []
    for ind, evs in by_ind.items():
        pos = [e["e1"] for e in evs if e["sent"] > 0.05]
        neg = [e["e1"] for e in evs if e["sent"] < -0.05]
        if len(pos) + len(neg) >= 8:
            rows.append({"ind": ind, "pos_n": len(pos), "pos": round(sum(pos) / len(pos), 5) if pos else None,
                         "neg_n": len(neg), "neg": round(sum(neg) / len(neg), 5) if neg else None})
    rows.sort(key=lambda x: -(x["pos_n"] + x["neg_n"]))
    out["by_ind"] = rows[:15]
    return out


# ====================================================================== 盤後綜合報告

def _report(D, stocks, by_code, sectors, glob_out, impact, res, dt, rets):
    T, days, last = D.T, D.days, D.T - 1
    d = days[last]
    mkt = res["market"]
    tx = D.mkt["taiex"]
    blocks = []
    # ---- 大盤
    lines = []
    if not isnan(tx[last]) and not isnan(tx[last - 1]):
        pts = tx[last] - tx[last - 1]
        lines.append("加權指數收 %s 點，%s %s 點（%s%s）。" % (format(round(tx[last], 2), ",.2f"), "上漲" if pts >= 0 else "下跌",
                                                     format(abs(round(pts, 2)), ",.2f"), "+" if pts >= 0 else "−", _pct(pts / tx[last - 1], 2)))
    vals = [sum((D.raw[c]["val"][t] or 0) for c in D.codes if not isnan(D.raw[c]["val"][t])) for t in range(max(0, last - 20), last + 1)]
    if vals and len(vals) > 5:
        v0, v20 = vals[-1], sum(vals[:-1]) / len(vals[:-1])
        lines.append("上市櫃總成交金額約 %s元，比最近 20 天平均%s %s。" % (_yi(v0), "多" if v0 >= v20 else "少", _pct(v0 / v20 - 1, 0)))
    up = sum(1 for r in stocks if not r["etf"] and r["chg"] > 0.0005)
    dn = sum(1 for r in stocks if not r["etf"] and r["chg"] < -0.0005)
    lu = sum(1 for r in stocks if not r["etf"] and r["chg"] >= 0.095)
    ld = sum(1 for r in stocks if not r["etf"] and r["chg"] <= -0.095)
    lines.append("上市櫃股票 %d 家上漲、%d 家下跌；漲停 %d 家、跌停 %d 家。" % (up, dn, lu, ld))
    blocks.append({"h": "大盤", "lines": lines})
    # ---- 法人
    lines = []
    for key, who in (("fi", "外資"), ("it", "投信"), ("dl", "自營商")):
        s = 0.0
        for c in D.codes:
            f, px = D.raw[c][key][last], D.raw[c]["c"][last]
            if not isnan(f) and not isnan(px):
                s += f * px
        lines.append("%s%s約 %s" % (who, "買超" if s >= 0 else "賣超", _yi(s)))
    lines = ["、".join(lines) + "（依個股買賣張數估算）。"]
    if mkt.get("foi") is not None:
        lines.append("外資在台指期上押%s %s 口%s。" % ("漲" if mkt["foi"] >= 0 else "跌", format(int(abs(mkt["foi"])), ","),
                                             "，近 5 天加碼押%s %s 口" % ("漲" if (mkt.get("foi5") or 0) >= 0 else "跌", format(int(abs(mkt.get("foi5") or 0)), ","))
                                             if mkt.get("foi5") is not None else ""))
    fi_top = sorted(((D.raw[c]["fi"][last] * D.raw[c]["c"][last], c) for c in D.codes
                     if not isnan(D.raw[c]["fi"][last]) and not isnan(D.raw[c]["c"][last])), reverse=True)
    it_top = sorted(((D.raw[c]["it"][last] * D.raw[c]["c"][last], c) for c in D.codes
                     if not isnan(D.raw[c]["it"][last]) and not isnan(D.raw[c]["c"][last])), reverse=True)
    items = []
    if fi_top:
        items.append({"t": "外資買最多", "list": [{"c": c, "n": D.names.get(c, c), "v": round(v / 1e8, 2)} for v, c in fi_top[:5] if v > 0]})
        items.append({"t": "外資賣最多", "list": [{"c": c, "n": D.names.get(c, c), "v": round(v / 1e8, 2)} for v, c in fi_top[-5:][::-1] if v < 0]})
    if it_top:
        items.append({"t": "投信買最多", "list": [{"c": c, "n": D.names.get(c, c), "v": round(v / 1e8, 2)} for v, c in it_top[:5] if v > 0]})
    blocks.append({"h": "法人動向", "lines": lines, "tops": items})
    # ---- 類股
    big = [s for s in sectors if s["n"] >= 6 and s["chg1"] is not None]
    lines = []
    if big:
        st = sorted(big, key=lambda s: -s["chg1"])
        lines.append("最強：%s。" % "、".join("%s %s%s" % (s["ind"], "+" if s["chg1"] >= 0 else "−", _pct(s["chg1"], 2)) for s in st[:3]))
        lines.append("最弱：%s。" % "、".join("%s %s%s" % (s["ind"], "+" if s["chg1"] >= 0 else "−", _pct(s["chg1"], 2)) for s in st[-3:][::-1]))
        flow = sorted([s for s in big if s["share"] and s["share20"] and s["share20"] >= 0.01], key=lambda s: -(s["share"] / s["share20"]))
        if flow:
            lines.append("資金明顯流入：%s。" % "、".join("%s（成交占比 %s，平常 %s）" % (s["ind"], _pct(s["share"]), _pct(s["share20"]))
                                                   for s in flow[:3] if s["share"] / s["share20"] > 1.1) if flow[0]["share"] / flow[0]["share20"] > 1.1 else "各類股資金分布和平常差不多。")
        fl = sorted(big, key=lambda s: -s["fi1"])
        lines.append("外資今天加碼最多：%s；賣最多：%s。" % ("、".join("%s %s" % (s["ind"], _yi(s["fi1"] * 1e8)) for s in fl[:2] if s["fi1"] > 0) or "無",
                                             "、".join("%s %s" % (s["ind"], _yi(s["fi1"] * 1e8)) for s in fl[-2:][::-1] if s["fi1"] < 0) or "無"))
    blocks.append({"h": "類股", "lines": lines})
    # ---- 個股焦點
    liq = [r for r in stocks if not r["etf"] and r.get("val") and r["val"] >= 1 and r["px"]]
    items = []
    today_val = sorted(((D.raw[r["c"]]["val"][last] or 0, r) for r in stocks if not isnan(D.raw[r["c"]]["val"][last])), key=lambda x: -x[0])
    items.append({"t": "成交金額最大", "list": [{"c": r["c"], "n": r["n"], "chg": r["chg"], "v": round(v / 1e8, 1)} for v, r in today_val[:5]]})
    items.append({"t": "漲最多（成交 1 億以上）", "list": [{"c": r["c"], "n": r["n"], "chg": r["chg"]} for r in sorted(liq, key=lambda r: -r["chg"])[:5]]})
    items.append({"t": "跌最多（成交 1 億以上）", "list": [{"c": r["c"], "n": r["n"], "chg": r["chg"]} for r in sorted(liq, key=lambda r: r["chg"])[:5]]})
    blocks.append({"h": "個股焦點", "tops": items})
    # ---- 消息
    lines, news_list = [], []
    nm = mkt.get("news")
    if nm:
        mood = "偏樂觀" if nm["mood"] > 0.05 else "偏悲觀" if nm["mood"] < -0.05 else "好壞參半"
        lines.append("近兩天 %d 則財經新聞，整體%s（好消息 %d 則、壞消息 %d 則）。" % (nm["n"], mood, nm["pos"], nm["neg"]))
        lines.append("今天有 %d 檔注意股、%d 檔處置股。" % (nm["warn_n"], nm["disp_n"]))
        items = [it for it in (getattr(D, "news_items", None) or []) if it.get("d", "") >= days[max(0, last - 1)] and it.get("codes")]
        items.sort(key=lambda it: (-abs(it.get("sent", 0)), -(it.get("at") or 0)))
        for it in items[:6]:
            news_list.append({"t": it["t"], "u": it.get("url"), "s": it.get("sent", 0), "src": it.get("src"),
                              "codes": [{"c": c, "n": D.names.get(c, c)} for c in (it.get("codes") or [])[:3]]})
    blocks.append({"h": "消息面", "lines": lines, "news": news_list})
    # ---- 國際
    blocks.append({"h": "國際股市", "lines": glob_out["summary"]})
    # ---- 展望
    lines = []
    HZW = {"short": "1 週", "mid": "1 個月", "long": "3 個月"}
    rel_low = []
    parts = []
    for hn in ("short", "mid", "long"):
        h = mkt["horizons"][hn]
        parts.append("未來 %s %.0f 分（%s）" % (HZW[hn], h["score"], h["label"]))
        if (h.get("rel") or 1) < 0.4:
            rel_low.append(HZW[hn])
    lines.append("大盤：" + "、".join(parts) + "。")
    if rel_low:
        lines.append("提醒：%s的判斷最近不太準，分數已調得保守，請參考「實測對答案」。" % "、".join(rel_low))
    ss = [s for s in sectors if s["n"] >= 6 and s["s"][1] is not None]
    if ss:
        lines.append("未來 1 個月較看好的類股：%s；較不看好：%s。" % ("、".join("%s（%.0f 分）" % (s["ind"], s["s"][1]) for s in ss[:3]),
                                                       "、".join("%s（%.0f 分）" % (s["ind"], s["s"][1]) for s in ss[-3:][::-1])))
    if dt:
        lines.append("當沖：明天先買後賣推薦 %d 檔、先賣後買推薦 %d 檔。" % (dt.get("long_ok", 0), dt.get("short_ok", 0)))
    blocks.append({"h": "接下來怎麼看", "lines": lines})
    pts = tx[last] - tx[last - 1] if not isnan(tx[last]) and not isnan(tx[last - 1]) else 0
    title = "%d/%d 台股%s %s 點" % (int(d[4:6]), int(d[6:8]), "上漲" if pts >= 0 else "下跌", format(abs(round(pts)), ","))
    return {"day": d, "title": title, "blocks": blocks}
