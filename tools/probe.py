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
tryit("rev_sii_html", "https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_115_9_0.html", 1500, "big5")
tryit("rev_otc_html", "https://mopsov.twse.com.tw/nas/t21/otc/t21sc03_115_9_0.html", 800, "big5")
tryit("rev_sii_html_old", "https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_114_3_0.html", 600, "big5")
tryit("rev_mops_html", "https://mops.twse.com.tw/nas/t21/sii/t21sc03_115_9_0.html", 600, "big5")
def post(name, url, data, n=1500):
    try:
        import urllib.parse
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(url, data=body, headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded", "Referer": "https://mopsov.twse.com.tw/mops/web/t163sb04"})
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
            b = r.read()
            res[name] = {"status": r.status, "ct": r.headers.get("Content-Type"), "len": len(b), "head": b.decode("utf-8", errors="replace")[:n]}
    except Exception as e:
        res[name] = {"err": repr(e)}
    time.sleep(3.5)
post("eps_ov", "https://mopsov.twse.com.tw/mops/web/ajax_t163sb04", {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "isQuery": "Y", "TYPEK": "sii", "year": "115", "season": "02"})
post("eps_mops", "https://mops.twse.com.tw/mops/web/ajax_t163sb04", {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "isQuery": "Y", "TYPEK": "sii", "year": "115", "season": "02"})
tryit("eps_openapi_hist", "https://openapi.twse.com.tw/v1/opendata/t187ap14_L", 800)
json.dump(res, open("probe_result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
