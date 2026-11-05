# -*- coding: utf-8 -*-
"""研究用：抓國內外情勢的長期歷史資料（國際行情、地緣政治風險、經濟政策不確定、景氣燈號、鉅亨政經新聞），存 probe 分支。"""
import json, os, sys, time, urllib.request, ssl, gzip, datetime as dt
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
ctx = ssl.create_default_context()
OUT = "probe_files"
os.makedirs(OUT, exist_ok=True)
log = {}


def get(u, timeout=60):
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            b = gzip.decompress(b)
        return b


def yahoo(sym):
    j = json.loads(get("https://query2.finance.yahoo.com/v8/finance/chart/%s?period1=946684800&period2=%d&interval=1d"
                       % (sym.replace("^", "%5E"), int(time.time()))))
    r = j["chart"]["result"][0]
    tz = r["meta"].get("gmtoffset", 0)
    ts, q = r["timestamp"], r["indicators"]["quote"][0]
    s = {}
    for t, o, c in zip(ts, q["open"], q["close"]):
        if c is None:
            continue
        d = dt.datetime.utcfromtimestamp(t + tz).strftime("%Y%m%d")
        s[d] = [None if o is None else round(o, 4), round(c, 4)]
    return s


ys = {}
for s in ("^VIX", "^TNX", "^IRX", "DX-Y.NYB", "TWD=X", "CL=F", "GC=F", "HG=F", "^SOX", "^GSPC", "TSM", "^TWII", "^N225", "^KS11", "^HSI"):
    try:
        ys[s] = yahoo(s)
        log[s] = len(ys[s])
    except Exception as e:
        log[s] = str(e)[:200]
    time.sleep(1)
json.dump(ys, gzip.open(OUT + "/yahoo.json.gz", "wt"))
for name, u in (("gpr_daily.xls", "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"),
                ("gpr_monthly.xls", "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"),
                ("epu_daily.csv", "https://www.policyuncertainty.com/media/All_Daily_Policy_Data.csv"),
                ("ndc.zip", "https://ws.ndc.gov.tw/Download.ashx?u=LzAwMS9hZG1pbmlzdHJhdG9yLzEwL3JlbGZpbGUvNTc4MS82MzkyL2VhMjM1YmQ5LWQwNTItNGE2OS1hYmZjLWQ1Yzc4NWQzZDBlMi56aXA%3d&n=5pmv5rCj5oyH5qiZ5Y%2bK54eI6JmfLnppcA%3d%3d&icon=.zip"),
                ("fred_epu.csv", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=USEPUINDXD")):
    try:
        b = get(u, 120)
        open(OUT + "/" + name, "wb").write(b)
        log[name] = len(b)
    except Exception as e:
        log[name] = str(e)[:200]
# 鉅亨政經新聞（台灣政經、國際政經）2019 起，每週一個區間
news = []
t0 = int(dt.datetime(2019, 1, 1).timestamp())
now = int(time.time())
errs = 0
for cat in (() if "nonews" in sys.argv else ("tw_macro", "wd_macro")):
    t = t0
    while t < now and errs < 50:
        e = min(now, t + 7 * 86400)
        page = 1
        while True:
            try:
                j = json.loads(get("https://api.cnyes.com/media/api/v1/newslist/category/%s?limit=100&startAt=%d&endAt=%d&page=%d"
                                   % (cat, t, e, page), 40))
            except Exception as ex:
                errs += 1
                log.setdefault("cnyes_err", []).append("%s %d %s" % (cat, t, str(ex)[:80]))
                time.sleep(3)
                break
            it = j.get("items") or {}
            for x in it.get("data") or []:
                news.append([x.get("publishAt"), cat, x.get("title"), (x.get("summary") or "")[:120]])
            if not it.get("next_page_url") or page >= 10:
                break
            page += 1
            time.sleep(0.3)
        t = e
        time.sleep(0.3)
log["news"] = len(news)
json.dump(news, gzip.open(OUT + "/cnyes_macro.json.gz", "wt"), ensure_ascii=False)
json.dump(log, open("probe_result.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in log.items()}, ensure_ascii=False))
