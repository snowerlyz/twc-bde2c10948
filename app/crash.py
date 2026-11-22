# -*- coding: utf-8 -*-
"""大跌之後：加權指數剛急跌時，歷史上同級的急跌之後怎麼走、各種應對方式的結果。

1. 狀態：最近 60 個交易日內有沒有「急跌」——A：5 個交易日跌 10% 以上；B：20 個交易日跌 20% 以上（B 比 A 嚴重）。
   定義事前決定（見 tools/crash_study.py），每天依加權指數長期收盤判斷。
2. 歷史：9 個市場（1927 年起）的同級急跌統計放在 app/crash_study.json（研究程式產生，不每天重算）；
   依「急跌前一年漲幅」分組（≥30% 大漲後的急跌，歷史結果明顯較差）。台股自己的急跌事件每天重算。
3. 應對：照研究結果事先寫好的規則與數字（抱住、賣出等站回 200 日均線、賣一半、新資金一次或分批），
   以及「依 200 日均線調整持股」的長期回測。不預測這次會怎麼走。
"""
import json
import math
import os

from util import log

GAP = 60
STUDY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crash_study.json")


def _trig(c, i, kind):
    if kind == "A":
        return i >= 5 and c[i] / c[i - 5] - 1 <= -0.10
    return i >= 20 and c[i] / c[i - 20] - 1 <= -0.20


def _first_of_cluster(c, i, kind):
    """往回找同一波（相隔 60 個交易日以內）第一次觸發的位置。"""
    j = i
    k = i - 1
    while k >= 0 and j - k <= GAP:
        if _trig(c, k, kind):
            j = k
        k -= 1
    return j


def _tw_events(ds, c, kind):
    out, last = [], -10 ** 9
    n = len(c)
    for i in range(n):
        if not _trig(c, i, kind):
            continue
        if i - last > GAP:
            f = lambda h: round(c[i + h] / c[i] - 1, 4) if i + h < n else None
            back = next((j - i for j in range(i + 1, n) if c[j] >= c[i]), None)
            out.append({"d": ds[i], "r": round(c[i] / c[i - (5 if kind == "A" else 20)] - 1, 4), "f20": f(20), "f60": f(60),
                        "f250": f(250), "mn": round(min(c[i + 1:i + 251]) / c[i] - 1, 4) if i + 1 < n else None,
                        "done": i + 250 < n, "back": back})
        last = i
    return out


def build(D):
    from risk import _series
    s = _series(D)
    ds = sorted(s)
    c = [float(s[d]) for d in ds]
    n = len(c)
    if n < 300:
        return None
    last = n - 1
    lr = [0.0] + [math.log(c[i] / c[i - 1]) for i in range(1, n)]

    def sd(w):
        x = lr[-w:]
        m = sum(x) / w
        return math.sqrt(max(0.0, sum((v - m) ** 2 for v in x) / w)) * math.sqrt(250)
    v5 = math.sqrt(sum(v * v for v in lr[-5:]) / 5 * 250)
    v20, v250 = sd(20), sd(250)
    w = c[max(0, last - 250):]
    pk = max(range(len(w)), key=lambda k: w[k]) + max(0, last - 250)
    ma200 = sum(c[-200:]) / 200
    st = {"day": ds[last], "close": round(c[last], 2), "r5": round(c[last] / c[last - 5] - 1, 4),
          "r20": round(c[last] / c[last - 20] - 1, 4), "peak": round(c[pk], 2), "peak_day": ds[pk],
          "dd": round(c[last] / c[pk] - 1, 4), "ma200": round(ma200, 2), "above200": c[last] > ma200,
          "v5": round(v5, 4), "v20": round(v20, 4), "v250": round(v250, 4)}
    # 最近 60 個交易日內的急跌（先看較嚴重的 B）
    trig = None
    for kind in ("B", "A"):
        hit = [i for i in range(max(0, n - GAP), n) if _trig(c, i, kind)]
        if hit:
            i0 = _first_of_cluster(c, hit[0], kind)
            p = i0 - 20
            g = c[p] / c[p - 250] - 1 if p >= 250 else None
            trig = {"kind": kind, "first": ds[i0], "first_close": round(c[i0], 2), "last_hit": ds[hit[-1]],
                    "days_since": last - hit[-1], "since_first": round(c[last] / c[i0] - 1, 4),
                    "prior_gain": round(g, 4) if g is not None else None, "hot": g is not None and g >= 0.30}
            break
    study = {}
    try:
        study = json.load(open(STUDY, encoding="utf-8"))
    except Exception as e:
        log("大跌之後：讀不到研究結果 %s" % e)
    out = {"state": st, "active": trig is not None, "trig": trig,
           "tw": {"A": _tw_events(ds, c, "A"), "B": _tw_events(ds, c, "B")}, "tw_since": ds[0][:4]}
    if study:
        out["study"] = {"markets": study.get("markets"), "since": study.get("since"), "policy": study.get("policy"),
                        "tail5": study.get("tail5")}
        kind = trig["kind"] if trig else "B"
        G = (study.get("groups") or {}).get(kind) or {}
        out["study"]["kind"] = kind
        out["study"]["all"] = G.get("all")
        out["study"]["grp"] = G.get("hot" if (trig and trig["hot"]) else "cold")
        out["study"]["other"] = G.get("cold" if (trig and trig["hot"]) else "hot")
        out["study"]["episodes"] = (study.get("episodes") or {}).get(kind)
    out["rules"] = _rules(out)
    return out


def _pc(x, sign=False):
    return ("%+.0f%%" if sign else "%.0f%%") % (x * 100)


def _rules(o):
    """事先定好的應對說明（數字取自研究結果）。"""
    S, st, tr = o.get("study") or {}, o["state"], o.get("trig")
    a, g, pol = S.get("all") or {}, S.get("grp") or {}, S.get("policy") or {}
    rules = []
    if not (a and g):
        return rules
    rules.append({"t": "不要在急跌後一次全部賣光",
                  "d": "同級急跌後，「抱住」一年平均 %s，「全部賣出、等站回 200 日均線再買回」只有 %s；%s 的波段抱住比較好。"
                       "急跌後常有很大的反彈，賣掉之後通常買不回來。" % (_pc(g["hold"], True), _pc(g["s200"], True), _pc(g["hold_win_s200"]))})
    rules.append({"t": "持股多少比賣不賣更重要",
                  "d": "但這類急跌有 %s 之後又再跌 10%% 以上、%s 再跌 20%% 以上（中間值 %s）。手上的持股，要是「再跌 2～3 成也不用被迫賣」的量；"
                       "不要用融資或借錢，斷頭會逼你賣在最低點。" % (_pc(g["worse10"]), _pc(g["worse20"]), _pc(g["mn_med"], True))})
    if pol.get("hold") and pol.get("ma200"):
        rules.append({"t": "想降低風險，用事先定好的規則減碼",
                      "d": "例如「收盤跌破 200 日均線就減碼、站回再加」：9 個市場長期回測，最大回落平均從 %s 降到 %s，代價是年報酬少約 %.1f 個百分點。"
                           "現在加權指數在 200 日均線（%s）%s %.1f%%。要用就長期照做，不要只在跌完才用。"
                           % (_pc(-pol["hold"]["mdd"]), _pc(-pol["ma200"]["mdd"]), (pol["hold"]["cagr"] - pol["ma200"]["cagr"]) * 100,
                              format(round(st["ma200"]), ","), "之上" if st["above200"] else "之下",
                              abs(st["close"] / st["ma200"] - 1) * 100)})
    rules.append({"t": "新資金：一次買或分批",
                  "d": "急跌當天一次買進，一年後平均 %s；分 3 批（當天、約 1 個月後、2 個月後）平均 %s，但有 %s 的波段分批反而比較好。"
                       "平均來說一次買較好，分批是用一點報酬換「不會一進場就套最深」。" % (_pc(g["now"], True), _pc(g["n3"], True), _pc(g["n3_win"]))})
    t5 = (S.get("tail5") or {}).get("old") or {}
    rules.append({"t": "短線、當沖：接下來一週震盪特別大",
                  "d": "急跌後的下一週，大盤上下震盪常比平常大很多：過去照一般波動算的 8 成範圍只涵蓋 %s（大反彈特別多）。"
                       "%s單筆金額縮小、停損放寬或少做。" % (_pc(t5.get("cov80") or 0.58),
                       "大盤預測的「短期」範圍已改用最近 5 天與 20 天的波動放寬（改了以後回測涵蓋 %s）。" % _pc((S.get("tail5") or {}).get("new", {}).get("cov80") or 0.8)
                       if st["r5"] <= -0.10 else "")})
    return rules
