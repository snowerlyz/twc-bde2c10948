# -*- coding: utf-8 -*-
"""法規與重大消息（2026-11-25，使用者要求「把消息跟法規也納入考量，像限空令、黃仁勳回歸都對股市有重大影響」）。

一、事件庫 app/events.json（人工整理，每天調校時依新聞補上）：目前有效的法規／救市措施、重大消息、歷次限空令。
二、自動偵測：最近 3 天新聞標題出現法規、救市相關字詞（限空、融券、借券、擔保維持率、處置股、國安基金…）就列出來，
    提醒「可能有新措施」，由每日調校確認後補進事件庫。
三、歷次限空令之後加權指數怎麼走（用 2000 年起的加權指數日線自己算）：只有 5 次，當背景說明，不拿來預測。
四、對評價與機器人的影響（研究筆記 2026-11-25）：
    - 限空令只限制融券、借券賣出，不直接影響評價的計算；融券多的股票在限空期間沒有一致的超額報酬（2025 年 +0.47%、
      2026 年 −0.53%／5 天），所以不加進評分。
    - 重大消息帶動的行情，模型看不懂消息本身：2026/11/9 起短期排名前 10% 只有約 2 成跑贏加權指數（平常約 45%），
      網頁在事件期間提醒「短期評價參考價值較低」。這是說明，不改評價與把關。
    - 機器人當沖：開盤就漲停不先賣（漲停鎖住常常買不回，現股當沖買不回會違約交割，限空令期間也不能改列融券）。
"""
import os

from util import DB, read_json

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "events.json")
RULE_WORDS = ["限空", "禁空", "放空", "平盤以下", "平盤下", "融券", "借券", "擔保維持率", "維持率", "處置股", "國安基金",
              "救市", "護盤", "證交稅", "當沖稅", "漲跌幅限制", "庫藏股"]
NEWS_CATS = ("tw_macro", "market", "tw_stock", "headline")
LESSON = {
    "asof": "20261124",
    "short_top": 0.202, "short_all": 0.379, "short_norm": 0.449, "short_norm_all": 0.404, "days": 7,
    "sb_ban": 0.0030, "sb_2025": 0.0047, "sb_2026": -0.0053,
}


def _taiex(D):
    """加權指數日線：2000 年起的長期資料（db/twii_long.json），再用本地收盤補上最新幾天。"""
    s = dict(((read_json(os.path.join(DB, "twii_long.json"), {}) or {}).get("s") or {}))
    tx = D.mkt.get("taiex") or []
    for d, v in zip(D.days, tx):
        if v == v and v:
            s[d] = v
    ks = sorted(s)
    return ks, [s[k] for k in ks]


def _ret(ks, px, i0, i1):
    if i0 < 0 or i1 >= len(ks) or i0 >= len(ks):
        return None
    return round(px[i1] / px[i0] - 1, 4)


def _idx(ks, d):
    """第一個 >= d 的交易日索引。"""
    import bisect
    return bisect.bisect_left(ks, d)


def _detect(D, known_days):
    items = [it for it in (getattr(D, "news_items", None) or []) if it.get("cat") in NEWS_CATS and it.get("d")]
    if not items:
        return []
    days = sorted(set(it["d"] for it in items))[-3:]
    seen, out = set(), []
    for it in sorted(items, key=lambda x: -(x.get("at") or 0)):
        t = it.get("t") or ""
        if it["d"] not in days or not any(w in t for w in RULE_WORDS):
            continue
        key = t[:18]
        if key in seen:
            continue
        seen.add(key)
        out.append({"t": t, "url": it.get("url"), "src": it.get("src"), "d": it["d"],
                    "w": [w for w in RULE_WORDS if w in t][:3]})
        if len(out) >= 8:
            break
    return out


def build(D):
    cfg = read_json(PATH, {}) or {}
    ks, px = _taiex(D)
    last = D.days[-1]
    ev_out = []
    for e in cfg.get("events") or []:
        if e["start"] > last:
            continue
        active = e.get("end") is None or e["end"] >= last
        i = _idx(ks, e["start"])
        if i >= len(ks):
            continue
        x = dict(e, active=active,
                 day_ret=_ret(ks, px, i - 1, i),          # 生效（反應）當天加權指數漲跌
                 since=_ret(ks, px, i - 1, len(ks) - 1),   # 生效前一天收盤到最新
                 n_days=len(ks) - i)
        if active or x["n_days"] <= 60:
            ev_out.append(x)
    ev_out.sort(key=lambda x: (x["start"], x["id"]), reverse=True)
    hist = []
    for b in cfg.get("bans") or []:
        i = _idx(ks, b["d"])
        if i >= len(ks) or i == 0:
            continue
        hist.append({"d": ks[i], "name": b["name"], "what": b.get("what"), "base": round(px[i - 1], 2),
                     "f5": _ret(ks, px, i - 1, i + 4), "f20": _ret(ks, px, i - 1, i + 19), "f60": _ret(ks, px, i - 1, i + 59)})
    done = [h for h in hist if h["f60"] is not None]
    rules = [e for e in ev_out if e["active"] and e["kind"] == "rule"]
    ban = None
    if any(e.get("group") == "限空令" for e in rules):
        st = min(e["start"] for e in rules if e.get("group") == "限空令")
        i = _idx(ks, st)
        full = [e["start"] for e in rules if e.get("group") == "限空令" and "全面" in e["title"]]
        ban = {"start": st, "full": min(full) if full else None, "since": _ret(ks, px, i - 1, len(ks) - 1), "n_days": len(ks) - i}
    big = [e for e in ev_out if e["active"] and e["kind"] == "news" and e["n_days"] <= 20]
    return {
        "day": last,
        "events": ev_out,
        "ban": ban,
        "hist": hist,
        "hist_sum": {"n": len(done), "up60": sum(1 for h in done if h["f60"] > 0),
                     "avg20": round(sum(h["f20"] for h in done) / len(done), 4) if done else None,
                     "avg60": round(sum(h["f60"] for h in done) / len(done), 4) if done else None},
        "detect": _detect(D, set(e["start"] for e in ev_out)),
        "caution": bool(big) or ban is not None,
        "lesson": LESSON,
    }
