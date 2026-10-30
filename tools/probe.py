# -*- coding: utf-8 -*-
"""連線測試：證交所即時行情（MIS）能不能抓、有沒有允許網頁跨網域讀取（CORS）。"""
import json, os, time, urllib.request, ssl
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
ctx = ssl.create_default_context(); ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
os.makedirs("probe_files", exist_ok=True)
res = {}
def get(name, url, origin=None):
    h = {"User-Agent": UA, "Referer": "https://mis.twse.com.tw/stock/fibest.jsp"}
    if origin:
        h["Origin"] = origin
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            body = r.read()
            open("probe_files/" + name, "wb").write(body)
            res[name] = {"status": r.status, "headers": dict(r.headers.items()), "len": len(body)}
    except Exception as e:
        res[name] = {"error": str(e)}
    time.sleep(1)
ts = int(time.time() * 1000)
q = "tse_2330.tw|tse_2317.tw|otc_3105.tw|tse_0050.tw"
get("mis1.json", "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=%s&json=1&delay=0&_=%d" % (q, ts), origin="https://snowerlyz.github.io")
for i in range(6):          # 連續抓幾次，看更新頻率與成交量變化
    get("mis_seq%d.json" % i, "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_2330.tw|tse_2317.tw&json=1&delay=0&_=%d" % int(time.time() * 1000))
    time.sleep(4)
get("odd.json", "https://mis.twse.com.tw/stock/api/getOddInfo.jsp?ex_ch=tse_2330.tw&json=1&delay=0&_=%d" % ts)
json.dump(res, open("probe_result.json", "w"), ensure_ascii=False, indent=1)
