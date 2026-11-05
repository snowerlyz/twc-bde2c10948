# -*- coding: utf-8 -*-
"""連線測試：國內外情勢資料來源（長期歷史，供 walk-forward 驗證）。結果存 probe 分支。"""
import json, os, time, urllib.request, ssl, gzip
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
ctx = ssl.create_default_context()
os.makedirs("probe_files", exist_ok=True)
res = {}


def get(u, n=None):
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            b = gzip.decompress(b)
        return r.status, r.headers.get("Content-Type"), b


def probe(name, u, save=True):
    try:
        st, ct, b = get(u)
        res[name] = {"ok": True, "status": st, "type": ct, "size": len(b), "head": b[:300].decode("utf-8", "replace")}
        if save:
            open("probe_files/" + name, "wb").write(b)
    except Exception as e:
        res[name] = {"ok": False, "err": str(e)[:300], "url": u}
    time.sleep(1)


for s in ("^VIX", "^TNX", "^IRX", "DX-Y.NYB", "TWD=X", "CL=F", "GC=F", "HG=F", "^SOX", "^GSPC", "^TWII"):
    probe("yh_" + s.replace("^", "").replace("=", "_"),
          "https://query2.finance.yahoo.com/v8/finance/chart/%s?period1=946684800&period2=%d&interval=1d" % (s.replace("^", "%5E"), int(time.time())))
fred = ("USEPUINDXD", "T10Y2Y", "BAMLH0A0HYM2", "DTWEXBGS", "VIXCLS", "STLFSI4", "GEPUCURRENT", "NFCI")
for s in fred:
    probe("fred_" + s, "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + s)
probe("gpr_daily_xls", "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls")
probe("gpr_monthly_xls", "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls")
probe("gpr_page", "https://www.matteoiacoviello.com/gpr.htm")
probe("ndc_ind", "https://index.ndc.gov.tw/n/json/data/eco/indicators")
probe("ndc_dataset", "https://data.gov.tw/api/v2/rest/dataset/6099")
probe("ndc_light_csv", "https://ws.ndc.gov.tw/Download.ashx?u=LzAwMS9hZG1pbmlzdHJhdG9yLzEwL3JlbGZpbGUvNTc4MS82MzkyL2RhMmY4ZDg0LTkxY2MtNGI4Zi05YTJjLTQwYmUxN2U2MTgzNi5jc3Y%3d&n=5pmv5rCj5oyH5qiZ6Z2F54eI6Jmf6Zug5ZGo5ZCN54mpLmNzdg%3d%3d")
for cat in ("tw_macro", "wd_macro", "headline", "tw_stock"):
    probe("cnyes_" + cat, "https://api.cnyes.com/media/api/v1/newslist/category/%s?limit=30&startAt=1546300800&endAt=1546905600" % cat)
for q, nm in (("(taiwan OR taipei) (china OR beijing) (military OR invasion OR blockade OR drills)", "tw_cn_mil"),
              ("tariff (taiwan OR semiconductor)", "tariff"), ("federal reserve interest rate", "fed")):
    probe("gdelt_" + nm, "https://api.gdeltproject.org/api/v2/doc/doc?query=%s&mode=timelinevolraw&format=json&startdatetime=20170101000000&enddatetime=20261101000000"
          % urllib.request.quote(q))
    time.sleep(6)
json.dump(res, open("probe_result.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: (v["ok"], v.get("size"), v.get("err", "")[:80]) for k, v in res.items()}, ensure_ascii=False, indent=0))
