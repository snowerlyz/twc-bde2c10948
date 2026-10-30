# -*- coding: utf-8 -*-
"""開一個本機伺服器測試模擬交易：即時行情用假的隨機走勢代替（不連證交所）。
用法：TWC_DATA=資料夾 python test/serve_paper_mock.py [port]"""
import datetime as dt
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import paper  # noqa: E402
import server  # noqa: E402

START = time.time()
BASE = dt.datetime.combine(dt.date.today(), dt.time(10, 0, 0))


def fake_now():
    return BASE + dt.timedelta(seconds=time.time() - START)


paper.now_tw = fake_now
server.now_tw = fake_now
paper.POLL_SEC = 2
STATE = {}
rnd = random.Random(7)


def sim(code):
    s = STATE.get(code)
    if not s:
        px = {"2330": 2365.0, "2317": 230.0}.get(code, 100.0)
        s = STATE[code] = {"px": px, "vol": 5000, "o": px, "h": px, "l": px, "ref": px}
    t = paper.tick(s["px"])
    s["px"] = round(s["px"] + rnd.choice([-1, 0, 0, 1]) * t, 2)
    s["vol"] += rnd.randint(5, 60)
    s["h"], s["l"] = max(s["h"], s["px"]), min(s["l"], s["px"])
    bid1 = s["px"] if rnd.random() < 0.5 else round(s["px"] - t, 2)
    bids = [(round(bid1 - i * t, 2), rnd.randint(5, 120)) for i in range(5)]
    asks = [(round(bid1 + (i + 1) * t, 2), rnd.randint(5, 120)) for i in range(5)]
    now = fake_now()
    return {"c": code, "n": {"2330": "台積電", "2317": "鴻海"}.get(code, code), "ex": "tse", "d": now.strftime("%Y%m%d"),
            "t": now.strftime("%H:%M:%S"), "ts": int(time.time() * 1000), "last": s["px"], "vol": s["vol"], "o": s["o"],
            "h": s["h"], "l": s["l"], "ref": s["ref"], "up": round(s["ref"] * 1.1, 0), "dn": round(s["ref"] * 0.9, 0),
            "bids": bids, "asks": asks}


paper.Feed.fetch = lambda self, codes: [sim(c) for c in codes]

if __name__ == "__main__":
    server.serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8790, lambda: None)
