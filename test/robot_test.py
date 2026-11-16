# -*- coding: utf-8 -*-
"""機器人模擬下單的單元測試（假行情，不連網）：python3 test/robot_test.py"""
import datetime as dt_
import os
import random
import sys
import tempfile

os.environ["TWC_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import robot  # noqa: E402

random.seed(1)
NDAY = 30
days = []
d = dt_.date(2026, 11, 2)
while len(days) < NDAY:
    if d.weekday() < 5:
        days.append(d.strftime("%Y%m%d"))
    d += dt_.timedelta(days=1)
codes = ["%04d" % (1101 + i) for i in range(20)]
raw = {}
for c in codes:
    px, o, cl, ref = 50.0, [], [], []
    for t in range(NDAY):
        ref.append(px)
        op = px * (1 + random.uniform(-0.02, 0.02))
        px = op * (1 + random.uniform(-0.03, 0.03))
        o.append(round(op, 2))
        cl.append(round(px, 2))
    raw[c] = {"o": o, "c": cl, "ref": ref}
raw["1101"]["o"][5] = round(raw["1101"]["ref"][5] * 1.1, 2)     # 第 5 天開盤漲停


class FD:
    pass


def make_D(T):
    D = FD()
    D.days, D.T = days[:T], T
    D.raw = {c: {k: v[:T] for k, v in s.items()} for c, s in raw.items()}
    D.mkt = {"taiex": [20000 + 10 * t for t in range(T)]}
    return D


def signals(T):
    rnd = random.Random(T)
    pk = rnd.sample(codes, 8)
    dt = {"long": [{"c": c, "n": "股" + c, "ok": True, "score": 60 - j, "win": 0.6, "avg": 0.002, "why": ["測試"]} for j, c in enumerate(pk[:3])],
          "short": [{"c": c, "n": "股" + c, "ok": j == 0, "score": 55, "win": 0.55, "avg": 0.001} for j, c in enumerate(pk[3:5])]}
    stocks = [{"c": c, "n": "股" + c, "ra": ("b" if c in pk[:6] else ("S" if c == pk[7] else "N")) + "NN"} for c in codes]
    res = {"_recs": {c: {"hs": {"short": {"pb": rnd.random()}}} for c in codes}}
    recs = {"h": {"short": {"timing": {"best": "close_open"}}}}
    return dt, stocks, res, recs


ok = True
for T in range(1, NDAY + 1):
    day = days[T - 1]
    late = T == 12
    hh = 8 if late else 18
    base = dt_.datetime.strptime(day, "%Y%m%d") + (dt_.timedelta(days=1) if late else dt_.timedelta(0))
    robot.now_tw = lambda base=base, hh=hh: base.replace(hour=hh, minute=30) if not (base.weekday() >= 5) else base.replace(hour=hh)
    if late:      # 模擬雲端延遲：第 12 天的資料到下一個交易日 10:30 才分析
        nxt = dt_.datetime.strptime(days[T], "%Y%m%d")
        robot.now_tw = lambda nxt=nxt: nxt.replace(hour=10, minute=30)
    D = make_D(T)
    dt, stocks, res, recs = signals(T)
    out = robot.run(D, res, stocks, dt, recs)
    if late and (out["acct"]["dt"]["pending"] or not out.get("plan_note")):
        print("雲端延遲到開盤後，不應產生當沖委託")
        ok = False
    if late and any(o["kind"] == "open" for o in out["acct"]["st"]["pending"]):
        print("雲端延遲到開盤後，不應產生開盤價委託")
        ok = False
    for _ in range(2):          # 同一天重跑多次：結果要一樣（不能重複撮合）
        out2 = robot.run(D, res, stocks, dt, recs)
        if out2["acct"]["st"]["stats"] != out["acct"]["st"]["stats"] or out2["acct"]["dt"]["stats"] != out["acct"]["dt"]["stats"]:
            print("重跑結果不同", day)
            ok = False

for k in ("dt", "st"):
    a = out["acct"][k]
    s = a["stats"]
    print(k, s)
    eq = s["cash"] + sum(p["qty"] * p["last"] for p in a["pos"])
    if abs(eq - s["equity"]) > 2:
        print("權益不一致", eq, s["equity"])
        ok = False
    if s["cash"] < -1:
        print("現金變負", s["cash"])
        ok = False
    st_ = [o["st"] for o in a["orders"]]
    print("  委託狀態：", {x: st_.count(x) for x in set(st_)})
    print("  持有", len(a["pos"]), "待送出", len(a["pending"]))
# 持有天數：短線每筆交易的買進日到賣出日相差 5 個交易日（提早賣出除外）
for tr in out["acct"]["st"]["trades"]:
    gap = days.index(tr["out_day"]) - days.index(tr["in_day"])
    if "到期" in tr["exit_why"] and gap != robot.ST_H:
        print("持有天數錯誤", tr)
        ok = False
    if "提早" in tr["exit_why"] and gap >= robot.ST_H:
        print("提早賣出天數錯誤", tr)
        ok = False
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
