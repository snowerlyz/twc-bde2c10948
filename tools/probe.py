# -*- coding: utf-8 -*-
"""連線測試：證交所即時行情（MIS）更新頻率（帶 cookie、連續抓 90 秒）。"""
import json, os, time, urllib.request, ssl, http.cookiejar
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
ctx = ssl.create_default_context(); ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), urllib.request.HTTPCookieProcessor(cj))
os.makedirs("probe_files", exist_ok=True)
def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://mis.twse.com.tw/stock/fibest.jsp?stock=2330", "Accept": "application/json"})
    with op.open(req, timeout=20) as r:
        return r.read()
try:
    get("https://mis.twse.com.tw/stock/index.jsp")
except Exception as e:
    print("index", e)
seq = []
t0 = time.time()
while time.time() - t0 < 90:
    try:
        b = get("https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_2330.tw|tse_2317.tw|tse_2603.tw&json=1&delay=0&_=%d" % int(time.time() * 1000))
        j = json.loads(b)
        seq.append({"at": round(time.time() - t0, 1), "rows": [{k: x.get(k) for k in ("c", "t", "tlong", "z", "tv", "v", "a", "f", "b", "g", "trade")} for x in j.get("msgArray", [])]})
    except Exception as e:
        seq.append({"at": round(time.time() - t0, 1), "err": str(e)})
    time.sleep(3)
json.dump(seq, open("probe_files/seq.json", "w"), ensure_ascii=False)
json.dump({"n": len(seq)}, open("probe_result.json", "w"))
