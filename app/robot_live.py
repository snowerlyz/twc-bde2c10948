# -*- coding: utf-8 -*-
"""機器人模擬下單：盤中即時觀察（2026-11-19，使用者要求「盤中就能觀察買賣情況」）。

只做「試算」，不改動正式帳戶（db/robot.json）：
- 讀正式帳戶狀態的複本，用當天的即時行情（開盤價、目前最高／最低價、目前成交價）
  套用和收盤後正式結算「完全相同」的撮合規則（robot._settle_dt／_settle_st），
  算出「到目前為止」哪些委託已成交、哪些還在等、帳戶現在值多少。
- 收盤價的委託（短線收盤買進、當沖收盤買回／賣出）在 13:30 前用目前價格試算，標示「等收盤」。
- 正式成交與損益仍以收盤後的日線結算為準（集合競價價格可能和盤中看到的不同）。

用法：
  雲端：python app/robot_live.py <robot.json 路徑> <輸出檔>      （.github/workflows/intraday.yml 每 2 分鐘跑一次）
  電腦版：server.py 的 /api/robot_live 直接呼叫 snapshot()。
"""
import copy
import datetime as dt
import http.cookiejar
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import robot as R  # noqa: E402

NAN = float("nan")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
MIS = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=%s&json=1&delay=0&_=%d"
YAHOO = "https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.stockList;fields=avgPrice%2Corderbook;symbols="


def now_tw():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=8)


def _f(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except Exception:
        return None


# ====================================================================== 即時行情（雲端用；電腦版改用 paper.Feed）
class Quotes:
    def __init__(self):
        ctx = ssl.create_default_context()
        self.op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx),
                                              urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.src = None
        self.err = None

    def _get(self, url, ref):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": ref, "Accept": "application/json"})
        with self.op.open(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))

    def mis(self, codes, mkt):
        out = {}
        for i in range(0, len(codes), 30):
            part = codes[i:i + 30]
            ex = []
            for c in part:     # 不知道上市或上櫃時兩個都查（查不到的不會回傳）
                m = mkt.get(c)
                ex += ["%s_%s.tw" % (m, c)] if m else ["tse_%s.tw" % c, "otc_%s.tw" % c]
            j = self._get(MIS % ("|".join(ex), int(time.time() * 1000)), "https://mis.twse.com.tw/stock/fibest.jsp")
            for x in j.get("msgArray") or []:
                c = x.get("c")
                if not c:
                    continue
                last = _f(x.get("z")) or _f((x.get("trade") or {}).get("z") if isinstance(x.get("trade"), dict) else None)
                if last is None:      # 盤中暫時沒有成交價：用最佳買賣價的中間
                    b = _f((x.get("b") or "").split("_")[0])
                    a = _f((x.get("a") or "").split("_")[0])
                    last = (a + b) / 2 if a and b else (a or b)
                out[c] = {"o": _f(x.get("o")), "h": _f(x.get("h")), "l": _f(x.get("l")), "last": last,
                          "ref": _f(x.get("y")), "d": x.get("d"), "t": x.get("t")}
        return out

    def yahoo(self, codes, mkt):
        out = {}
        syms = []
        for c in codes:
            m = mkt.get(c)
            syms += ["%s.%s" % (c, "TWO" if m == "otc" else "TW")] if m else ["%s.TW" % c, "%s.TWO" % c]
        for i in range(0, len(syms), 30):
            j = self._get(YAHOO + urllib.parse.quote(",".join(syms[i:i + 30]), safe=".") + "&_=%d" % int(time.time() * 1000),
                          "https://tw.stock.yahoo.com/")
            for x in j if isinstance(j, list) else []:
                raw = lambda k: _f((x.get(k) or {}).get("raw")) if isinstance(x.get(k), dict) else _f(x.get(k))
                c = (x.get("symbol") or "").split(".")[0]
                if not c or raw("price") is None:
                    continue
                tm = x.get("regularMarketTime") or ""
                try:
                    u = dt.datetime.strptime(tm[:19], "%Y-%m-%dT%H:%M:%S") + dt.timedelta(hours=8)
                    d, t = u.strftime("%Y%m%d"), u.strftime("%H:%M:%S")
                except Exception:
                    d = t = None
                out[c] = {"o": raw("regularMarketOpen"), "h": raw("regularMarketDayHigh"), "l": raw("regularMarketDayLow"),
                          "last": raw("price"), "ref": raw("regularMarketPreviousClose"), "d": d, "t": t}
        return out

    def fetch(self, codes, mkt):
        codes = sorted({c for c in codes if c and c.isalnum()})
        if not codes:
            return {}
        self.err = None
        try:
            q = self.mis(codes, mkt)
            if q:
                self.src = "證交所（約 1 分鐘更新）"
                return q
        except Exception as e:
            self.err = "證交所：%s" % e
        try:
            q = self.yahoo(codes, mkt)
            if q:
                self.src = "Yahoo 奇摩股市"
                return q
        except Exception as e:
            self.err = (self.err + "；" if self.err else "") + "Yahoo：%s" % e
        return {}


# ====================================================================== 試算
class _D:
    """給 robot 撮合函式用的「只有今天一天」的行情。"""

    def __init__(self, day, quotes):
        self.days = [day]
        self.T = 1
        self.raw = {}
        for c, q in quotes.items():
            g = lambda k: NAN if q.get(k) is None else q[k]
            self.raw[c] = {"o": [g("o")], "h": [g("h")], "l": [g("l")], "c": [g("last")], "ref": [g("ref")]}


def codes_of(st):
    cs = set()
    for a in (st.get("acct") or {}).values():
        cs |= {o["c"] for o in a.get("pending") or []}
        cs |= {p["c"] for p in a.get("pos") or []}
    return sorted(cs)


def _phase(hm):
    if hm < "09:00":
        return "pre", "開盤前：委託已排好，09:00 開盤後開始撮合"
    if hm < "13:30":
        return "open", "盤中：依目前行情試算（每 1～2 分鐘更新）"
    return "closed", "已收盤：用收盤價試算，正式結算在傍晚資料更新後"


def snapshot(st, quotes, now=None, src=None, err=None, taiex=None):
    """正式帳戶狀態 st（不會被修改）＋即時行情 → 盤中觀察用的資料。"""
    now = now or now_tw()
    today, hm = now.strftime("%Y%m%d"), now.strftime("%H:%M")
    ph, ph_txt = _phase(hm)
    out = {"gen": now.strftime("%Y-%m-%d %H:%M:%S"), "day": today, "official": st.get("last"), "phase": ph, "phase_txt": ph_txt,
           "src": src, "err": err, "taiex": taiex, "acct": {}}
    qd = {q.get("d") for q in quotes.values() if q.get("d")}
    if st.get("last") and st["last"] >= today:
        out.update(phase="done", phase_txt="今天已正式結算，請看下方的正式紀錄")
        return out
    if now.weekday() >= 5 or (ph != "pre" and qd and today not in qd):
        out.update(phase="holiday", phase_txt="今天沒有開盤")
        return out
    started = ph != "pre"
    # 還沒成交過的股票（開盤前、暫停交易）不放進行情：撮合會當作「還沒有成交價」
    qs = {c: q for c, q in quotes.items() if started and q.get("o") and q.get("last") and (not q.get("d") or q["d"] == today)}
    D = _D(today, qs)
    for k, a0 in (st.get("acct") or {}).items():
        a = copy.deepcopy(a0)
        n_ord, n_tr = len(a["orders"]), len(a["trades"])
        eq0 = a["eq"][-1][1] if a.get("eq") else a["init"]
        pend0 = list(a.get("pending") or [])
        if started:
            (R._settle_dt if k == "dt" else R._settle_st)(a, D, 0)
        new_o = a["orders"][n_ord:] if started else []
        new_t = a["trades"][n_tr:] if started else []
        rows = []
        seen = set()
        for o in new_o:
            q = qs.get(o["c"]) or quotes.get(o["c"]) or {}
            stx, kind = o["st"], "done"
            if o["st"] == "成交" and o["kind"] == "close" and ph == "open":
                stx, kind = "等收盤（13:30 用收盤價成交；目前價格試算）", "wait"
            elif ph == "open" and "盤中也沒有漲回平盤" in o["st"]:
                stx, kind = "掛平盤價等待中（開低，盤中漲回平盤以上才成交）", "wait"
            elif ph == "open" and "盤中價格沒到限價" in o["st"]:
                stx, kind = "主單沒成交，已改下這檔備選，等價格到限價", "wait"
            elif ph == "open" and "收盤漲停" in o["st"]:
                stx, kind = "目前漲停（收盤仍漲停就買不到，改買備選）", "wait"
            elif o["st"] == "沒有成交（當天沒有交易）" or o["st"] == "沒有成交（查不到行情）":
                stx, kind = "還沒有成交價", "wait"
            elif o["st"] != "成交":
                kind = "miss"
            seen.add(o["id"])
            rows.append({"c": o["c"], "n": o["n"], "act": o.get("act") or ("買進" if o["side"] == "B" else ("先賣" if k == "dt" and o["kind"] == "open" else "賣出")),
                         "role": o.get("role"), "kind": o["kind"], "st": stx, "k": kind, "px": o.get("px"), "qty": o.get("qty"),
                         "at": o.get("at"), "now": q.get("last"), "ref": q.get("ref"), "o": q.get("o"), "t": q.get("t")})
        for o in pend0:          # 還沒輪到的（開盤前全部；盤中是用不到的備選、收盤才處理的）
            if o["id"] in seen or any(r["c"] == o["c"] and r["role"] == o.get("role") for r in rows):
                continue
            q = quotes.get(o["c"]) or {}
            if not started:
                stx = "等開盤（09:00 用開盤價）" if o["kind"] == "open" else "等收盤（13:30 用收盤價）"
            elif o.get("role") == "backup":
                mains = [r for r in rows if r["role"] == "main" and r["kind"] == "open"]
                if ph == "open" and k == "dt" and any(r["role"] == "backup" for r in rows):
                    stx = "備選：順位較後，今天用不到"
                elif ph == "open" and k == "dt" and any(r["k"] == "wait" and r["px"] is None for r in mains):
                    stx = "備選：主單開盤沒成交時依序改下"
                elif o["kind"] == "close" and ph == "open":
                    stx = "備選：收盤時主單漲停買不到才改買"
                else:
                    stx = "備選：主單都有成交，不用下單"
            else:
                stx = "等待中"
            rows.append({"c": o["c"], "n": o["n"], "act": "買進" if o["side"] == "B" else ("先賣" if k == "dt" else "賣出"),
                         "role": o.get("role"), "kind": o["kind"], "st": stx, "k": "wait" if o.get("role") != "backup" or not started else "skip",
                         "px": None, "qty": None, "at": None, "now": q.get("last"), "ref": q.get("ref"), "o": q.get("o"), "t": q.get("t")})
        # 帳戶現值：庫存用目前價格
        for p in a["pos"]:
            q = quotes.get(p["c"]) or {}
            if q.get("last") and (not q.get("d") or q["d"] == today):
                p["last"] = q["last"]
        eqv = a["cash"] + sum(p["qty"] * p["last"] for p in a["pos"])
        pos = []
        for p in a["pos"]:
            q = quotes.get(p["c"]) or {}
            mv = p["qty"] * p["last"]
            net = mv - R.fee(mv) - int(mv * (R.TAX_ETF if R.is_etf(p["c"]) else R.TAX))
            pos.append({"c": p["c"], "n": p["n"], "qty": p["qty"], "px": p["px"], "now": p["last"], "ref": q.get("ref"),
                        "upnl": round(net - p["cost"]), "uret": round(net / p["cost"] - 1, 5), "new": p["day"] == today,
                        "left": max(0, p["left"])})
        out["acct"][k] = {"eq": round(eqv), "eq0": round(eq0), "pnl": round(eqv - eq0), "init": a["init"],
                          "ret": round(eqv / a["init"] - 1, 5), "orders": rows,
                          "trades": [{x: t.get(x) for x in ("c", "n", "dir", "in_px", "out_px", "qty", "pnl", "ret", "in_at")} for t in new_t],
                          "pos": pos}
    return out


def market_map(st, latest_path=None):
    m = dict(st.get("mkt") or {})
    if latest_path and os.path.exists(latest_path):
        try:
            with open(latest_path, encoding="utf-8") as f:
                for r in (json.load(f) or {}).get("stocks") or []:
                    m[r["c"]] = "otc" if r.get("m") in ("上櫃", "櫃") else "tse"
        except Exception:
            pass
    return m


def main(state_path, out_path):
    with open(state_path, encoding="utf-8") as f:
        st = json.load(f)
    qf = Quotes()
    cs = codes_of(st)
    quotes = qf.fetch(cs, market_map(st))
    taiex = None
    try:
        j = qf._get(MIS % ("tse_t00.tw", int(time.time() * 1000)), "https://mis.twse.com.tw/stock/fibest.jsp")
        x = (j.get("msgArray") or [{}])[0]
        z, y = _f(x.get("z")), _f(x.get("y"))
        if z and y:
            taiex = {"now": z, "ref": y, "chg": round(z / y - 1, 5), "t": x.get("t")}
    except Exception:
        pass
    snap = snapshot(st, quotes, src=qf.src, err=qf.err if not quotes and cs else None, taiex=taiex)
    snap["n_quotes"], snap["n_codes"] = len(quotes), len(cs)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, out_path)
    print(snap["gen"], snap["phase"], "行情 %d/%d 檔" % (len(quotes), len(cs)), qf.src or "", qf.err or "")
    return snap


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
