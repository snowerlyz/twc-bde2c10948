# -*- coding: utf-8 -*-
"""研究用：抓各國主要指數的長期日線（Yahoo），給「歷史大跌事件研究」做跨市場驗證。
執行：連線測試工作流程，script=tools/crash_fetch.py，branch=probe-crash。"""
import datetime as dt
import json
import os
import ssl
import time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
ctx = ssl.create_default_context()
os.makedirs("probe_files", exist_ok=True)
SYMS = ["^TWII", "^GSPC", "^IXIC", "^N225", "^HSI", "^KS11", "^SOX", "^DJI", "^GDAXI", "^FTSE", "0050.TW"]
res = {}
for s in SYMS:
    out = None
    for host in ("query1", "query2"):
        try:
            u = ("https://%s.finance.yahoo.com/v8/finance/chart/%s?period1=-1500000000&period2=%d&interval=1d&events=div%%7Csplit"
                 % (host, urllib.parse.quote(s), int(time.time())))
            req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
                j = json.loads(r.read())
            r0 = j["chart"]["result"][0]
            off = r0["meta"].get("gmtoffset") or 0
            q = r0["indicators"]["quote"][0]
            adj = ((r0["indicators"].get("adjclose") or [{}])[0] or {}).get("adjclose")
            rows = {}
            for i, ts in enumerate(r0["timestamp"]):
                c = q["close"][i]
                if c is None:
                    continue
                d = dt.datetime.utcfromtimestamp(ts + off).strftime("%Y%m%d")
                rows[d] = [q["open"][i], q["high"][i], q["low"][i], c, adj[i] if adj else None]
            out = rows
            break
        except Exception as e:
            res[s + "_err"] = str(e)
    if out:
        json.dump(out, open("probe_files/%s.json" % s.replace("^", "").replace(".", "_"), "w"))
        ds = sorted(out)
        res[s] = {"n": len(ds), "first": ds[0], "last": ds[-1]}
    time.sleep(1)
json.dump(res, open("probe_result.json", "w"), ensure_ascii=False, indent=1)
