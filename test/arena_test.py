# -*- coding: utf-8 -*-
"""人格競賽的單元測試（假行情，不連網）：python3 test/arena_test.py"""
import datetime as dt_
import json
import os
import random
import sys
import tempfile
from collections import Counter

os.environ["TWC_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import arena  # noqa: E402
import robot  # noqa: E402

random.seed(2)
NDAY = 200
days = []
d = dt_.date(2026, 5, 4)
while len(days) < NDAY:
    if d.weekday() < 5:
        days.append(d.strftime("%Y%m%d"))
    d += dt_.timedelta(days=1)
codes = ["%04d" % (1101 + i) for i in range(60)]
raw = {}
for j, c in enumerate(codes):
    px, o, cl, ref, hi, lo, v, val = 50.0, [], [], [], [], [], [], []
    drift = 0.004 if j < 10 else (-0.004 if j < 20 else 0.0)
    for t in range(NDAY):
        ref.append(px)
        op = px * (1 + random.uniform(-0.02, 0.02))
        r = random.uniform(-0.05, 0.05) + drift
        if random.random() < 0.05:
            r = random.choice([0.08, -0.08, 0.1, -0.1])
        px = max(1.0, min(op * (1 + r), ref[-1] * 1.1, ))
        px = max(px, ref[-1] * 0.9)
        o.append(round(op, 2))
        cl.append(round(px, 2))
        hi.append(round(max(op, px) * (1 + random.uniform(0, 0.01)), 2))
        lo.append(round(min(op, px) * (1 - random.uniform(0, 0.01)), 2))
        q = random.uniform(1e6, 3e6) * (3 if abs(r) > 0.04 else 1)
        v.append(q)
        val.append(q * px)
    raw[c] = {"o": o, "c": cl, "ref": ref, "h": hi, "l": lo, "v": v, "val": val}


class FD:
    pass


def make_D(T):
    D = FD()
    D.days, D.T, D.codes = days[:T], T, codes
    D.names = {c: "股" + c for c in codes}
    D.raw = {c: {k: x[:T] for k, x in s.items()} for c, s in raw.items()}
    D.mkt = {"taiex": [20000 + 10 * t for t in range(T)]}
    return D


def signals(T):
    rnd = random.Random(T)
    pk = rnd.sample(codes, 8)
    dt = {"long": [{"c": c, "n": "股" + c, "ok": True, "win": 0.6 - 0.02 * j, "avg": 0.004, "score": 60} for j, c in enumerate(pk[:3])],
          "short": [{"c": c, "n": "股" + c, "ok": True, "win": 0.58, "avg": 0.005 - 0.001 * j, "score": 58} for j, c in enumerate(pk[3:8])]}
    stocks = [{"c": c, "n": "股" + c, "ra": rnd.choice("BbNN") + rnd.choice("bNs") + rnd.choice("BbNS"), "s": [50, 50, rnd.uniform(40, 90)]} for c in codes]
    res = {"_recs": {c: {"hs": {"short": {"pb": rnd.random()}}} for c in codes}}
    return dt, stocks, res


ok = True
for T in range(1, NDAY + 1):
    day = days[T - 1]
    base = dt_.datetime.strptime(day, "%Y%m%d")
    late = T == 70
    arena.now_tw = (lambda nxt=dt_.datetime.strptime(days[T], "%Y%m%d"): nxt.replace(hour=10, minute=30)) if late else \
        (lambda base=base: base.replace(hour=18, minute=30))
    D = make_D(T)
    dt, stocks, res = signals(T)
    A_all = [raw[c]["c"][:T] for c in codes]
    out = arena.run(D, res, stocks, dt, A_all)
    if late:
        for p in out["p"]:
            if p["kind"] == "dt" and p["pending"]:
                print("雲端延遲到開盤後，不應產生當沖委託", p["id"])
                ok = False
    out2 = arena.run(D, res, stocks, dt, A_all)
    if [p["stats"] for p in out2["p"]] != [p["stats"] for p in out["p"]]:
        print("重跑結果不同", day)
        ok = False

if os.path.exists(robot.PATH):
    print("人格競賽不應建立或改動機器人帳戶 robot.json")
    ok = False
st = json.load(open(arena.PATH))
for p in out["p"]:
    pp = arena.PBY[p["id"]]
    a = st["acct"][p["id"]]
    s = p["stats"]
    ins = Counter(tr["in_day"] for tr in a["trades"])
    print(p["name"], p["kind"], "筆數", s["n"], "報酬 %.2f%%" % (s["ret"] * 100), "每天最多", max(ins.values()) if ins else 0, "持有", len(a["pos"]))
    if ins and max(ins.values()) > pp["max"]:
        print("  一天成交超過上限", pp["max"])
        ok = False
    if s["n"] == 0:
        print("  測試資料應該要有交易")
        ok = False
    eq = s["cash"] + sum(x["qty"] * x["last"] for x in a["pos"])
    if abs(eq - s["equity"]) > 2 or s["cash"] < -1:
        print("  權益或現金不正確", eq, s["equity"], s["cash"])
        ok = False
    if pp["kind"] == "st":
        for tr in a["trades"]:
            gap = days.index(tr["out_day"]) - days.index(tr["in_day"])
            lt = days.index(tr["in_day"]) <= 69 <= days.index(tr["out_day"])     # 雲端延遲那天：賣單晚一天
            if "到期" in tr["exit_why"] and gap != pp["hold"] and not (lt and gap == pp["hold"] + 1):
                print("  持有天數錯誤", tr)
                ok = False
            if gap > pp["hold"] + 3:
                print("  持有太久", tr)
                ok = False
        why = Counter(tr["exit_why"].split("（")[0] for tr in a["trades"])
        print("  出場原因", dict(why))
for p in out["p"]:
    if len(p["rev"]) < 20:
        print("每週策略整理數量不對", p["name"], len(p["rev"]))
        ok = False
print("週記範例（%s %s）：" % (out["p"][4]["name"], out["p"][4]["rev"][0]["week"]))
for x in out["p"][4]["rev"][0]["lines"]:
    print("  ", x)
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
