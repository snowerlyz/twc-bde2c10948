# -*- coding: utf-8 -*-
"""連線測試：在 GitHub 上抓資料存到 probe 分支，給研究用（雲端開發環境連不到外部網站）。"""
import json, os, time, urllib.request, ssl
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
ctx = ssl.create_default_context(); ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
os.makedirs("probe_files", exist_ok=True)
def save(name, url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90, context=ctx) as r:
        open("probe_files/" + name, "wb").write(r.read())
    time.sleep(2)
res = {}
for sym in ("%5ETWII",):
    for host in ("query1", "query2"):
        try:
            save("twii_max.json", "https://%s.finance.yahoo.com/v8/finance/chart/%s?period1=946684800&period2=%d&interval=1d" % (host, sym, int(time.time())))
            res[sym] = "ok"
            break
        except Exception as e:
            res[sym] = str(e)
json.dump(res, open("probe_result.json", "w"))
