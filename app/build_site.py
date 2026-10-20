# -*- coding: utf-8 -*-
"""把分析結果打包成純靜態網站（給 GitHub Pages 用，手機不用開電腦也能看）。

  python app/build_site.py <輸出資料夾>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import shutil
import time

from util import RESULTS, ROOT, now_tw, read_json

WEB = os.path.join(ROOT, "web")


def build(out):
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(WEB, out)
    api = os.path.join(out, "api")
    os.makedirs(os.path.join(api, "stock"), exist_ok=True)
    os.makedirs(os.path.join(api, "warrants"), exist_ok=True)
    for name in ("latest", "model", "futures", "warrant_picks", "daytrade", "tuning"):
        src = os.path.join(RESULTS, name + ".json")
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(api, name))
    for sub in ("stock", "warrants"):
        d = os.path.join(RESULTS, sub)
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".json"):
                    shutil.copyfile(os.path.join(d, f), os.path.join(api, sub, f[:-5]))
    latest = read_json(os.path.join(RESULTS, "latest.json"), {}) or {}
    status = {"static": True, "state": "idle", "running": False, "has_data": bool(latest),
              "latest_mtime": int(time.time()), "generated": latest.get("generated"),
              "lan": [], "now": now_tw().strftime("%Y-%m-%d %H:%M:%S")}
    with open(os.path.join(api, "status"), "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False)
    with open(os.path.join(api, "watchlist"), "w", encoding="utf-8") as f:
        f.write("[]")
    # 不讓搜尋引擎收錄
    with open(os.path.join(out, "robots.txt"), "w", encoding="utf-8") as f:
        f.write("User-agent: *\nDisallow: /\n")
    idx = os.path.join(out, "index.html")
    with open(idx, encoding="utf-8") as f:
        html = f.read()
    html = html.replace("<head>", '<head>\n<meta name="robots" content="noindex,nofollow,noarchive">', 1)
    with open(idx, "w", encoding="utf-8") as f:
        f.write(html)
    open(os.path.join(out, ".nojekyll"), "w").close()
    print("網站已輸出到", out)


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "_site"))
