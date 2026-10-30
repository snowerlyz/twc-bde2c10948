# -*- coding: utf-8 -*-
"""模擬交易（模擬盤）：用證交所即時行情（每 5 秒的最佳五檔與成交量）模擬「下單 → 排隊 → 成交 → 結算」。

一、委託
  - 限價單（ROD 當日有效／IOC 立即成交否則取消）、市價單（以漲跌停價當作限價、立即成交否則取消）。
  - 現股（可放隔夜，短中長線）與現股當沖（可先買後賣、先賣後買，當天要沖銷）。
  - 觸價單：最新成交價碰到觸發價，才把委託送出（用來設停損、停利）。
  - 開盤前、收盤後下的單，排入下一次開盤（集合競價）。

二、怎麼成交（盡量貼近真實排隊）
  1. 送出時，價格已經碰到對手方（買價 ≥ 最佳賣價）：依五檔掛單由好到差吃單，數量以畫面上的掛單量為上限。
  2. 沒有成交的部分在自己的價位「排隊」：
     - 掛在五檔內已有的價位：排在目前所有掛單的後面，前面還有多少張＝當下畫面上這個價位的掛單量。
     - 比目前最佳買（賣）價更好：自己就是第一個，前面 0 張。
     - 比五檔還差：看不到前面有多少，只有價格「穿過」才成交。
  3. 之後每 5 秒的新行情：
     - 這段時間有成交、且成交價就是我的價位 → 這個價位前面的單被成交掉，我的排隊往前移（估計：成交量的一半在這個價位，
       若這個價位的掛單量減少更多，以減少的量為準）；掛單量減少但不是成交的部分視為有人取消，依比例算在我前面或後面。
     - 前面的量被吃完以後，再成交的量才輪到我。
     - 成交價跌破我的買價（或漲破我的賣價）、或對手方掛到我的價位 → 我的價位一定已經被吃光，全部成交。
  4. 開盤、收盤（集合競價）：買價高於開盤（收盤）價全部以開盤（收盤）價成交；剛好等於時照排隊規則。
  這是用公開的五檔與成交量「估計」排隊，看不到每一筆委託，所以是近似值。

三、結算（台灣規則）
  手續費 0.1425% × 折扣（預設 6 折，每筆最低 20 元）；賣出證交稅 0.3%，當沖 0.15%，ETF 0.1%。
  賣出（或當沖回補）時才結算已實現損益＝賣出金額 − 手續費 − 稅 − 買進成本（含買進手續費）。
  當沖：先買後賣沒賣掉的，收盤後轉為現股（要準備款項）；先賣後買沒買回的，以收盤價強制回補（模擬）。
  交割款項以「成交當下就扣、就入帳」簡化（實際是 T+2）。
"""
import datetime as dt
import http.cookiejar
import json
import math
import os
import ssl
import threading
import time
import urllib.request

from util import DATA, RESULTS, log, now_tw, read_json, write_json

PAPER_DIR = os.path.join(DATA, "paper")
STATE_PATH = os.path.join(PAPER_DIR, "state.json")
LOT = 1000
FEE = 0.001425
MIN_FEE = 20
TAX = 0.003
TAX_DT = 0.0015
TAX_ETF = 0.001
INIT_CASH = 1_000_000
POLL_SEC = 5
MIS = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=%s&json=1&delay=0&_=%d"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


# ====================================================================== 價格規則
def tick(p):
    if p < 10:
        return 0.01
    if p < 50:
        return 0.05
    if p < 100:
        return 0.1
    if p < 500:
        return 0.5
    if p < 1000:
        return 1.0
    return 5.0


def on_tick(p):
    t = tick(p)
    return abs(round(p / t) * t - p) < 1e-6


def fnum(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except Exception:
        return None


def parse(x):
    """證交所 MIS 一筆即時資料 → 統一格式。"""
    def levels(ps, ss):
        out = []
        for p, s in zip((ps or "").split("_"), (ss or "").split("_")):
            p, s = fnum(p), fnum(s)
            if p and s:
                out.append((round(p, 4), int(s)))
        return out
    last = fnum(x.get("z"))
    tr = x.get("trade") or {}
    if last is None and isinstance(tr, dict):
        last = fnum(tr.get("z"))
    return {
        "c": x.get("c"), "n": x.get("n"), "ex": x.get("ex"), "d": x.get("d"), "t": x.get("t") or x.get("%"),
        "ts": int(x.get("tlong") or 0), "last": last, "vol": int(fnum(x.get("v")) or 0),
        "o": fnum(x.get("o")), "h": fnum(x.get("h")), "l": fnum(x.get("l")), "ref": fnum(x.get("y")),
        "up": fnum(x.get("u")), "dn": fnum(x.get("w")),
        "bids": levels(x.get("b"), x.get("g")), "asks": levels(x.get("a"), x.get("f")),
    }


def phase(t):
    """依行情時間判斷盤別：pre 開盤前、open 盤中、close 收盤集合競價、done 收盤後。"""
    if not t:
        return "pre"
    if t < "09:00:00":
        return "pre"
    if t < "13:25:00":
        return "open"
    if t < "13:30:00":
        return "close"
    return "done"


# ====================================================================== 帳戶
class Paper:
    def __init__(self, path=STATE_PATH, clock=None):
        self.path = path
        self.clock = clock or now_tw
        self.lock = threading.RLock()
        self.q = {}           # 最新行情
        self.prev = {}        # 上一筆行情
        self.used = {}        # 同一筆行情中，自己的單已經吃掉的對手掛單量
        self.s = read_json(path, None) or self._new(INIT_CASH, 0.6)

    # ---------------------------------------------------------------- 基本
    def _new(self, cash, disc):
        return {"init": cash, "cash": cash, "disc": disc, "seq": 0, "orders": [], "pos": {}, "fills": [],
                "closed": [], "hist": [], "day": None, "created": self.clock().strftime("%Y-%m-%d %H:%M")}

    def save(self):
        write_json(self.path, self.s)

    def reset(self, cash=INIT_CASH, disc=0.6):
        with self.lock:
            self.s = self._new(int(cash), float(disc))
            self.save()

    def today(self):
        return self.clock().strftime("%Y%m%d")

    def now_s(self):
        return self.clock().strftime("%Y-%m-%d %H:%M:%S")

    def fee(self, amount, first=True):
        f = int(math.floor(amount * FEE * self.s["disc"]))
        return max(MIN_FEE, f) if first else f

    def reserved(self):
        r = 0.0
        for o in self.s["orders"]:
            if o["side"] == "B" and o["status"] in ("waiting", "pending", "queue", "partial") and not o.get("cover"):
                r += (o["qty"] - o["filled"]) * LOT * o["price"] * (1 + FEE * self.s["disc"]) + MIN_FEE
        return r

    def pending_sell(self, code):
        return sum(o["qty"] - o["filled"] for o in self.s["orders"]
                   if o["code"] == code and o["side"] == "S" and o["status"] in ("waiting", "pending", "queue", "partial"))

    # ---------------------------------------------------------------- 下單
    def place(self, req):
        """req: code, side(B/S), qty(張), price, kind(LMT/MKT), tif(ROD/IOC/FOK), dt(bool), tag, trigger, name"""
        with self.lock:
            code = str(req.get("code") or "").strip()
            side = req.get("side")
            qty = int(req.get("qty") or 0)
            kind = req.get("kind") or "LMT"
            tif = req.get("tif") or "ROD"
            dtf = bool(req.get("dt"))
            if side not in ("B", "S") or qty < 1 or qty > 499:
                raise ValueError("買賣別或張數不正確（1～499 張）")
            if not code.isalnum():
                raise ValueError("股票代號不正確")
            q = self.q.get(code)
            price = fnum(req.get("price"))
            if kind == "MKT":
                if not q or not (q["up"] and q["dn"]):
                    raise ValueError("還沒有這檔的即時行情，暫時不能下市價單")
                price = q["up"] if side == "B" else q["dn"]
                tif = "IOC"
            if kind in ("MOO", "MOC"):
                # 開盤價／收盤價成交：參加集合競價、一定成交；價格只用來預留款項（以漲跌停價估）
                if q and q["up"] and q["dn"]:
                    price = q["up"] if side == "B" else q["dn"]
                elif price:
                    price = _floor_tick(price * (1.1 if side == "B" else 0.9))
                tif = "ROD"
            if not price:
                raise ValueError("請輸入價格")
            if not on_tick(price):
                raise ValueError("價格不符合升降單位（%s 元的股票每次跳 %s 元）" % (price, tick(price)))
            if q and q["up"] and q["dn"] and not (q["dn"] - 1e-6 <= price <= q["up"] + 1e-6):
                raise ValueError("價格超出今天的漲跌停範圍（%s～%s）" % (q["dn"], q["up"]))
            pos = self.s["pos"].get(code) or {}
            have = pos.get("qty", 0)
            cover = side == "B" and have < 0
            if side == "B" and not cover:
                need = qty * LOT * price * (1 + FEE * self.s["disc"]) + MIN_FEE
                if need > self.s["cash"] - self.reserved() + 1e-6:
                    raise ValueError("可用現金不足（需要約 %s 元）" % format(int(need), ","))
            if side == "S":
                avail = max(0, have) - self.pending_sell(code)
                if qty * LOT > avail and not dtf:
                    raise ValueError("庫存不足：可賣 %d 張。沒有庫存要先賣，請勾選「當沖」（現股當沖先賣後買）" % (avail // LOT))
            trig = req.get("trigger") or None
            if trig:
                tp = fnum(trig.get("px"))
                if not tp or trig.get("dir") not in ("le", "ge"):
                    raise ValueError("觸價條件不正確")
                trig = {"px": tp, "dir": trig["dir"]}
            plan = req.get("plan") or None
            if plan:
                plan = {"h": int(plan.get("h") or 0), "exit": plan.get("exit") or "open", "hz": plan.get("hz")}
                if plan["h"] <= 0:
                    plan = None
            self.s["seq"] += 1
            o = {"id": self.s["seq"], "plan": plan, "code": code, "name": req.get("name") or (q or {}).get("n") or code,
                 "side": side, "qty": qty, "price": round(price, 4), "kind": kind, "tif": tif, "dt": dtf,
                 "tag": req.get("tag") or ("dt" if dtf else "free"), "cover": cover,
                 "status": "waiting" if trig else "pending", "trigger": trig, "filled": 0, "avg": None,
                 "ahead": None, "at": self.now_s(), "day": self.today(), "note": "", "fills": []}
            self.s["orders"].append(o)
            self._try_now(o)
            self.save()
            return o

    def cancel(self, oid):
        with self.lock:
            for o in self.s["orders"]:
                if o["id"] == oid and o["status"] in ("waiting", "pending", "queue", "partial"):
                    o["status"] = "cancelled" if o["filled"] == 0 else "partial_cancelled"
                    o["note"] = "已取消（%s）" % self.now_s()[11:19]
                    self.save()
                    return o
            raise ValueError("找不到可以取消的委託")

    def set_exit(self, code, stop=None, target=None):
        with self.lock:
            p = self.s["pos"].get(code)
            if not p:
                raise ValueError("沒有這檔庫存")
            p["stop"], p["target"] = fnum(stop), fnum(target)
            self.save()

    # ---------------------------------------------------------------- 撮合
    def _live(self, q):
        return q and q.get("d") == self.today()

    def _try_now(self, o):
        """剛送出的委託：盤中而且有最新行情時，先看能不能直接成交，剩下的開始排隊。"""
        q = self.q.get(o["code"])
        if o["status"] != "pending" or not self._live(q) or o.get("kind") in ("MOO", "MOC"):
            return
        ph = phase(q["t"])
        if ph != "open":
            return          # 開盤前、收盤集合競價、收盤後：等下一次撮合
        self._take(o, q)
        if o["filled"] < o["qty"]:
            if o["tif"] in ("IOC", "FOK"):
                self._kill(o)
            else:
                self._join(o, q)

    def _take(self, o, q):
        """吃對手方五檔掛單。"""
        opp = q["asks"] if o["side"] == "B" else q["bids"]
        rem = o["qty"] - o["filled"]
        plan = []
        for p, s in opp:
            if (o["side"] == "B" and p > o["price"] + 1e-6) or (o["side"] == "S" and p < o["price"] - 1e-6):
                break
            key = (o["code"], o["side"], p, q["ts"])
            avail = s - self.used.get(key, 0)
            if avail <= 0:
                continue
            n = min(rem, avail)
            plan.append((p, n, key))
            rem -= n
            if rem == 0:
                break
        if o["tif"] == "FOK" and rem > 0:
            return
        for p, n, key in plan:
            self.used[key] = self.used.get(key, 0) + n
            self._fill(o, p, n, "直接成交（吃掉對方掛在 %s 的單）" % _p(p))

    def _join(self, o, q):
        """開始排隊：前面有多少張。"""
        mine = q["bids"] if o["side"] == "B" else q["asks"]
        lv = dict(mine)
        best = mine[0][0] if mine else None
        if o["price"] in lv:
            o["ahead"] = lv[o["price"]]
        elif best is None or (o["side"] == "B" and o["price"] > best) or (o["side"] == "S" and o["price"] < best):
            o["ahead"] = 0
        else:
            o["ahead"] = None          # 比五檔還差，看不到前面有多少
        o["status"] = "queue" if o["filled"] == 0 else "partial"

    def _kill(self, o):
        o["status"] = "partial_cancelled" if o["filled"] else "cancelled"
        o["note"] = "IOC／市價：沒有立即成交的部分自動取消"

    def _step(self, o, q0, q1):
        """一筆排隊中的委託，從上一筆行情 q0 到這一筆 q1 之間的變化。"""
        P, B = o["price"], o["side"] == "B"
        rem = o["qty"] - o["filled"]
        if rem <= 0:
            return
        dv = max(0, q1["vol"] - q0["vol"]) if q0 else 0
        lp = q1["last"]
        mine = dict(q1["bids"] if B else q1["asks"])
        opp = q1["asks"] if B else q1["bids"]
        best_opp = opp[0][0] if opp else None
        # 1) 價格穿過我的價位 → 一定輪到我（價格優先）
        through = False
        if dv > 0 and lp is not None and ((B and lp < P - 1e-6) or (not B and lp > P + 1e-6)):
            through = True
        if q0 and q0.get("l") and q1.get("l") and B and q1["l"] < q0["l"] and q1["l"] < P - 1e-6:
            through = True
        if q0 and q0.get("h") and q1.get("h") and not B and q1["h"] > q0["h"] and q1["h"] > P + 1e-6:
            through = True
        if best_opp is not None and ((B and best_opp <= P + 1e-6) or (not B and best_opp >= P - 1e-6)):
            through = True
        if through:
            self._fill(o, P, rem, "價格穿過委託價，排到成交")
            return
        if P in mine:
            size_now = mine[P]
            size_prev = dict((q0["bids"] if B else q0["asks"]) if q0 else []).get(P)
            if o["ahead"] is None:
                o["ahead"] = size_now          # 剛出現在五檔內：排在所有人後面
                return
            traded = dv * 0.5 if (dv > 0 and lp is not None and abs(lp - P) < 1e-6) else 0.0
            if size_prev is not None and size_now < size_prev:
                dec = size_prev - size_now
                if traded > 0:
                    traded = max(traded, min(dec, dv))
                cancels = max(0.0, dec - traded)
                if size_prev > 0 and o["ahead"] > 0:
                    o["ahead"] -= cancels * (o["ahead"] / float(size_prev))
            o["ahead"] -= traded
            o["ahead"] = min(o["ahead"], size_now)
            if o["ahead"] < 0:
                n = min(rem, int(math.floor(-o["ahead"])) or 1)
                o["ahead"] = 0.0
                self._fill(o, P, n, "排隊排到，成交")
        elif o["ahead"] == 0 or (mine and ((B and P > max(mine)) or (not B and P < min(mine)))):
            # 我比所有人掛得好（自己是最佳價）：有人用更差的價成交，就會先成交到我
            o["ahead"] = 0.0
            if dv > 0 and lp is not None and ((B and lp <= P + 1e-6) or (not B and lp >= P - 1e-6)):
                n = min(rem, max(1, int(dv * 0.5)))
                self._fill(o, P, n, "掛在最佳價，排到成交")
        else:
            o["ahead"] = None

    def _auction(self, o, px, q1, label):
        """集合競價（開盤、收盤）：價格比成交價好就全部成交。"""
        P, B = o["price"], o["side"] == "B"
        rem = o["qty"] - o["filled"]
        if (B and P > px + 1e-6) or (not B and P < px - 1e-6):
            self._fill(o, px, rem, "%s集合競價成交" % label)
        elif abs(P - px) < 1e-6:
            o["ahead"] = dict(q1["bids"] if B else q1["asks"]).get(P, 0)
            o["status"] = "queue" if o["filled"] == 0 else "partial"
        else:
            self._join(o, q1)

    # ---------------------------------------------------------------- 成交與結算
    def _fill(self, o, px, n, why):
        if n <= 0:
            return
        code = o["code"]
        amt = px * n * LOT
        first = not o["fills"]
        fee = self.fee(amt, first)
        pos = self.s["pos"].setdefault(code, {"qty": 0, "cost": 0.0, "dt_qty": 0, "short_amt": 0.0, "name": o["name"],
                                              "open": self.today(), "tag": o["tag"], "stop": None, "target": None})
        pos["name"] = o["name"]
        tax = 0
        realized = None
        sh = n * LOT
        etf = code.startswith("00")
        if o["side"] == "B":
            self.s["cash"] -= amt + fee
            if pos["qty"] < 0:                                 # 當沖回補
                cov = min(sh, -pos["qty"])
                avg_short = pos["short_amt"] / (-pos["qty"])
                cost = px * cov + fee * cov / sh
                realized = avg_short * cov - cost
                pos["short_amt"] -= avg_short * cov
                pos["qty"] += cov
                self._close(o, pos, cov, avg_short, px, realized, fee * cov / sh, 0, "當沖回補")
                sh -= cov
            if sh > 0:
                if pos["qty"] == 0:
                    pos.update(open=self.today(), tag=o["tag"], cost=0.0)
                pos["qty"] += sh
                pos["cost"] += px * sh + fee * sh / (n * LOT)
                pos["today_qty"] = pos.get("today_qty", 0) + sh      # 今天買進的股數：今天賣掉就是當沖（證交稅 0.15%）
                if o["dt"]:
                    pos["dt_qty"] += sh
        else:
            if pos["qty"] > 0:
                sell = min(sh, pos["qty"])
                dt_part = min(sell, pos.get("today_qty", 0))
                rate_n = TAX_ETF if etf else TAX
                tax_s = int(math.floor(px * dt_part * TAX_DT + px * (sell - dt_part) * rate_n))
                avg = pos["cost"] / pos["qty"]
                fee_s = fee * sell / sh
                realized = px * sell - fee_s - tax_s - avg * sell
                pos["cost"] -= avg * sell
                pos["qty"] -= sell
                pos["today_qty"] = max(0, pos.get("today_qty", 0) - dt_part)
                pos["dt_qty"] = max(0, pos.get("dt_qty", 0) - sell)
                tax += tax_s
                self._close(o, pos, sell, avg, px, realized, fee_s, tax_s, "當沖賣出" if dt_part else "賣出")
                sh -= sell
            if sh > 0:                                          # 當沖先賣（放空）
                tax_s = int(math.floor(px * sh * TAX_DT))
                fee_s = fee * sh / (n * LOT)
                if pos["qty"] == 0:
                    pos.update(open=self.today(), tag=o["tag"])
                pos["qty"] -= sh
                pos["short_amt"] += px * sh - fee_s - tax_s
                tax += tax_s
            self.s["cash"] += amt - fee - tax
        if o.get("plan") and o["side"] == "B" and code in self.s["pos"] and self.s["pos"][code]["qty"] > 0:
            pl = o["plan"]
            self.s["pos"][code]["plan_exit"] = {"day": _add_weekdays(self.today(), pl["h"]), "h": pl["h"], "hz": pl.get("hz")}
            self.s["pos"][code]["tag"] = pl.get("hz") or self.s["pos"][code].get("tag")
        o["filled"] += n
        o["fills"].append({"t": self.now_s()[11:19], "px": px, "n": n})
        o["avg"] = round(sum(f["px"] * f["n"] for f in o["fills"]) / o["filled"], 4)
        o["status"] = "filled" if o["filled"] >= o["qty"] else "partial"
        o["note"] = why
        self.s["fills"].append({"id": o["id"], "code": code, "name": o["name"], "side": o["side"], "px": px, "n": n,
                                "fee": fee, "tax": tax, "at": self.now_s(), "dt": o["dt"], "why": why,
                                "realized": None if realized is None else round(realized)})
        self.s["fills"] = self.s["fills"][-500:]
        if pos["qty"] == 0:
            self.s["pos"].pop(code, None)

    def _close(self, o, pos, shares, avg, px, realized, fee, tax, kind):
        d0 = pos.get("open") or self.today()
        days = (dt.date(int(self.today()[:4]), int(self.today()[4:6]), int(self.today()[6:])) -
                dt.date(int(d0[:4]), int(d0[4:6]), int(d0[6:]))).days
        self.s["closed"].append({"code": o["code"], "name": o["name"], "kind": kind, "lots": shares / LOT, "cost": round(avg, 4),
                                 "px": px, "fee": round(fee), "tax": round(tax), "pnl": round(realized),
                                 "ret": round(realized / (avg * shares), 4) if avg else None, "days": days,
                                 "tag": pos.get("tag") or "free", "at": self.now_s()})

    # ---------------------------------------------------------------- 行情進來
    def on_quote(self, q):
        with self.lock:
            code = q["c"]
            q0 = self.q.get(code)
            if q0 and q0["ts"] == q["ts"] and q0["vol"] == q["vol"]:
                return False
            self.prev[code] = q0 if q0 and q0.get("d") == q.get("d") else None
            self.q[code] = q
            if not self._live(q):
                return False
            self._roll(q["d"])
            ph = phase(q["t"])
            q0 = self.prev[code]
            changed = False
            for o in self.s["orders"]:
                if o["code"] != code or o["status"] not in ("waiting", "pending", "queue", "partial"):
                    continue
                if o["status"] == "waiting":                      # 觸價單
                    lp = q["last"]
                    tr = o["trigger"]
                    if lp is not None and ((tr["dir"] == "le" and lp <= tr["px"] + 1e-6) or (tr["dir"] == "ge" and lp >= tr["px"] - 1e-6)):
                        o["status"] = "pending"
                        o["note"] = "觸價（%s）已送出" % _p(lp)
                        changed = True
                    else:
                        continue
                placed = o["at"][:10].replace("-", "")
                if o.get("kind") == "MOO":                    # 開盤價成交
                    if ph == "open" and not o.get("auct") and (placed < q["d"] or o["at"][11:] < "09:00:00") and q.get("o"):
                        o["auct"] = True
                        self._fill(o, q["o"], o["qty"] - o["filled"], "開盤集合競價，以開盤價成交")
                        changed = True
                    continue
                if o.get("kind") == "MOC":                    # 收盤價成交
                    if ph == "done" and not o.get("cauct") and (placed < q["d"] or o["at"][11:] < "13:30:00") and q["last"]:
                        o["cauct"] = True
                        self._fill(o, q["last"], o["qty"] - o["filled"], "收盤集合競價，以收盤價成交")
                        changed = True
                    continue
                if ph in ("pre", "close"):
                    continue                                  # 開盤前、收盤集合競價期間：等撮合
                pre_open = placed < q["d"] or o["at"][11:] < "09:00:00"
                if ph == "open":
                    if o["status"] == "pending":
                        if pre_open and not o.get("auct") and q.get("o"):
                            o["auct"] = True                  # 開盤前下的單：參加開盤集合競價
                            self._auction(o, q["o"], q, "開盤")
                        else:
                            self._take(o, q)
                            if o["filled"] < o["qty"]:
                                if o["tif"] in ("IOC", "FOK"):
                                    self._kill(o)
                                else:
                                    self._join(o, q)
                    else:
                        self._step(o, q0, q)
                    changed = True
                elif ph == "done" and not o.get("cauct") and (placed < q["d"] or o["at"][11:] < "13:30:00"):
                    o["cauct"] = True                         # 收盤集合競價
                    if q["last"]:
                        self._auction(o, q["last"], q, "收盤")
                    changed = True
            # 依計畫到期出場：到期那天以開盤價賣出（回測：到期開盤賣比收盤賣好）
            p = self.s["pos"].get(code)
            pe = (p or {}).get("plan_exit")
            if p and pe and p["qty"] > 0 and ph == "open" and q["d"] >= pe["day"] and q.get("o") and self.pending_sell(code) == 0:
                p.pop("plan_exit", None)
                try:
                    o = self.place({"code": code, "side": "S", "qty": int(p["qty"] // LOT), "kind": "MOO", "price": q["o"],
                                    "name": p.get("name"), "tag": p.get("tag")})
                    o["auct"] = True
                    late = q["t"] > "09:01:00"
                    self._fill(o, q["o"], o["qty"], "計畫到期，以開盤價賣出" + ("（程式開啟時已過開盤，以當天開盤價模擬）" if late else ""))
                    self.save()
                except Exception as e:
                    log("模擬交易計畫出場失敗：%s" % e)
            # 停損／停利（庫存設定的出場價）
            if p and ph == "open" and q["last"] and p["qty"] > 0:
                lp = q["last"]
                hit = None
                if p.get("stop") and lp <= p["stop"] + 1e-6:
                    hit = "停損"
                elif p.get("target") and lp >= p["target"] - 1e-6:
                    hit = "停利"
                if hit and self.pending_sell(code) == 0:
                    bid = q["bids"][0][0] if q["bids"] else lp
                    p["stop" if hit == "停損" else "target"] = None
                    try:
                        o = self.place({"code": code, "side": "S", "qty": int(p["qty"] // LOT), "price": bid, "tif": "ROD",
                                        "name": p.get("name"), "tag": p.get("tag")})
                        o["note"] = "%s觸發，以買價 %s 賣出" % (hit, _p(bid))
                    except Exception as e:
                        log("模擬交易%s失敗：%s" % (hit, e))
            if len(self.used) > 5000:
                self.used.clear()
            self.save()
            return changed

    def after_poll(self):
        """一輪行情處理完：收盤後做收盤作業（所有股票的收盤撮合都做完之後才做）。"""
        with self.lock:
            live = [q for q in self.q.values() if self._live(q)]
            if live and all(phase(q["t"]) == "done" for q in live):
                self._eod(live[0]["d"])
                self.save()

    def _roll(self, d):
        """換日：前一天沒處理完的收盤作業。"""
        if self.s.get("day") and self.s["day"] != d:
            self._eod(self.s["day"], force=True)
        self.s["day"] = d

    def _eod(self, d, force=False):
        """收盤作業：當日有效單失效、當沖未沖銷處理、記錄當天資產。"""
        if self.s.get("eod") == d:
            return
        for o in self.s["orders"]:
            placed = o["at"][:10].replace("-", "")
            cut = "09:00:00" if o.get("kind") == "MOO" else "13:30:00"     # 開盤價單：開盤後才下的，算明天的
            if o["status"] in ("queue", "partial", "pending") and (placed < d or (placed == d and o["at"][11:] < cut)):
                o["status"] = "expired" if o["filled"] == 0 else "partial_expired"
                o["note"] = "收盤未成交，委託失效（當日有效）"
        for code, p in list(self.s["pos"].items()):
            q = self.q.get(code) or {}
            px = q.get("last") or self._close_px(code)
            if p["qty"] < 0 and px:                             # 先賣沒買回 → 強制回補
                n = -p["qty"]
                o = {"id": 0, "code": code, "name": p.get("name") or code, "side": "B", "qty": n // LOT, "price": px,
                     "dt": True, "tag": p.get("tag") or "dt", "fills": [], "filled": 0}
                self._fill(o, px, n // LOT, "當沖未回補，以收盤價強制回補（模擬）")
            else:
                p["dt_qty"] = 0                                 # 先買沒賣掉 → 轉成現股
                p["today_qty"] = 0
        eq = self.equity()
        self.s["hist"] = [h for h in self.s["hist"] if h["d"] != d] + [{"d": d, "eq": round(eq["equity"]), "cash": round(self.s["cash"]),
                                                                       "mv": round(eq["mv"])}]
        self.s["eod"] = d

    def _close_px(self, code):
        st = (read_json(os.path.join(RESULTS, "latest.json"), {}) or {}).get("stocks") or []
        for r in st:
            if r.get("c") == code:
                return r.get("px")
        return None

    # ---------------------------------------------------------------- 報表
    def equity(self):
        mv = 0.0
        unreal = 0.0
        rows = []
        for code, p in self.s["pos"].items():
            q = self.q.get(code) or {}
            px = q.get("last") or (q.get("bids") or [[None]])[0][0] or self._close_px(code) or 0
            sh = p["qty"]
            if sh > 0:
                val = px * sh
                cost = p["cost"]
                # 未實現損益要扣掉賣出時的手續費與稅，才是「現在賣掉」真正拿到的
                sell_cost = val * (FEE * self.s["disc"] + (TAX_ETF if code.startswith("00") else TAX))
                u = val - sell_cost - cost
                mv += val
            else:
                val = px * sh
                cost = -p["short_amt"]
                u = p["short_amt"] - (-val) * (1 + FEE * self.s["disc"])
                mv += val
            unreal += u
            rows.append({"code": code, "name": p.get("name") or code, "lots": sh / LOT, "avg": round(abs(cost / sh), 4) if sh else None,
                         "px": px, "val": round(val), "unreal": round(u), "ret": round(u / abs(cost), 4) if cost else None,
                         "tag": p.get("tag"), "open": p.get("open"), "dt": bool(p.get("dt_qty")) or sh < 0,
                         "stop": p.get("stop"), "target": p.get("target"), "plan_exit": p.get("plan_exit")})
        return {"mv": mv, "unreal": unreal, "equity": self.s["cash"] + mv, "rows": rows}

    def view(self):
        with self.lock:
            eq = self.equity()
            closed = self.s["closed"]
            realized = sum(c["pnl"] for c in closed)
            today = self.today()
            t_real = sum(c["pnl"] for c in closed if c["at"][:10].replace("-", "") == today)
            by = {}
            for c in closed:
                b = by.setdefault(c["tag"], {"n": 0, "win": 0, "pnl": 0})
                b["n"] += 1
                b["win"] += 1 if c["pnl"] > 0 else 0
                b["pnl"] += c["pnl"]
            fees = sum(f["fee"] for f in self.s["fills"])
            taxes = sum(f["tax"] for f in self.s["fills"])
            act = [o for o in self.s["orders"] if o["status"] in ("waiting", "pending", "queue", "partial")]
            done = [o for o in self.s["orders"] if o not in act][-60:]
            quotes = {c: q for c, q in self.q.items() if c in {o["code"] for o in act} | set(self.s["pos"])}
            return {"init": self.s["init"], "cash": round(self.s["cash"]), "avail": round(self.s["cash"] - self.reserved()),
                    "disc": self.s["disc"], "equity": round(eq["equity"]), "mv": round(eq["mv"]), "unreal": round(eq["unreal"]),
                    "realized": round(realized), "today_realized": round(t_real), "fees": fees, "taxes": taxes,
                    "ret": round((eq["equity"] - self.s["init"]) / self.s["init"], 4),
                    "pos": eq["rows"], "orders": list(reversed(act)), "done": list(reversed(done)),
                    "closed": list(reversed(closed[-100:])), "by_tag": by, "hist": self.s["hist"][-250:],
                    "created": self.s.get("created"), "quotes": quotes}


def _floor_tick(p):
    t = tick(p)
    return round(math.floor(p / t + 1e-9) * t, 2)


def _add_weekdays(d, n):
    """從 d（YYYYMMDD）往後算 n 個平日（國定假日沒扣，實際交易日可能晚一兩天）。"""
    x = dt.date(int(d[:4]), int(d[4:6]), int(d[6:]))
    while n > 0:
        x += dt.timedelta(days=1)
        if x.weekday() < 5:
            n -= 1
    return x.strftime("%Y%m%d")


def _p(x):
    return ("%.2f" % x).rstrip("0").rstrip(".")


# ====================================================================== 即時行情
class Feed:
    """向證交所 MIS 抓即時五檔（每 5 秒），交給模擬帳戶撮合。"""

    def __init__(self, paper, markets=None):
        self.paper = paper
        self.markets = markets or {}
        self.watch = {}                 # 畫面上正在看的股票 → 最後一次被看的時間
        self.err = None
        self.last_ok = None
        ctx = ssl.create_default_context()
        try:
            ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        except Exception:
            pass
        self.op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx),
                                              urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.started = False

    def market_of(self, code):
        if not self.markets:
            st = (read_json(os.path.join(RESULTS, "latest.json"), {}) or {}).get("stocks") or []
            self.markets = {r["c"]: ("otc" if r.get("m") in ("上櫃", "櫃") else "tse") for r in st}
        return self.markets.get(code, "tse")

    def fetch(self, codes):
        codes = [c for c in codes if c and c.isalnum()]
        out = []
        for i in range(0, len(codes), 40):
            part = codes[i:i + 40]
            ex = "|".join("%s_%s.tw" % (self.market_of(c), c) for c in part)
            req = urllib.request.Request(MIS % (ex, int(time.time() * 1000)), headers={
                "User-Agent": UA, "Referer": "https://mis.twse.com.tw/stock/fibest.jsp", "Accept": "application/json"})
            with self.op.open(req, timeout=10) as r:
                j = json.loads(r.read().decode("utf-8"))
            out += [parse(x) for x in j.get("msgArray") or [] if x.get("c")]
        return out

    def codes(self):
        now = time.time()
        s = self.paper.s
        cs = {o["code"] for o in s["orders"] if o["status"] in ("waiting", "pending", "queue", "partial")} | set(s["pos"])
        cs |= {c for c, t in self.watch.items() if now - t < 90}
        return sorted(cs)

    def poll_once(self):
        cs = self.codes()
        if not cs:
            return 0
        try:
            qs = self.fetch(cs)
            for q in qs:
                self.paper.on_quote(q)
            self.paper.after_poll()
            self.err = None
            self.last_ok = now_tw().strftime("%H:%M:%S")
            return len(qs)
        except Exception as e:
            self.err = str(e)
            return 0

    def quote(self, code):
        """畫面要看某一檔的五檔：記下來，背景會持續更新；沒有最新的就馬上抓一次。"""
        self.watch[code] = time.time()
        q = self.paper.q.get(code)
        if not q or time.time() - q.get("_got", 0) > 20:
            try:
                for x in self.fetch([code]):
                    x["_got"] = time.time()
                    self.paper.on_quote(x)
            except Exception as e:
                self.err = str(e)
        return self.paper.q.get(code)

    def loop(self):
        while True:
            n = now_tw()
            t = n.strftime("%H:%M")
            active = n.weekday() < 5 and "08:29" <= t <= "13:36"
            if active:
                self.poll_once()
                time.sleep(POLL_SEC)
            else:
                # 收盤後：補做一次收盤作業（如果白天沒開著），之後每 5 分鐘看一次就好
                if n.weekday() < 5 and t > "13:36":
                    self.poll_once()
                time.sleep(300 if not self.watch else 30)

    def start(self):
        if not self.started:
            self.started = True
            threading.Thread(target=self.loop, daemon=True).start()
