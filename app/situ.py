# -*- coding: utf-8 -*-
"""國內外情勢（國際、國內、政治與經濟新聞）與「今日盤勢一句話」。

一、國內外情勢（說明背景，不直接拿來猜漲跌）
  國際：美股恐慌指數 VIX、美國 10 年債利率、美元指數、油價、費城半導體、
        地緣政治風險指數（Caldara & Iacoviello，依國際新聞報導計算）、美國經濟政策不確定指數（Baker, Bloom & Davis）。
  國內：國發會景氣燈號、新台幣匯率、台灣的地緣政治風險（同一個指數的台灣分項，每月）。
  新聞：鉅亨網「台灣政經」「國際政經」與頭條新聞，依關鍵字分成七個主題（兩岸與地緣政治、美中貿易與關稅、美國政治、
        利率與央行、國內景氣與出口、國內政治、匯率與資金），看最近 3 天的熱度（比前 15 天平均多或少）與偏多偏空。
  每一項的「偏有利／偏不利」方向是事前依常理與文獻決定（例如恐慌指數高、新台幣急貶、地緣政治風險升高視為不利），
  只描述目前的狀態。2005 年起的 walk-forward 檢驗（研究筆記 2026-11-05）：這些指標對之後一週到三個月加權指數的
  漲跌預測力都很弱（和「一律猜漲」差不多，也沒有讓大跌風險模型更準），所以只當背景說明，網頁照實寫。

二、今日盤勢一句話（開盤前）
  1. 隔夜美股：台積電 ADR 與費城半導體的平均漲跌 → 加權指數當天收紅的機率。
     2005 年起逐日 walk-forward 邏輯迴歸（每 20 天用已揭曉資料重估），實測猜對約 63%（一律猜漲約 54%），
     機率和實際上漲比例很接近。美股還沒收盤時（下午、晚上）不給方向。
  2. 大跌風險等級（app/risk.py）。
  3. 建議依「風險等級 × 收紅機率」事前定好的規則：風險高→持股減半、不追高（回測可降低最大回落，但多頭時少賺）；
     偏高→不加碼、設好停損；其餘依收紅機率提醒開盤追價或分批。
  每天開盤前的預測存進 db/brief_log.json，收盤後對答案（前瞻實測）。
"""
import bisect
import datetime as dt
import math
import os

from util import DB, log, now_tw, read_json, write_json

SITU_PATH = os.path.join(DB, "situ_src.json")
LOG_PATH = os.path.join(DB, "brief_log.json")
US = ("TSM", "^SOX")
START = "20050101"
REFIT = 20

TOPICS = [
    ("geo", "兩岸與地緣政治", ["共軍", "解放軍", "軍演", "台海", "兩岸", "封鎖", "武統", "中共", "對台", "國台辦", "飛彈", "戰爭",
                         "開戰", "衝突", "伊朗", "以色列", "烏克蘭", "俄羅斯", "北韓", "中東", "停火", "空襲", "制裁"]),
    ("trade", "美中貿易與關稅", ["關稅", "貿易戰", "貿易協議", "出口管制", "禁令", "實體清單", "晶片法", "232", "301", "對等",
                          "中美", "美中", "貿易談判"]),
    ("uspol", "美國政治", ["川普", "白宮", "民主黨", "共和黨", "美國國會", "期中選舉", "眾議院", "參議院", "范斯", "政府關門"]),
    ("rate", "利率與央行", ["聯準會", "Fed", "FOMC", "降息", "升息", "利率", "央行", "鮑爾", "通膨", "CPI", "PCE", "殖利率",
                        "縮表", "非農", "就業數據"]),
    ("econ", "國內景氣與出口", ["出口", "外銷訂單", "GDP", "經濟成長", "景氣", "燈號", "PMI", "失業率", "薪資", "消費", "內需",
                          "主計", "國發會", "經濟部", "工業生產"]),
    ("politics", "國內政治", ["立法院", "立委", "罷免", "總統府", "行政院", "賴清德", "總預算", "民進黨", "國民黨", "民眾黨", "閣揆",
                          "卓榮泰", "藍白", "朝野"]),
    ("fx", "匯率與資金", ["新台幣", "台幣", "匯率", "升值", "貶值", "外資", "熱錢", "資金外流", "匯出", "匯入"]),
]
MACRO_CATS = ("tw_macro", "wd_macro", "headline", "market")
DOMESTIC = {"econ", "politics", "fx"}     # 國內主題：只算台灣政經、台股新聞，或標題提到台灣的
TW_WORDS = ("台灣", "臺灣", "台股", "國內", "我國", "台幣", "主計", "國發會", "經濟部", "央行", "立法院", "行政院")


def isnan(x):
    return x is None or x != x


def _pct_rank(xs, v, min_n=50):
    xs = [x for x in xs if not isnan(x)]
    if len(xs) < min_n or isnan(v):
        return None
    return sum(1 for x in xs if x < v) / len(xs)


def _level(p):
    if p is None:
        return "資料不足"
    return "偏高" if p >= 0.8 else ("偏低" if p <= 0.2 else "普通")


def _gseries(D, sym):
    x = ((getattr(D, "glob_raw", {}) or {}).get(sym) or {}).get("s") or {}
    ks = sorted(k for k, v in x.items() if v)
    return ks, [x[k] for k in ks]


def _item(key, name, value, p, bad_high, note, src):
    """bad_high＝數值偏高對台股不利（事前依常理決定）。"""
    tone = "中性"
    if p is not None:
        if p >= 0.8:
            tone = "偏不利" if bad_high else "偏有利"
        elif p <= 0.2:
            tone = "偏有利" if bad_high else "偏不利"
    return {"k": key, "name": name, "v": value, "pct": None if p is None else round(p, 3), "lv": _level(p),
            "tone": tone, "note": note, "src": src}


# ---------------------------------------------------------------- 國際與國內指標
def _indicators(D, src):
    intl, dom = [], []
    # 恐慌指數：水準在近一年的位置
    ks, vs = _gseries(D, "^VIX")
    if len(vs) > 260:
        p = _pct_rank(vs[-251:-1], vs[-1])
        intl.append(_item("vix", "美股恐慌指數 VIX", "%.1f" % vs[-1], p, True,
                          "數字越高代表美股投資人越緊張；%s" % ("目前比近一年大多數時候高" if (p or 0) >= 0.8 else
                                                       "目前比近一年大多數時候低" if p is not None and p <= 0.2 else "目前在近一年的中間"), "Yahoo"))

    def chg_item(sym, key, name, n, bad_high, unit="pct", note=""):
        ks, vs = _gseries(D, sym)
        if len(vs) < 300:
            return None
        ch = [(vs[i] - vs[i - n]) if unit == "pt" else (vs[i] / vs[i - n] - 1) for i in range(n, len(vs))]
        p = _pct_rank(ch[-251:-1], ch[-1])
        val = ("%s %.2f 個百分點" % ("升" if ch[-1] >= 0 else "降", abs(ch[-1]))) if unit == "pt" else \
            ("%s %.1f%%" % ("漲" if ch[-1] >= 0 else "跌", abs(ch[-1]) * 100))
        return _item(key, name, "近一個月" + val, p, bad_high, note, "Yahoo")
    for args in (("^TNX", "tnx", "美國 10 年債利率", 20, True, "pt", "利率快速上升時，高本益比的科技股壓力較大"),
                 ("DX-Y.NYB", "dxy", "美元指數", 20, True, "pct", "美元走強時，資金傾向流出亞洲股市"),
                 ("CL=F", "oil", "國際油價", 20, True, "pct", "台灣是能源進口國，油價急漲推高成本與通膨"),
                 ("^SOX", "sox", "費城半導體指數", 20, False, "pct", "台股權值以半導體為主，連動很高")):
        it = chg_item(*args)
        if it:
            intl.append(it)
    # 新聞計算的指數：近 30 天平均在近三年的位置
    for key, name, bad, note, nm in (("gpr", "地緣政治風險（國際新聞）", True,
                                      "依國際主要報紙中戰爭、軍事威脅、恐怖攻擊等報導的比例計算", "Caldara & Iacoviello 地緣政治風險指數"),
                                     ("epu", "美國經濟政策不確定（新聞）", True,
                                      "依美國報紙中「經濟、政策、不確定」相關報導的比例計算（關稅、預算、利率政策等）",
                                      "Baker, Bloom & Davis 經濟政策不確定指數")):
        s = src.get(key) or {}
        ks = sorted(s)
        if len(ks) < 800:
            continue
        m30 = [sum(s[k] for k in ks[i - 29:i + 1]) / 30 for i in range(29, len(ks))]
        p = _pct_rank(m30[-781:-1], m30[-1])
        it = _item(key, name, "近 30 天平均 %.0f（截至 %s/%s）" % (m30[-1], ks[-1][4:6].lstrip("0"), ks[-1][6:].lstrip("0")),
                   p, bad, note + "；和近三年比" + _level(p), nm)
        if key == "gpr":
            intl.insert(1, it)
        else:
            intl.append(it)
    # 國內：景氣燈號
    nd = src.get("ndc") or {}
    if nd:
        k = max(nd)
        sc, light, lead = nd[k]
        prev = nd.get(sorted(nd)[-2]) if len(nd) > 1 else None
        color = {"紅": "紅燈（景氣過熱）", "黃紅": "黃紅燈（景氣活絡）", "綠": "綠燈（景氣穩定）", "黃藍": "黃藍燈（景氣欠佳）",
                 "藍": "藍燈（景氣低迷）"}.get(light, light)
        # 台股常見說法「藍燈買、紅燈賣」：分數高視為偏不利（事前決定；實測預測力很弱）
        tone = "偏不利" if sc >= 38 else ("偏有利" if sc <= 22 else "中性")
        dom.append({"k": "ndc", "name": "國發會景氣燈號", "v": "%s 年 %s 月 %s，%d 分%s" % (
            k[:4], k[4:].lstrip("0"), color, sc, "" if not prev else "（前一個月 %d 分）" % prev[0]),
            "pct": None, "lv": light, "tone": tone,
            "note": "景氣好代表企業獲利好，但股市通常提前反映；常見的說法是「藍燈買、紅燈賣」", "src": "國發會"})
    # 國內：新台幣（美元兌新台幣上升＝新台幣貶值）
    it = chg_item("TWD=X", "twd", "新台幣匯率", 20, True, "pct", "新台幣急貶常伴隨外資賣超")
    if it:
        it["v"] = it["v"].replace("近一個月漲 ", "近一個月貶值 ").replace("近一個月跌 ", "近一個月升值 ")
        dom.append(it)
    # 國內：台灣地緣政治風險（每月）
    tw = src.get("gpr_twn") or {}
    if len(tw) > 60:
        ks = sorted(tw)
        p = _pct_rank([tw[k] for k in ks[-37:-1]], tw[ks[-1]], 30)
        dom.append(_item("gpr_twn", "台灣的地緣政治風險（國際新聞）", "%s 年 %s 月" % (ks[-1][:4], ks[-1][4:].lstrip("0")), p, True,
                         "國際報導中提到台灣與戰爭、軍事威脅的比例；和近三年比" + _level(p), "Caldara & Iacoviello 地緣政治風險指數"))
    return intl, dom


# ---------------------------------------------------------------- 政治與經濟新聞
def _news(D):
    items = [it for it in (getattr(D, "news_items", None) or []) if (it.get("cat") in MACRO_CATS)]
    if not items:
        return None
    days = sorted(set(it["d"] for it in items if it.get("d")))
    if len(days) < 2:
        return None
    last = days[-1]
    rec_days = set(days[-3:])
    base_days = set(days[-18:-3])
    out = []
    for key, name, kws in TOPICS:
        hit = [it for it in items if any(w in (it.get("t") or "") for w in kws)
               and (key not in DOMESTIC or it.get("cat") in ("tw_macro", "market") or any(w in (it.get("t") or "") for w in TW_WORDS))]
        r = [it for it in hit if it["d"] in rec_days]
        b = [it for it in hit if it["d"] in base_days]
        per_r = len(r) / max(1, len(rec_days))
        per_b = len(b) / max(1, len(base_days)) if base_days else None
        heat = "資料累積中" if not per_b else ("升溫" if per_r >= per_b * 1.5 and len(r) >= 6 else
                                          ("降溫" if per_r <= per_b * 0.6 else "持平"))
        sent = sum(it.get("sent", 0) for it in r) / len(r) if r else 0.0
        tone = "偏空" if sent <= -0.15 else ("偏多" if sent >= 0.15 else "中性")
        top = sorted(r, key=lambda it: (-abs(it.get("sent", 0)), -(it.get("at") or 0)))[:4]
        out.append({"k": key, "name": name, "n": len(r), "per": round(per_r, 1), "base": None if per_b is None else round(per_b, 1),
                    "heat": heat, "sent": round(sent, 3), "tone": tone,
                    "top": [{"t": it.get("t"), "url": it.get("url"), "src": it.get("src"), "at": it.get("at"),
                             "s": round(it.get("sent", 0), 2)} for it in sorted(top, key=lambda it: -(it.get("at") or 0))]})
    out.sort(key=lambda x: -x["n"])
    return {"day": last, "from": min(rec_days), "n": sum(1 for it in items if it["d"] in rec_days), "days": len(days),
            "topics": out}


# ---------------------------------------------------------------- 隔夜美股 → 台股當天
def _irls(np, X, y, l2=1.0, it=30):
    Z = np.c_[np.ones(len(X)), X]
    w = np.zeros(Z.shape[1])
    R = l2 * np.diag(np.r_[0.0, np.ones(Z.shape[1] - 1)])
    for _ in range(it):
        p = 1.0 / (1.0 + np.exp(-np.clip(Z @ w, -30, 30)))
        g = Z.T @ (p - y) + R @ w
        Hm = (Z * (p * (1 - p))[:, None]).T @ Z + R
        s = np.linalg.solve(Hm, g)
        w -= s
        if np.abs(s).max() < 1e-9:
            break
    return w


def _us_series(D, src):
    out = {}
    for sym in US:
        s = dict(((src.get("us_long") or {}).get(sym)) or {})
        ks, vs = _gseries(D, sym)
        s.update(dict(zip(ks, vs)))
        k = sorted(d for d, v in s.items() if v)
        out[sym] = (k, [s[d] for d in k])
    return out


def _overnight(D, src):
    """回傳 (今天的隔夜資訊或 None, 實測統計, 模型)。"""
    import numpy as np
    from risk import _series
    tw = _series(D)
    tds = sorted(tw)
    us = _us_series(D, src)
    if any(len(us[s][0]) < 400 for s in US):
        return None, None
    rows = []
    for k in range(1, len(tds)):
        T, P = tds[k], tds[k - 1]
        rs = []
        for sym in US:
            ds, vs = us[sym]
            j1, j0 = bisect.bisect_left(ds, T) - 1, bisect.bisect_left(ds, P) - 1
            if j0 < 0:
                rs = None
                break
            rs.append(math.log(vs[j1] / vs[j0]) if j1 > j0 else 0.0)
        if rs is None:
            continue
        rows.append((T, sum(rs) / len(rs), math.log(tw[T] / tw[P])))
    if len(rows) < 1500:
        return None, None
    D_ = [r[0] for r in rows]
    x = np.clip(np.array([r[1] for r in rows]) * 50, -4, 4)
    R_ = np.array([r[2] for r in rows])
    y = (R_ > 0).astype(float)
    first = next((i for i, d in enumerate(D_) if d >= START), None)
    if first is None or first < 500:
        return None, None
    pr = np.full(len(y), np.nan)
    w = None
    for i in range(first, len(y)):
        if w is None or (i - first) % REFIT == 0:
            w = _irls(np, x[:i, None], y[:i])
        pr[i] = 1 / (1 + math.exp(-float(w[0] + w[1] * x[i])))
    w = _irls(np, x[:, None], y)
    n = len(y)

    def stat(sel):
        sel = sel & ~np.isnan(pr)
        if sel.sum() < 30:
            return None
        p, yy = pr[sel], y[sel]
        strong = sel & (np.abs(pr - 0.5) >= 0.15)
        return {"n": int(sel.sum()), "hit": round(float(((p > 0.5) == (yy > 0.5)).mean()), 4), "up": round(float(yy.mean()), 4),
                "brier": round(float(((p - yy) ** 2).mean()), 4),
                "brier_base": round(float(((yy.mean() - yy) ** 2).mean()), 4),
                "strong_n": int(strong.sum()),
                "strong_hit": round(float(((pr[strong] > 0.5) == (y[strong] > 0.5)).mean()), 4) if strong.sum() else None}
    idx = np.arange(n)
    st = {"all": stat(idx >= first), "y2": stat(idx >= n - 500), "d60": stat(idx >= n - 60), "from": D_[first]}
    bins = []
    for lo, hi in ((0, 0.3), (0.3, 0.45), (0.45, 0.55), (0.55, 0.7), (0.7, 1.01)):
        s = (idx >= first) & (pr >= lo) & (pr < hi)
        if s.sum():
            bins.append({"lo": lo, "hi": min(1, hi), "n": int(s.sum()), "real": round(float(y[s].mean()), 4),
                         "avg": round(float(R_[s].mean()), 5)})
    st["bins"] = bins
    # 今天：最新美股收盤日期是否晚於台股最後一個交易日（＝下一個台股交易日的隔夜資訊）
    last_tw = tds[-1]
    rs, by, uday = [], {}, None
    for sym in US:
        ds, vs = us[sym]
        if ds[-1] < last_tw:
            return None, st
        j0 = bisect.bisect_left(ds, last_tw) - 1
        if j0 < 0:
            return None, st
        r = math.log(vs[-1] / vs[j0])
        rs.append(r)
        by[sym] = round(math.exp(r) - 1, 4)
        uday = max(uday or "", ds[-1])
    xo = sum(rs) / len(rs)
    xt = max(-4.0, min(4.0, xo * 50))
    p = 1 / (1 + math.exp(-float(w[0] + w[1] * xt)))
    # 過去隔夜情況最相近的 200 天，台股當天的漲跌（過往經驗）
    xs = x[:n]
    near = np.argsort(np.abs(xs - xt))[:200]
    rr = np.sort(R_[near])
    today = {"us_day": uday, "chg": round(math.exp(xo) - 1, 4), "by": by, "p_up": round(p, 4),
             "near": {"n": 200, "up": round(float((rr > 0).mean()), 4), "med": round(float(math.exp(rr[100]) - 1), 4),
                      "lo": round(float(math.exp(rr[40]) - 1), 4), "hi": round(float(math.exp(rr[160]) - 1), 4)}}
    return today, st


# ---------------------------------------------------------------- 一句話與建議
def _next_trading_day(last):
    try:
        from collector import load_calendar
        closed = set(load_calendar().get("closed") or [])
    except Exception:
        closed = set()
    d = dt.datetime.strptime(last, "%Y%m%d").date()
    for _ in range(15):
        d += dt.timedelta(days=1)
        s = d.strftime("%Y%m%d")
        if d.weekday() < 5 and s not in closed:
            return s
    return None


def _md(d):
    return "%s/%s" % (d[4:6].lstrip("0"), d[6:].lstrip("0"))


def _brief(D, ov, risk, intl, dom, news):
    last = D.days[-1]
    target = _next_trading_day(last)
    lv = (risk or {}).get("level")
    d1 = ((risk or {}).get("d1") or {})
    p = ov["p_up"] if ov else None
    if p is None:
        lean = None
    elif p >= 0.65:
        lean = "偏強"
    elif p >= 0.55:
        lean = "小幅偏多"
    elif p > 0.45:
        lean = "方向不明"
    elif p > 0.35:
        lean = "小幅偏弱"
    else:
        lean = "偏弱"
    # 建議（事前定好的規則）
    if lv == "高":
        adv = "持股減半或先不加碼，不追高；等風險降到「正常」再分批買回"
    elif lv == "偏高":
        adv = "不加碼、設好停損，想買的分批進場"
    elif p is not None and p >= 0.65:
        adv = "可照評價清單操作；開高時不要一次追滿，分批進場"
    elif p is not None and p <= 0.35:
        adv = "開盤容易走低，想買的不必急著開盤追，持股照原計畫"
    else:
        adv = "照評價清單操作，控制每檔的金額"
    bad = [x["name"] for x in (intl + dom) if x["tone"] == "偏不利"]
    hot = [t["name"] for t in ((news or {}).get("topics") or []) if t["heat"] == "升溫"]
    if ov:
        us_txt = "隔夜台積電 ADR %+.1f%%、費半 %+.1f%%" % (ov["by"]["TSM"] * 100, ov["by"]["^SOX"] * 100)
        head = "%s台股%s（收紅機率 %d%%，%s）" % (_md(target) + " " if target else "", lean, round(p * 100), us_txt)
    else:
        head = "%s台股：美股收盤後（早上 7:35 左右）更新方向" % (_md(target) + " " if target else "")
    risk_txt = "大跌風險「%s」" % lv if lv else ""
    if lv and d1.get("p") is not None:
        risk_txt += "（跌 2%% 以上機率 %d%%）" % round(d1["p"] * 100)
    sentence = "；".join(x for x in (head, risk_txt) if x) + "。建議：" + adv + "。"
    ctx = []
    if bad:
        ctx.append("需留意：" + "、".join(bad[:3]))
    if hot:
        ctx.append("新聞升溫：" + "、".join(hot[:3]))
    return {"day": last, "target": target, "sentence": sentence, "lean": lean, "p_up": p, "level": lv, "advice": adv,
            "ctx": "；".join(ctx), "has_us": bool(ov), "at": now_tw().strftime("%Y-%m-%d %H:%M")}


def _log_and_eval(D, brief):
    """開盤前（目標日 9:00 以前）的預測存起來，之後對答案。"""
    from risk import _series
    lg = read_json(LOG_PATH, {}) or {}
    now = now_tw()
    t = brief.get("target")
    if t and brief.get("has_us"):
        lock = now.strftime("%Y%m%d") > t or (now.strftime("%Y%m%d") == t and now.strftime("%H%M") >= "0900")
        if not lock:
            lg[t] = {"p": brief["p_up"], "lv": brief["level"], "at": brief["at"], "s": brief["sentence"]}
    tw = _series(D)
    tds = sorted(tw)
    ev = []
    for d, x in sorted(lg.items()):
        if d in tw:
            j = tds.index(d)
            if j > 0 and x.get("p") is not None:
                r = tw[d] / tw[tds[j - 1]] - 1
                x["r"] = round(r, 4)
                ev.append((x["p"], r))
    lg = {k: lg[k] for k in sorted(lg)[-400:]}
    write_json(LOG_PATH, lg)
    if not ev:
        return {"n": 0}
    hit = sum(1 for p, r in ev if (p > 0.5) == (r > 0)) / len(ev)
    return {"n": len(ev), "hit": round(hit, 4), "up": round(sum(1 for _, r in ev if r > 0) / len(ev), 4),
            "rows": [{"d": d, "p": x.get("p"), "r": x.get("r"), "lv": x.get("lv")} for d, x in sorted(lg.items())[-10:]]}


def build(D, risk=None):
    src = read_json(SITU_PATH, {}) or {}
    try:
        intl, dom = _indicators(D, src)
    except Exception as e:
        log("國內外情勢指標失敗：%s" % e)
        intl, dom = [], []
    try:
        news = _news(D)
    except Exception as e:
        log("政經新聞分類失敗：%s" % e)
        news = None
    try:
        ov, ovst = _overnight(D, src)
    except Exception as e:
        import traceback
        log("隔夜美股模型失敗：%s\n%s" % (e, traceback.format_exc()))
        ov, ovst = None, None
    brief = _brief(D, ov, risk, intl, dom, news)
    try:
        brief["live"] = _log_and_eval(D, brief)
    except Exception as e:
        log("盤勢預測紀錄失敗：%s" % e)
    nb = sum(1 for x in intl + dom if x["tone"] == "偏不利")
    ng = sum(1 for x in intl + dom if x["tone"] == "偏有利")
    summ = "國內外情勢：%d 項偏不利、%d 項偏有利、其餘中性。" % (nb, ng)
    out = {"day": D.days[-1], "intl": intl, "dom": dom, "news": news, "overnight": ov, "ov_stat": ovst,
           "brief": brief, "summary": summ, "src_at": src.get("_at"),
           "verdict": "我們用 2005 年以來的資料檢驗過：恐慌指數、利率、美元、油價、地緣政治與政策不確定的新聞指數、景氣燈號、"
                      "新台幣等情勢，對之後一週到三個月大盤漲跌的預測力都很弱（和一律猜漲差不多），也沒有讓大跌風險估得更準，"
                      "所以這裡只用來說明背景。真正有用的是隔夜美股（猜當天收紅或收黑）與大跌風險。政經新聞的主題熱度從 2026/10 才開始累積，"
                      "之後會用前瞻實測檢驗。"}
    return out
