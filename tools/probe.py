# 測試各資料來源在雲端主機上能否連線（只讀取，不改任何東西）
import json, ssl, sys, urllib.request, re
ctx = ssl.create_default_context()
try:
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
except Exception:
    pass
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
URLS = [
  "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
  "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O",
  "https://www.twse.com.tw/rwd/zh/announcement/notice?response=json",
  "https://www.twse.com.tw/rwd/zh/announcement/punish?response=json",
  "https://openapi.twse.com.tw/v1/announcement/punish",
  "https://openapi.twse.com.tw/v1/announcement/notice",
  "https://api.cnyes.com/media/api/v1/newslist/category/tw_stock?limit=30",
  "https://news.google.com/rss/search?q=%E5%8F%B0%E8%82%A1&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
  "https://tw.stock.yahoo.com/rss?category=tw-market",
  "https://query1.finance.yahoo.com/v8/finance/chart/%5ESOX?range=1y&interval=1d",
  "https://query2.finance.yahoo.com/v8/finance/chart/TWD=X?range=1y&interval=1d",
  "https://stooq.com/q/d/l/?s=%5Espx&i=d",
  "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
]
out = {}
for u in URLS:
    try:
        req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
            b = r.read()
            out[u] = {"status": r.status, "len": len(b), "ct": r.headers.get("Content-Type"), "head": b[:700].decode("utf-8", "replace")}
    except Exception as e:
        out[u] = {"error": repr(e)[:300]}
for base in ("https://openapi.twse.com.tw/v1/swagger.json", "https://www.tpex.org.tw/openapi/swagger.json"):
    try:
        req = urllib.request.Request(base, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
            j = json.loads(r.read())
        out[base] = [p + " | " + (v.get("get", {}).get("summary") or "") for p, v in j["paths"].items()
                     if re.search(r"重大|注意|處置|公告|訊息|變更交易|全額", (v.get("get", {}).get("summary") or ""))]
    except Exception as e:
        out[base] = {"error": repr(e)[:300]}
json.dump(out, open("probe_result.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: (v.get("status") or v.get("error")) if isinstance(v, dict) else len(v) for k, v in out.items()}, ensure_ascii=False, indent=1))
