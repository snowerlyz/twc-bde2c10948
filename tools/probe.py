# -*- coding: utf-8 -*-
"""連線測試：Yahoo 奇摩股市即時報價的更新頻率與 CORS。"""
import json, os, time, urllib.request, ssl
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
ctx = ssl.create_default_context()
os.makedirs("probe_files", exist_ok=True)
U = "https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.stockList;fields=avgPrice%2Corderbook;symbols=2330.TW%2C2317.TW%2C3105.TWO"
res = {}
req = urllib.request.Request(U, headers={"User-Agent": UA, "Origin": "https://snowerlyz.github.io", "Accept": "application/json"})
with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
    res["headers"] = dict(r.headers.items())
seq = []
t0 = time.time()
while time.time() - t0 < 60:
    try:
        req = urllib.request.Request(U + "&_=%d" % int(time.time() * 1000), headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            j = json.loads(r.read())
        seq.append({"at": round(time.time() - t0, 1), "rows": [{k: x.get(k) for k in ("symbol", "regularMarketTime", "volume", "inMarket", "outMarket")} | {"p": (x.get("price") or {}).get("raw"), "ob0": (x.get("orderbook") or [{}])[0]} for x in j]})
    except Exception as e:
        seq.append({"at": round(time.time() - t0, 1), "err": str(e)})
    time.sleep(3)
json.dump(seq, open("probe_files/yseq.json", "w"), ensure_ascii=False)
json.dump(res, open("probe_result.json", "w"), ensure_ascii=False, indent=1)
