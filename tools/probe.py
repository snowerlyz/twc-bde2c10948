# 測試各資料來源在雲端主機上能否連線（只讀取，不改任何東西）
import json, ssl, urllib.request, re
ctx = ssl.create_default_context()
try:
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
except Exception:
    pass
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
def get(u):
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
        return r.read().decode("utf-8", "replace")
out = {}
def tryit(name, fn):
    try:
        out[name] = fn()
    except Exception as e:
        out[name] = {"error": repr(e)[:300]}
tryit("cnyes", lambda: [{k: (v if k != "content" else str(v)[:120]) for k, v in it.items()} for it in json.loads(get("https://api.cnyes.com/media/api/v1/newslist/category/tw_stock?limit=5"))["items"]["data"][:3]])
tryit("cnyes_headline", lambda: json.loads(get("https://api.cnyes.com/media/api/v1/newslist/category/headline?limit=3"))["items"]["data"][0].keys().__repr__())
tryit("yahoo_rss_stock", lambda: get("https://tw.stock.yahoo.com/rss?s=2330")[:1500])
tryit("yahoo_rss_market", lambda: re.findall(r"<item>.*?</item>", get("https://tw.stock.yahoo.com/rss?category=tw-market"), re.S)[:2])
tryit("google_rss", lambda: re.findall(r"<item>.*?</item>", get("https://news.google.com/rss/search?q=%E5%8F%B0%E7%A9%8D%E9%9B%BB+when:7d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"), re.S)[:2])
tryit("ap04_L", lambda: (lambda j: {"n": len(j), "dates": sorted(set(x.get("發言日期") for x in j))[-5:], "keys": list(j[0].keys()), "titles": [x.get("主旨 ", x.get("主旨", ""))[:80] for x in j[:8]]})(json.loads(get("https://openapi.twse.com.tw/v1/opendata/t187ap04_L"))))
tryit("tpex_warn", lambda: json.loads(get("https://www.tpex.org.tw/openapi/v1/tpex_trading_warning_information"))[:2])
tryit("tpex_disp", lambda: json.loads(get("https://www.tpex.org.tw/openapi/v1/tpex_disposal_information"))[:2])
tryit("twse_notetrans", lambda: json.loads(get("https://openapi.twse.com.tw/v1/announcement/notetrans"))[:2])
tryit("twse_notice_rwd", lambda: json.loads(get("https://www.twse.com.tw/rwd/zh/announcement/notice?startDate=20261016&endDate=20261016&response=json")).get("data", [])[:2])
def yh(sym):
    j = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/%s?range=1y&interval=1d" % urllib.request.quote(sym)))
    r = j["chart"]["result"][0]
    q = r["indicators"]["quote"][0]["close"]
    return {"n": len(r["timestamp"]), "last": q[-3:], "t0": r["timestamp"][0], "tz": r["meta"].get("exchangeTimezoneName")}
for sym in ["^GSPC", "^IXIC", "^SOX", "^VIX", "^TNX", "TWD=X", "^N225", "TSM", "^TWII", "DX-Y.NYB", "CL=F"]:
    tryit("yahoo " + sym, lambda s=sym: yh(s))
json.dump(out, open("probe_result.json", "w"), ensure_ascii=False, indent=1)
print("done")
