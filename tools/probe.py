# -*- coding: utf-8 -*-
import json, os, time, urllib.request, urllib.parse, ssl
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
ctx = ssl.create_default_context(); ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
os.makedirs("probe_files", exist_ok=True)
def save(name, url, data=None):
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA, "Referer": "https://mopsov.twse.com.tw/mops/web/t163sb04"})
    with urllib.request.urlopen(req, timeout=90, context=ctx) as r:
        open("probe_files/" + name, "wb").write(r.read())
    time.sleep(3)
save("rev_sii.html", "https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_115_9_0.html")
save("eps_sii.html", "https://mopsov.twse.com.tw/mops/web/ajax_t163sb04", {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "isQuery": "Y", "TYPEK": "sii", "year": "115", "season": "02"})
save("eps_otc.html", "https://mopsov.twse.com.tw/mops/web/ajax_t163sb04", {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "isQuery": "Y", "TYPEK": "otc", "year": "114", "season": "04"})
json.dump({"ok": 1}, open("probe_result.json", "w"))
