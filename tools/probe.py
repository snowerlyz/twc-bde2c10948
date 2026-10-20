# -*- coding: utf-8 -*-
"""連線測試：實際跑一次消息面與國際市場的抓取，結果存到 probe 分支供檢查。"""
import json, os, shutil, sys, time
os.environ["TWC_DATA"] = os.path.abspath("probe_data")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import extra
from util import today_tw, ymd
t0 = time.time()
day = ymd(today_tw())
res = {}
try:
    g = extra.collect_global()
    res["global"] = {k: (len(v["s"]), sorted(v["s"])[-1]) for k, v in g.items() if k != "_at"}
except Exception as e:
    res["global_err"] = repr(e)
for d in sys.argv[1:] or [day]:
    try:
        n = extra.collect_news(d)
        res["news_" + d] = {"items": len(n["items"]), "mops": len(n["mops"]), "warn": len(n["warn"]), "disp": len(n["disp"]),
                            "sample": [(i["t"], i["sent"], i["codes"][:3]) for i in n["items"][:8]]}
    except Exception as e:
        res["news_err_" + d] = repr(e)
res["sec"] = round(time.time() - t0)
json.dump(res, open("probe_result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
