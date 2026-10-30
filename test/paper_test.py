# -*- coding: utf-8 -*-
"""模擬交易撮合的單元測試（用假的行情序列）。執行：python test/paper_test.py"""
import datetime as dt
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ.setdefault("TWC_DATA", tempfile.mkdtemp())
import paper  # noqa: E402

T0 = dt.datetime(2026, 10, 30, 9, 0, 0)


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t


def snap(t, last, vol, bids, asks, o=100.0, h=101.0, l=99.0, code="1234", d="20261030"):
    return {"c": code, "n": "測試", "ex": "tse", "d": d, "t": t, "ts": int(t.replace(":", "")) + int(d) * 1000000, "last": last,
            "vol": vol, "o": o, "h": h, "l": l, "ref": 100.0, "up": 110.0, "dn": 90.0, "bids": bids, "asks": asks}


def mk():
    c = Clock()
    p = paper.Paper(path=os.path.join(tempfile.mkdtemp(), "s.json"), clock=c)
    p.reset(1_000_000, 0.6)
    return p, c


def test_queue_fill():
    p, c = mk()
    c.t = T0.replace(hour=9, minute=30)
    p.on_quote(snap("09:30:00", 100.5, 1000, [(100.0, 50), (99.5, 80)], [(100.5, 30), (101.0, 60)]))
    o = p.place({"code": "1234", "side": "B", "qty": 5, "price": 100.0})
    assert o["status"] == "queue" and o["ahead"] == 50, o
    # 有 40 張在 100 成交，100 的掛單從 50 減到 10（含我後面新進來的 0）
    p.on_quote(snap("09:30:05", 100.0, 1040, [(100.0, 10), (99.5, 80)], [(100.5, 30), (101.0, 60)]))
    assert o["filled"] == 0 and 9 <= o["ahead"] <= 10, o["ahead"]
    # 又成交 30 張在 100：前面 10 張吃完，再輪到我 5 張
    p.on_quote(snap("09:30:10", 100.0, 1070, [(100.0, 3), (99.5, 80)], [(100.5, 30), (101.0, 60)]))
    assert o["status"] == "filled", o
    assert p.s["pos"]["1234"]["qty"] == 5000
    print("排隊成交 OK", o["note"])


def test_take_and_settle():
    p, c = mk()
    c.t = T0.replace(hour=10)
    p.on_quote(snap("10:00:00", 100.5, 1000, [(100.0, 50)], [(100.5, 3), (101.0, 60)]))
    o = p.place({"code": "1234", "side": "B", "qty": 5, "price": 101.0})
    assert o["status"] == "filled" and abs(o["avg"] - (100.5 * 3 + 101 * 2) / 5) < 1e-9, o
    cash_after_buy = p.s["cash"]
    amt = 100.5 * 3000 + 101 * 2000
    fee = max(20, int(100.5 * 3000 * 0.001425 * 0.6)) + int(101 * 2000 * 0.001425 * 0.6)
    assert abs((1_000_000 - cash_after_buy) - (amt + fee)) < 1, (cash_after_buy, amt, fee)
    # 隔天賣出：吃買方 102
    c.t = dt.datetime(2026, 11, 2, 10, 0)
    p.on_quote(snap("10:00:00", 102.0, 500, [(102.0, 100)], [(102.5, 10)], d="20261102"))
    s = p.place({"code": "1234", "side": "S", "qty": 5, "price": 102.0})
    assert s["status"] == "filled"
    cl = p.s["closed"][-1]
    sell_amt = 102 * 5000
    exp = sell_amt - max(20, int(sell_amt * 0.001425 * 0.6)) - int(sell_amt * 0.003) - (amt + fee)
    assert abs(cl["pnl"] - exp) <= 2, (cl, exp)
    assert "1234" not in p.s["pos"]
    print("吃單與結算 OK：已實現", cl["pnl"], "持有", cl["days"], "天")


def test_through_and_hidden():
    p, c = mk()
    c.t = T0.replace(hour=11)
    p.on_quote(snap("11:00:00", 100.0, 1000, [(100.0, 50), (99.5, 80), (99.0, 10), (98.5, 10), (98.0, 10)], [(100.5, 30)]))
    o = p.place({"code": "1234", "side": "B", "qty": 2, "price": 97.5})
    assert o["ahead"] is None
    p.on_quote(snap("11:00:05", 98.0, 1100, [(98.0, 5)], [(98.5, 30)], l=98.0))
    assert o["filled"] == 0
    p.on_quote(snap("11:00:10", 97.0, 1200, [(97.0, 5)], [(97.5, 30)], l=97.0))
    assert o["status"] == "filled" and o["avg"] == 97.5
    print("價格穿過成交 OK")


def test_daytrade_short_and_eod():
    p, c = mk()
    c.t = T0.replace(hour=9, minute=5)
    p.on_quote(snap("09:05:00", 100.0, 1000, [(100.0, 50)], [(100.5, 30)]))
    try:
        p.place({"code": "1234", "side": "S", "qty": 2, "price": 100.0})
        raise AssertionError("沒庫存不應該能賣")
    except ValueError:
        pass
    o = p.place({"code": "1234", "side": "S", "qty": 2, "price": 100.0, "dt": True})
    assert o["status"] == "filled" and p.s["pos"]["1234"]["qty"] == -2000
    # 收盤 101，沒回補 → 強制回補
    c.t = T0.replace(hour=13, minute=31)
    p.on_quote(snap("13:30:00", 101.0, 2000, [(101.0, 5)], [(101.5, 5)]))
    p.after_poll()
    assert "1234" not in p.s["pos"], p.s["pos"]
    cl = p.s["closed"][-1]
    assert cl["pnl"] < 0 and cl["kind"] == "當沖回補"
    print("當沖先賣、收盤強制回補 OK：", cl["pnl"])


def test_preopen_auction_and_expiry():
    p, c = mk()
    c.t = T0.replace(hour=8, minute=40)
    p.on_quote(snap("08:40:00", None, 0, [(99.0, 5)], [(101.0, 5)]))
    o1 = p.place({"code": "1234", "side": "B", "qty": 1, "price": 101.0, "name": "測試"})
    o2 = p.place({"code": "1234", "side": "B", "qty": 1, "price": 98.0})
    assert o1["status"] == "pending"
    c.t = T0.replace(hour=9, minute=0, second=5)
    p.on_quote(snap("09:00:05", 100.0, 300, [(99.5, 20)], [(100.0, 20)], o=100.0))
    assert o1["status"] == "filled" and o1["avg"] == 100.0, o1
    assert o2["status"] in ("queue",), o2
    c.t = T0.replace(hour=13, minute=31)
    p.on_quote(snap("13:30:00", 100.0, 900, [(99.5, 20)], [(100.0, 20)]))
    p.after_poll()
    assert o2["status"] == "expired", o2
    print("開盤集合競價、當日有效失效 OK")


def test_trigger_stop():
    p, c = mk()
    c.t = T0.replace(hour=9, minute=10)
    p.on_quote(snap("09:10:00", 100.0, 1000, [(100.0, 50)], [(100.5, 30)]))
    p.place({"code": "1234", "side": "B", "qty": 1, "price": 100.5})
    o = p.place({"code": "1234", "side": "S", "qty": 1, "price": 97.0, "trigger": {"px": 97.5, "dir": "le"}})
    assert o["status"] == "waiting"
    p.on_quote(snap("09:10:05", 98.0, 1100, [(98.0, 50)], [(98.5, 30)]))
    assert o["status"] == "waiting"
    p.on_quote(snap("09:10:10", 97.5, 1200, [(97.5, 50)], [(98.0, 30)]))
    assert o["status"] == "filled" and o["avg"] == 97.5, o
    print("觸價停損 OK：", p.s["closed"][-1]["pnl"])


if __name__ == "__main__":
    for f in (test_queue_fill, test_take_and_settle, test_through_and_hidden, test_daytrade_short_and_eod,
              test_preopen_auction_and_expiry, test_trigger_stop):
        f()
    print("全部通過")
