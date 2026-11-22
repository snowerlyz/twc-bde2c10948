# -*- coding: utf-8 -*-
"""研究：歷史上「急跌」之後怎麼走、各種應對方式的結果（9 個市場，1927 年起）。

資料：tools/crash_fetch.py 抓的 Yahoo 日線（加權指數、S&P 500、那斯達克、日經、恆生、韓國綜合、
費城半導體、德國 DAX、英國富時），放在同一個資料夾。結果寫到 app/crash_study.json，網頁「大跌之後」卡片用。
執行：python tools/crash_study.py 資料夾

事前定好的定義（看結果前決定，不再調整）：
- 急跌 A：5 個交易日跌 10% 以上；急跌 B：20 個交易日跌 20% 以上。同一市場 60 個交易日內只算第一次。
- 不同市場 45 天內同時發生算同一波（例如 2008、2020），統計時每一波只算一次（各市場平均），避免重複計算。
- 分組：急跌開始前（觸發日往前 20 天）的一年漲幅 ≥30%（大漲之後的急跌）或 <30%。
- 應對（從觸發日收盤起算一年 250 個交易日；訊號收盤判斷、隔天收盤執行；每次買賣成本 0.15%）：
  抱住；全部賣出、站回 200 日均線再買回；賣一半、站回 20 日均線再買回。
  新資金：觸發日收盤一次買進；分 3 批（觸發日、20 天後、40 天後）。
- 全期間的持股規則：一直抱住；收盤在 200 日均線之上才持有；依波動調整持股（長期平均波動 ÷ 近 20 天波動，最多 100%）。
- 指數不含股利、現金不計利息（兩者大致抵銷，對「抱住」略不利）。
"""
import datetime as dt
import json
import math
import os
import sys

import numpy as np

MK = ["TWII", "GSPC", "IXIC", "N225", "HSI", "KS11", "SOX", "GDAXI", "FTSE"]
MK_NAME = {"TWII": "台灣加權", "GSPC": "美國 S&P 500", "IXIC": "那斯達克", "N225": "日經 225", "HSI": "香港恆生",
           "KS11": "韓國綜合", "SOX": "費城半導體", "GDAXI": "德國 DAX", "FTSE": "英國富時 100"}
COST = 0.0015
H = 250
OUT = os.path.join(os.path.dirname(__file__), "..", "app", "crash_study.json")


def load(src, name):
    d = json.load(open(os.path.join(src, name + ".json")))
    k = sorted(d)
    c = np.array([d[x][3] or 0 for x in k], float)
    ok = c > 0
    return [x for x, o in zip(k, ok) if o], c[ok]


def ma(c, w):
    cs = np.r_[0, np.cumsum(c)]
    out = np.full(len(c), np.nan)
    out[w - 1:] = (cs[w:] - cs[:-w]) / w
    return out


def events(c, kind, gap=60):
    n = len(c)
    t = np.zeros(n, bool)
    if kind == "A":
        t[5:] = c[5:] / c[:-5] - 1 <= -0.10
    else:
        t[20:] = c[20:] / c[:-20] - 1 <= -0.20
    ev, last = [], -10 ** 9
    for i in np.where(t)[0]:
        if i - last > gap:
            ev.append(int(i))
        last = i
    return ev


def path(c, m20, m200, i, mode):
    """持有 1 單位的人從觸發日收盤起一年的結果：(報酬, 期間最大回落)。"""
    n = len(c)
    end = min(n - 1, i + H)
    pos, v, peak, mdd, sold = 1.0, 1.0, 1.0, 0.0, False
    for j in range(i + 1, end + 1):
        v *= 1 + pos * (c[j] / c[j - 1] - 1)
        new = pos
        if mode != "hold":
            if not sold:
                new, sold = (0.5 if mode == "half20" else 0.0), True
            ref = m20 if mode == "half20" else m200
            if pos < 1 and c[j] > ref[j]:
                new = 1.0
        if new != pos:
            v *= 1 - COST * abs(new - pos)
            pos = new
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return v - 1, mdd


def study(src):
    rows = {"A": [], "B": []}
    for mk in MK:
        k, c = load(src, mk)
        n = len(c)
        m20, m200 = ma(c, 20), ma(c, 200)
        for kind in rows:
            for i in events(c, kind):
                p = i - 20
                if p < 250 or i + H >= n or np.isnan(m200[p]):
                    continue
                end = i + H
                rows[kind].append({
                    "mk": mk, "d": k[i], "g": c[p] / c[p - 250] - 1,
                    "f20": c[i + 20] / c[i] - 1, "f60": c[i + 60] / c[i] - 1, "f250": c[end] / c[i] - 1,
                    "mn": c[i + 1:end + 1].min() / c[i] - 1,
                    "hold": path(c, m20, m200, i, "hold"), "s200": path(c, m20, m200, i, "sell200"),
                    "half": path(c, m20, m200, i, "half20"),
                    "n3": float(np.mean([c[end] / c[j] - 1 for j in (i, i + 20, i + 40)])),
                })
    return rows


def cluster(rows):
    D = lambda s: dt.date(int(s[:4]), int(s[4:6]), int(s[6:]))
    rows = sorted(rows, key=lambda r: r["d"])
    cl = []
    for r in rows:
        if cl and (D(r["d"]) - D(cl[-1][-1]["d"])).days <= 45:
            cl[-1].append(r)
        else:
            cl.append([r])
    return cl


def summarize(cl):
    if not cl:
        return None
    A = lambda f: np.array([np.mean([f(x) for x in c]) for c in cl])
    f250, mn = A(lambda x: x["f250"]), A(lambda x: x["mn"])
    hold, s200, half = A(lambda x: x["hold"][0]), A(lambda x: x["s200"][0]), A(lambda x: x["half"][0])
    r4 = lambda v: round(float(v), 4)
    return {
        "n": len(cl), "mk_n": sum(len(c) for c in cl),
        "f20": r4(A(lambda x: x["f20"]).mean()), "f60": r4(A(lambda x: x["f60"]).mean()),
        "f250": r4(f250.mean()), "f250_med": r4(np.median(f250)), "up250": r4((f250 > 0).mean()),
        "worse10": r4((mn <= -0.10).mean()), "worse20": r4((mn <= -0.20).mean()), "mn_med": r4(np.median(mn)),
        "hold": r4(hold.mean()), "hold_mdd": r4(np.median(A(lambda x: x["hold"][1]))),
        "s200": r4(s200.mean()), "s200_mdd": r4(np.median(A(lambda x: x["s200"][1]))),
        "half": r4(half.mean()), "half_mdd": r4(np.median(A(lambda x: x["half"][1]))),
        "hold_win_s200": r4((hold > s200).mean()), "hold_win_half": r4((hold > half).mean()),
        "now": r4(f250.mean()), "n3": r4(A(lambda x: x["n3"]).mean()), "n3_win": r4((A(lambda x: x["n3"]) > f250).mean()),
    }


def policies(src):
    res = {}
    for mk in MK:
        k, c = load(src, mk)
        n = len(c)
        r = np.r_[0, c[1:] / c[:-1] - 1]
        lr = np.r_[0, np.diff(np.log(c))]
        m200 = ma(c, 200)
        v20 = np.full(n, np.nan)
        for i in range(250, n):
            v20[i] = lr[i - 19:i + 1].std() * math.sqrt(250)
        cnt = np.cumsum(~np.isnan(v20))
        lv = np.where(cnt > 250, np.cumsum(np.nan_to_num(v20)) / np.maximum(cnt, 1), np.nan)
        start = 600
        for kind in ("hold", "ma200", "vol"):
            if kind == "hold":
                pos = np.ones(n)
            elif kind == "ma200":
                pos = np.where(c > m200, 1.0, 0.0)
            else:
                with np.errstate(divide="ignore", invalid="ignore"):
                    pos = np.clip(lv / v20, 0, 1)
            pos = np.nan_to_num(pos, nan=1.0)
            p = np.r_[1.0, pos[:-1]]
            ret = (p * r - np.r_[0, np.abs(np.diff(p))] * COST)[start:]
            eq = np.cumprod(1 + ret)
            yrs = len(ret) / 250.0
            res.setdefault(kind, []).append((eq[-1] ** (1 / yrs) - 1, ret.std() * math.sqrt(250),
                                             (eq / np.maximum.accumulate(eq) - 1).min()))
    return {k: {"cagr": round(float(np.mean([x[0] for x in v])), 4), "vol": round(float(np.mean([x[1] for x in v])), 4),
                "mdd": round(float(np.mean([x[2] for x in v])), 4)} for k, v in res.items()}


def tails(src):
    """急跌後（5 天跌 10% 以上的日子）下一週：現行範圍 vs 用近 5 天＋近 20 天波動的範圍，實際落在範圍外的比例。"""
    out = {"old": [0, 0, 0, 0], "new": [0, 0, 0, 0]}
    h = 5
    for mk in [m for m in MK if m != "SOX"]:
        k, c = load(src, mk)
        n = len(c)
        r = np.r_[0, np.diff(np.log(c))]

        def rstd(w):
            o = np.full(n, np.nan)
            for i in range(w - 1, n):
                o[i] = r[i - w + 1:i + 1].std()
            return o
        v20, v250 = rstd(20), rstd(250)
        v5 = np.sqrt(np.convolve(r * r, np.ones(5) / 5)[:n])
        s = np.sqrt(0.5 * v20 ** 2 + 0.5 * v250 ** 2)
        s[:250] = np.nan
        z = np.full(n, np.nan)
        for j in range(n - h):
            if s[j] == s[j]:
                z[j] = math.log(c[j + h] / c[j]) / (s[j] * math.sqrt(h))
        zs = None
        for t in range(1500, n - h):
            if s[t] != s[t] or not c[t] / c[t - 5] - 1 <= -0.10:
                continue
            zz = z[:t + 1 - h]
            zs = np.sort(zz[~np.isnan(zz)])
            rr = math.log(c[t + h] / c[t])
            for lab, sg in (("old", s[t]), ("new", math.sqrt(0.5 * v5[t] ** 2 + 0.5 * v20[t] ** 2))):
                d = sg * math.sqrt(h)
                o = out[lab]
                o[0] += 1
                o[1] += np.quantile(zs, .1) * d <= rr <= np.quantile(zs, .9) * d
                o[2] += rr < np.quantile(zs, .01) * d
                o[3] += rr > np.quantile(zs, .95) * d
    return {lab: {"n": o[0], "cov80": round(o[1] / o[0], 3), "below1": round(o[2] / o[0], 3), "above95": round(o[3] / o[0], 3)}
            for lab, o in out.items()}


def main(src):
    rows = study(src)
    res = {"at": dt.date.today().isoformat(), "markets": [MK_NAME[m] for m in MK], "since": "1927", "groups": {}, "episodes": {}}
    for kind in ("A", "B"):
        g = {"all": summarize(cluster(rows[kind])),
             "hot": summarize(cluster([r for r in rows[kind] if r["g"] >= 0.30])),
             "cold": summarize(cluster([r for r in rows[kind] if r["g"] < 0.30]))}
        res["groups"][kind] = g
        eps = []
        for c in cluster([r for r in rows[kind] if r["g"] >= 0.30]):
            eps.append({"d": c[0]["d"], "mk": [MK_NAME[x["mk"]] for x in c], "f250": round(float(np.mean([x["f250"] for x in c])), 4),
                        "mn": round(float(np.mean([x["mn"] for x in c])), 4), "g": round(float(np.mean([x["g"] for x in c])), 4)})
        res["episodes"][kind] = eps
    res["policy"] = policies(src)
    res["tail5"] = tails(src)
    json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1)[:4000])


if __name__ == "__main__":
    main(sys.argv[1])
