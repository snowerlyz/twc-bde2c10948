# -*- coding: utf-8 -*-
"""消息面與國際市場資料。

消息面（每天存一份，日後模型可用歷史檢驗效果）：
  - 鉅亨網台股新聞（每則新聞附有相關股票代號）
  - Yahoo 股市台股新聞（大盤消息）
  - 公開資訊觀測站重大訊息（上市、上櫃）
  - 注意股票、處置股票（上市、上櫃）
國際市場（每次更新整份覆蓋）：Yahoo Finance 日線
"""
import datetime as dt
import html
import os
import re
import time

from util import DB, fetch, fetch_json, log, now_tw, read_json, roc_to_ymd, write_json

NEWS_DIR = os.path.join(DB, "parts", "news")
GLOBAL_PATH = os.path.join(DB, "global.json")

# ---------------------------------------------------------------- 情緒詞庫
POS = ["創新高", "新高", "成長", "大增", "增長", "優於預期", "超乎預期", "超預期", "看好", "調升", "上修", "上調", "受惠",
       "接單", "訂單", "擴產", "漲價", "獲利", "轉盈", "轉虧為盈", "買超", "加碼", "利多", "大漲", "漲停", "強勢", "突破",
       "回溫", "熱銷", "得標", "樂觀", "亮眼", "爆發", "復甦", "雙增", "攀升", "增溫", "旺季", "供不應求", "強勁", "創高",
       "翻紅", "反彈", "續強", "看俏", "放量", "大單", "急單", "滿載", "認證", "量產", "出貨暢旺", "調高目標價", "上調目標價", "升目標價", "漲逾", "V轉", "大漲", "噴出", "飆漲",
       "填息", "填權", "獲利了結", "強漲", "必買", "買點", "攻高", "上攻", "勁揚", "走高", "收紅", "大買", "偏多", "看多"]
NEG = ["衰退", "下滑", "減少", "虧損", "轉虧", "下修", "調降", "下調", "不如預期", "低於預期", "利空", "賣超", "減碼", "大跌",
       "跌停", "重挫", "疲弱", "停工", "裁員", "減產", "罰", "違約", "訴訟", "掏空", "示警", "警訊", "處置", "注意股", "跳票",
       "下市", "全額交割", "保守", "砍單", "庫存調整", "跌破", "失守", "賣壓", "翻黑", "崩", "暴跌", "疑慮", "延後",
       "取消", "火災", "事故", "停產", "弱勢", "走弱", "回檔", "降評", "降等", "淡季", "衝擊", "降目標價", "下調目標價", "續挫", "跌逾", "殺盤",
       "風險", "難放心", "倒閉", "破產", "貶值", "暴雷", "見頂", "泡沫", "崩跌", "利空", "制裁", "關稅", "撤資", "賣壓沉重", "雙殺", "重貶", "斷頭", "收黑", "走低", "大賣", "倒貨", "急殺", "偏空", "看空"]


MACRO_BAD = ["殖利率", "通膨", "油價", "美元指數", "失業率", "公債利率", "CPI", "PCE"]   # 這些東西「創新高、攀升」對股市是壞消息
UP_WORDS = {"創新高", "新高", "攀升", "增溫", "大增", "飆", "創高", "強勁", "上調", "調升"}


def sentiment(text):
    """回傳 -1～1 的情緒分數與命中的詞。"""
    if not text:
        return 0.0, []
    t = re.sub(r"\s+", "", text)
    pos = [w for w in POS if w in t]
    neg = [w for w in NEG if w in t]
    # 「創新高」已含「新高」，避免重複計分
    pos = [w for w in pos if not any(w != o and w in o for o in pos)]
    neg = [w for w in neg if not any(w != o and w in o for o in neg)]
    if any(m in t for m in MACRO_BAD):
        flip = [w for w in pos if w in UP_WORDS]
        pos = [w for w in pos if w not in UP_WORDS]
        neg = neg + flip
    if "獲利了結" in pos:
        pos.remove("獲利了結")
        neg.append("獲利了結")
    p, n = len(pos), len(neg)
    if p + n == 0:
        return 0.0, []
    return (p - n) / (p + n + 1.0), pos[:3] + neg[:3]


def sentiment2(title, summ=""):
    """標題為主；標題看不出多空時才參考摘要（打五折）。"""
    sc, w = sentiment(title)
    if w:
        return sc, w
    sc2, w2 = sentiment((summ or "")[:80])
    return sc2 * 0.5, w2


def _clean(s):
    s = html.unescape(str(s or ""))
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- 消息面
def fetch_cnyes(days=4, max_pages=8):
    cutoff = time.time() - days * 86400
    items = []
    for cat in ("tw_stock", "headline"):
        for page in range(1, max_pages + 1):
            try:
                j = fetch_json("https://api.cnyes.com/media/api/v1/newslist/category/%s?limit=50&page=%d" % (cat, page), retries=2)
            except Exception as e:
                log("鉅亨新聞 %s p%d：%s" % (cat, page, e))
                break
            data = (j.get("items") or {}).get("data") or []
            if not data:
                break
            old = False
            for it in data:
                at = it.get("publishAt") or 0
                if at < cutoff:
                    old = True
                    continue
                title = _clean(it.get("title"))
                summ = _clean(it.get("summary") or it.get("content"))[:160]
                sc, words = sentiment2(title, summ)
                items.append({"id": it.get("newsId"), "t": title, "s": summ, "at": at, "src": "鉅亨網",
                              "url": "https://news.cnyes.com/news/id/%s" % it.get("newsId"),
                              "codes": [c for c in (it.get("stock") or []) if re.fullmatch(r"\w{4,6}", str(c))],
                              "cat": cat, "sent": round(sc, 3), "kw": words})
            if old:
                break
    # 去重
    seen, out = set(), []
    for it in sorted(items, key=lambda x: -x["at"]):
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        out.append(it)
    return out


def fetch_yahoo_market():
    try:
        x = fetch("https://tw.stock.yahoo.com/rss?category=tw-market")
    except Exception as e:
        log("Yahoo 新聞：%s" % e)
        return []
    out = []
    for m in re.finditer(r"<item>(.*?)</item>", x, re.S):
        b = m.group(1)
        t = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", b, re.S)
        l = re.search(r"<link>(.*?)</link>", b, re.S)
        d = re.search(r"<description><!\[CDATA\[(.*?)\]\]></description>", b, re.S)
        p = re.search(r"<pubDate>(.*?)</pubDate>", b, re.S)
        if not t:
            continue
        title = _clean(t.group(1))
        summ = _clean(d.group(1) if d else "")[:160]
        try:
            at = int(dt.datetime.strptime(p.group(1).strip(), "%a, %d %b %Y %H:%M:%S %Z").replace(
                tzinfo=dt.timezone.utc).timestamp()) if p else 0
        except Exception:
            at = 0
        sc, words = sentiment2(title, summ)
        out.append({"t": title, "s": summ, "at": at, "src": "Yahoo股市", "url": l.group(1).strip() if l else "",
                    "codes": [], "cat": "market", "sent": round(sc, 3), "kw": words})
    return out


def fetch_mops():
    out = []
    for url, ck in (("https://openapi.twse.com.tw/v1/opendata/t187ap04_L", "公司代號"),
                    ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O", "SecuritiesCompanyCode")):
        try:
            rows = fetch_json(url)
        except Exception as e:
            log("重大訊息：%s" % e)
            continue
        for r in rows if isinstance(rows, list) else []:
            code = str(r.get(ck) or r.get("公司代號") or "").strip()
            title = _clean(r.get("主旨 ") or r.get("主旨") or "")
            if not code or not title:
                continue
            sc, words = sentiment(title)
            out.append({"c": code, "t": title[:120], "d": roc_to_ymd(r.get("發言日期", "")), "sent": round(sc, 3)})
    return out


def _period_end(p):
    """'115/10/20~115/10/27'、'1151020~1151027' → '20261027'"""
    m = re.findall(r"(\d{3})/?(\d{2})/?(\d{2})", str(p or ""))
    if not m:
        return None
    y, mo, d = m[-1]
    return "%04d%s%s" % (int(y) + 1911, mo, d)


def fetch_alerts(day):
    warn, disp = {}, {}
    try:
        j = fetch_json("https://www.twse.com.tw/rwd/zh/announcement/notice?startDate=%s&endDate=%s&response=json" % (day, day))
        for r in j.get("data") or []:
            warn[str(r[1]).strip()] = _clean(r[4])[:80]
    except Exception as e:
        log("上市注意股：%s" % e)
    try:
        for r in fetch_json("https://openapi.twse.com.tw/v1/announcement/punish"):
            code = str(r.get("Code") or r.get("證券代號") or "").strip()
            per = r.get("DispositionPeriod") or r.get("處置起迄時間") or ""
            end = _period_end(per)
            if code and (end is None or end >= day):
                disp[code] = "處置期間 %s" % per
    except Exception as e:
        log("上市處置股：%s" % e)
    try:
        for r in fetch_json("https://www.tpex.org.tw/openapi/v1/tpex_trading_warning_information"):
            if roc_to_ymd(r.get("Date", "")) in (day, None):
                warn[str(r.get("SecuritiesCompanyCode", "")).strip()] = _clean(r.get("TradingInformation"))[:80]
    except Exception as e:
        log("上櫃注意股：%s" % e)
    try:
        for r in fetch_json("https://www.tpex.org.tw/openapi/v1/tpex_disposal_information"):
            per = r.get("DispositionPeriod", "")
            end = _period_end(per)
            if end is None or end >= day:
                disp[str(r.get("SecuritiesCompanyCode", "")).strip()] = "處置期間 %s" % per
    except Exception as e:
        log("上櫃處置股：%s" % e)
    warn.pop("", None)
    disp.pop("", None)
    return warn, disp


def collect_news(day, trade_day=None):
    """抓當天的消息面資料存成 parts/news/<day>.json.gz（同一天重抓會合併）。"""
    path = os.path.join(NEWS_DIR, day + ".json.gz")
    old = read_json(path, {}) or {}
    items = fetch_cnyes() + fetch_yahoo_market()
    mops = fetch_mops()
    warn, disp = fetch_alerts(trade_day or day)
    # 合併舊資料（同日多次更新）
    seen = set((it.get("url") or it.get("t")) for it in items)
    for it in old.get("items", []):
        k = it.get("url") or it.get("t")
        if k not in seen:
            items.append(it)
            seen.add(k)
    ms = set((m["c"], m["t"]) for m in mops)
    for m in old.get("mops", []):
        if (m["c"], m["t"]) not in ms:
            mops.append(m)
    w0, d0 = old.get("warn", {}), old.get("disp", {})
    w0.update(warn)
    d0.update(disp)
    obj = {"day": day, "at": now_tw().strftime("%Y-%m-%d %H:%M"), "items": items[:1500], "mops": mops, "warn": w0, "disp": d0}
    write_json(path, obj, gz=True)
    log("消息面：新聞 %d 則、重大訊息 %d 則、注意股 %d、處置股 %d" % (len(items), len(mops), len(w0), len(d0)))
    return obj


# ---------------------------------------------------------------- 國際市場
GLOBAL_SYMBOLS = [
    ("^SOX", "費城半導體"), ("^IXIC", "那斯達克"), ("^GSPC", "標普 500"), ("TSM", "台積電 ADR"),
    ("^VIX", "恐慌指數 VIX"), ("^TNX", "美國 10 年債殖利率"), ("TWD=X", "美元兌新台幣"), ("DX-Y.NYB", "美元指數"),
    ("^N225", "日經 225"), ("CL=F", "原油"),
    ("^DJI", "道瓊工業"), ("^KS11", "韓國綜合"), ("^HSI", "香港恒生"), ("000001.SS", "上海綜合"),
    ("^GDAXI", "德國 DAX"), ("NVDA", "輝達"), ("GC=F", "黃金"),
]


def collect_global():
    out = read_json(GLOBAL_PATH, {}) or {}
    ok = 0
    for sym, name in GLOBAL_SYMBOLS:
        for host in ("query1", "query2"):
            try:
                j = fetch_json("https://%s.finance.yahoo.com/v8/finance/chart/%s?range=2y&interval=1d" % (
                    host, sym.replace("^", "%5E")), retries=2)
                r = j["chart"]["result"][0]
                tz = r["meta"].get("exchangeTimezoneName") or "UTC"
                gmtoff = r["meta"].get("gmtoffset") or 0
                closes = r["indicators"]["quote"][0]["close"]
                series = {}
                for ts, c in zip(r["timestamp"], closes):
                    if c is None:
                        continue
                    d = dt.datetime.utcfromtimestamp(ts + gmtoff).strftime("%Y%m%d")
                    series[d] = round(float(c), 4)
                if series:
                    out[sym] = {"name": name, "tz": tz, "s": series}
                    ok += 1
                break
            except Exception as e:
                last = e
        else:
            log("國際市場 %s：%s" % (sym, last))
    if ok:
        out["_at"] = now_tw().strftime("%Y-%m-%d %H:%M")
        write_json(GLOBAL_PATH, out)
    log("國際市場：取得 %d/%d 項" % (ok, len(GLOBAL_SYMBOLS)))
    return out
