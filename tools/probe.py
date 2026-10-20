# -*- coding: utf-8 -*-
"""連線測試：外資持股比率、集保股權分散表。結果存到 probe 分支。"""
import json, os, sys, time, urllib.request, ssl, gzip
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
ctx = ssl.create_default_context()
ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
def get(url, n=600):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            b = gzip.decompress(b)
        ct = r.headers.get("Content-Type", "")
        return r.status, ct, len(b), b
res = {}
def tryit(name, url, n=900, enc="utf-8"):
    try:
        st, ct, ln, b = get(url)
        try:
            txt = b.decode(enc)
        except Exception:
            txt = b.decode("cp950", errors="replace")
        res[name] = {"status": st, "ct": ct, "len": ln, "head": txt[:n]}
    except Exception as e:
        res[name] = {"err": repr(e)}
    time.sleep(3.5)
tryit("twse_qfiis", "https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS?date=20261020&selectType=ALLBUT0999&response=json", 1500)
tryit("twse_qfiis_old", "https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS?date=20251020&selectType=ALLBUT0999&response=json", 400)
tryit("tpex_qfii_www", "https://www.tpex.org.tw/www/zh-tw/insti/qfii?date=2026/10/20&response=json", 1500)
tryit("tpex_qfii_www2", "https://www.tpex.org.tw/www/zh-tw/insti/qfiiStat?date=2026/10/20&response=json", 800)
tryit("tpex_qfii_old", "https://www.tpex.org.tw/web/stock/3insti/qfii/qfii_result.php?l=zh-tw&o=json&d=115/10/20", 1500)
tryit("tpex_openapi_qfii", "https://www.tpex.org.tw/openapi/v1/tpex_3insti_qfii", 1200)
tryit("tpex_openapi_qfii2", "https://www.tpex.org.tw/openapi/v1/tpex_qfii_trading", 600)
tryit("tdcc_15", "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5", 1500)
tryit("tdcc_smart", "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5", 800)
json.dump(res, open("probe_result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
