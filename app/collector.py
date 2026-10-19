# -*- coding: utf-8 -*-
"""資料蒐集：從證交所、櫃買中心、期交所官方公開資料抓取並整理成精簡格式。

每個交易日拆成幾個「部分」各自存檔，中斷後可以接續：
  twse_px  上市日行情＋大盤指數＋漲跌家數
  twse_ch  上市三大法人
  twse_mg  上市融資融券
  tpex_px  上櫃日行情
  tpex_ch  上櫃三大法人
  tpex_mg  上櫃融資融券
  fut      期交所全部期貨日行情
另有按月抓的：txf_inst（台指期三大法人留倉）、pc（選擇權買賣權比）
以及只保留最新一份的快照：基本面、權證、個股期貨對照表。
"""
import calendar
import datetime as dt
import html
import os
import re
import threading
from html.parser import HTMLParser

from util import (DB, FetchError, fetch, fetch_json, log, num, read_json, sign_num,
                  roc_to_ymd, today_tw, now_tw, write_json, ymd, parse_ymd)

TWSE = "https://www.twse.com.tw/rwd/zh"
TWSE_OA = "https://openapi.twse.com.tw/v1"
TPEX = "https://www.tpex.org.tw/www/zh-tw"
TPEX_OA = "https://www.tpex.org.tw/openapi/v1"
TAIFEX = "https://www.taifex.com.tw/cht"

DAY_PARTS = ["twse_px", "tpex_px", "fut", "twse_ch", "tpex_ch", "twse_mg", "tpex_mg"]
PRICE_PARTS = {"twse_px", "tpex_px", "fut"}
CAL_PATH = os.path.join(DB, "calendar.json")


def part_path(part, d):
    return os.path.join(DB, "parts", part, d + ".json.gz")


def month_path(part, ym):
    return os.path.join(DB, "monthly", part, ym + ".json")


class NoData(Exception):
    """該日沒有資料（休市或尚未公布）"""


# ====================================================================== 解析器

def _fields(fields):
    return [re.sub(r"<[^>]+>", "", str(f)).strip() for f in fields]


def _idx(fields, *names, exact=True):
    for n in names:
        for i, f in enumerate(fields):
            if (f == n) if exact else (n in f):
                return i
    raise KeyError("找不到欄位 %s（現有：%s）" % (names, fields))


def parse_twse_px(j):
    if not j or j.get("stat") != "OK":
        raise NoData()
    px, names, mkt = {}, {}, {}
    stock_tab = None
    for t in j.get("tables", []):
        title = t.get("title") or ""
        fields = _fields(t.get("fields") or [])
        data = t.get("data") or []
        if "證券代號" in fields and "收盤價" in fields and data:
            stock_tab = (fields, data)
        elif "價格指數(臺灣證券交易所)" in title:
            for row in data:
                if str(row[0]).strip() == "發行量加權股價指數":
                    mkt["taiex"] = num(row[1])
                    mkt["taiex_chg"] = sign_num(row[2], row[3])
        elif "漲跌證券數合計" in title:
            ci = fields.index("股票") if "股票" in fields else 2
            for row in data:
                k = str(row[0])
                v = num(str(row[ci]).split("(")[0])
                if k.startswith("上漲"):
                    mkt["up"] = v
                elif k.startswith("下跌"):
                    mkt["down"] = v
                elif k.startswith("持平"):
                    mkt["flat"] = v
    if not stock_tab:
        raise NoData()
    fields, data = stock_tab
    ic, iname = _idx(fields, "證券代號"), _idx(fields, "證券名稱")
    io, ih, il, icl = (_idx(fields, "開盤價"), _idx(fields, "最高價"),
                       _idx(fields, "最低價"), _idx(fields, "收盤價"))
    iv, ival = _idx(fields, "成交股數"), _idx(fields, "成交金額")
    isg, idf = _idx(fields, "漲跌(+/-)"), _idx(fields, "漲跌價差")
    for r in data:
        code = str(r[ic]).strip()
        names[code] = str(r[iname]).strip()
        c = num(r[icl])
        chg = sign_num(r[isg], r[idf])
        px[code] = [num(r[io]), num(r[ih]), num(r[il]), c, num(r[iv]) or 0, num(r[ival]) or 0,
                    (c - chg) if (c is not None and chg is not None) else None]
    if len(px) < 100:
        raise NoData()
    return {"px": px, "names": names, "mkt": mkt}


def parse_twse_ch(j):
    if not j or j.get("stat") != "OK" or not j.get("data"):
        raise NoData()
    f = _fields(j["fields"])
    ic = _idx(f, "證券代號")
    i_fi = _idx(f, "外陸資買賣超股數(不含外資自營商)")
    i_fd = _idx(f, "外資自營商買賣超股數")
    i_it = _idx(f, "投信買賣超股數")
    i_dl = _idx(f, "自營商買賣超股數")
    ch = {}
    for r in j["data"]:
        code = str(r[ic]).strip()
        ch[code] = [(num(r[i_fi]) or 0) + (num(r[i_fd]) or 0), num(r[i_it]) or 0, num(r[i_dl]) or 0]
    return {"ch": ch}


def parse_twse_mg(j):
    if not j or j.get("stat") != "OK":
        raise NoData()
    mg, total = {}, {}
    for t in j.get("tables", []):
        f = _fields(t.get("fields") or [])
        data = t.get("data") or []
        if f and f[0] == "項目":
            for r in data:
                k = str(r[0])
                if k.startswith("融資(交易單位)"):
                    total["mb"] = num(r[5])
                elif k.startswith("融券(交易單位)"):
                    total["sb"] = num(r[5])
                elif k.startswith("融資金額"):
                    total["mamt"] = num(r[5])
        elif f and f[0] == "代號" and len(f) >= 13 and data:
            for r in data:
                mg[str(r[0]).strip()] = [num(r[6]) or 0, num(r[12]) or 0]
    if len(mg) < 100:
        raise NoData()
    return {"mg": mg, "total": total}


def parse_tpex_px(j):
    tabs = (j or {}).get("tables") or []
    if not tabs or not tabs[0].get("data"):
        raise NoData()
    f = _fields(tabs[0]["fields"])
    ic, iname = _idx(f, "代號"), _idx(f, "名稱")
    icl, io, ih, il = _idx(f, "收盤"), _idx(f, "開盤"), _idx(f, "最高"), _idx(f, "最低")
    iv, ival = _idx(f, "成交股數"), _idx(f, "成交金額(元)")
    ichg = _idx(f, "漲跌")
    ish = _idx(f, "發行股數")
    px, names, shares = {}, {}, {}
    for r in tabs[0]["data"]:
        code = str(r[ic]).strip()
        names[code] = str(r[iname]).strip()
        c = num(r[icl])
        chg = num(r[ichg])
        px[code] = [num(r[io]), num(r[ih]), num(r[il]), c, num(r[iv]) or 0, num(r[ival]) or 0,
                    (c - chg) if (c is not None and chg is not None) else None]
        shares[code] = num(r[ish])
    if len(px) < 100:
        raise NoData()
    return {"px": px, "names": names, "shares": shares}


def parse_tpex_ch(j):
    tabs = (j or {}).get("tables") or []
    if not tabs or not tabs[0].get("data"):
        raise NoData()
    ch = {}
    for r in tabs[0]["data"]:
        if len(r) < 24:
            continue
        ch[str(r[0]).strip()] = [num(r[10]) or 0, num(r[13]) or 0, num(r[22]) or 0]
    if len(ch) < 50:
        raise NoData()
    return {"ch": ch}


def parse_tpex_mg(j):
    tabs = (j or {}).get("tables") or []
    if not tabs or not tabs[0].get("data"):
        raise NoData()
    mg = {}
    for r in tabs[0]["data"]:
        if len(r) < 15:
            continue
        mg[str(r[0]).strip()] = [num(r[6]) or 0, num(r[14]) or 0]
    if len(mg) < 50:
        raise NoData()
    return {"mg": mg}


def _csv_rows(text):
    rows = []
    for line in text.replace("\r", "").split("\n"):
        line = line.strip()
        if not line:
            continue
        rows.append([c.strip() for c in line.split(",")])
    return rows


def parse_fut(text):
    t = text.lstrip()
    if t.startswith("<"):
        raise FetchError("期交所回傳網頁而非資料")
    rows = _csv_rows(text)
    if len(rows) < 2:
        raise NoData()
    head = rows[0]
    i_ses = head.index("交易時段") if "交易時段" in head else 17
    out = {}
    for r in rows[1:]:
        if len(r) < 12 or r[i_ses] != "一般":
            continue
        cid, month = r[1].strip(), r[2].strip()
        if not re.fullmatch(r"\d{6}", month):
            continue
        rec = [month, num(r[3]), num(r[4]), num(r[5]), num(r[6]), num(r[9]) or 0, num(r[10]), num(r[11])]
        out.setdefault(cid, []).append(rec)
    if not out:
        raise NoData()
    return {"fut": out}


def parse_txf_inst(text):
    rows = _csv_rows(text)
    out = {}
    who = {"自營商": "dealer", "投信": "trust", "外資及陸資": "foreign", "外資": "foreign"}
    for r in rows[1:]:
        if len(r) < 14:
            continue
        d = r[0].replace("/", "")
        k = who.get(r[2])
        if not k or not re.fullmatch(r"\d{8}", d):
            continue
        out.setdefault(d, {})[k] = [num(r[7]) or 0, num(r[13]) or 0]  # 當日淨口數、未平倉淨口數
    return out


def parse_pc(text):
    rows = _csv_rows(text)
    out = {}
    for r in rows[1:]:
        if len(r) < 7:
            continue
        d = r[0].replace("/", "")
        if re.fullmatch(r"\d{8}", d):
            out[d] = [num(x) for x in r[1:7]]
    return out


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell, self._in = [], None, [], False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._in, self._cell = True, []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._in:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._in = False
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._in:
            self._cell.append(data)


def parse_stock_futures(text):
    p = _TableParser()
    p.feed(text)
    out = {}
    for r in p.rows:
        if len(r) >= 5 and re.fullmatch(r"[A-Z0-9]{2,3}", r[0]) and re.fullmatch(r"\w{4,6}", r[2]):
            if "股票期貨" in r[4]:
                out[r[0] + "F"] = {"stock": r[2], "name": r[3]}
    return out


# ====================================================================== 抓取

def _tpex_date(d):
    return "%s/%s/%s" % (d[:4], d[4:6], d[6:])


def fetch_part(part, d):
    if part == "twse_px":
        return parse_twse_px(fetch_json("%s/afterTrading/MI_INDEX?date=%s&type=ALLBUT0999&response=json" % (TWSE, d)))
    if part == "twse_ch":
        return parse_twse_ch(fetch_json("%s/fund/T86?date=%s&selectType=ALLBUT0999&response=json" % (TWSE, d)))
    if part == "twse_mg":
        return parse_twse_mg(fetch_json("%s/marginTrading/MI_MARGN?date=%s&selectType=ALL&response=json" % (TWSE, d)))
    td = _tpex_date(d).replace("/", "%2F")
    if part == "tpex_px":
        return parse_tpex_px(fetch_json("%s/afterTrading/otc?date=%s&type=EW&id=&response=json" % (TPEX, td)))
    if part == "tpex_ch":
        return parse_tpex_ch(fetch_json("%s/insti/dailyTrade?type=Daily&sect=EW&date=%s&id=&response=json" % (TPEX, td)))
    if part == "tpex_mg":
        return parse_tpex_mg(fetch_json("%s/margin/balance?date=%s&id=&response=json" % (TPEX, td)))
    if part == "fut":
        dd = _tpex_date(d)
        return parse_fut(fetch(TAIFEX + "/3/futDataDown", data={
            "down_type": "1", "commodity_id": "all", "commodity_id2": "",
            "queryStartDate": dd, "queryEndDate": dd}, encoding="cp950"))
    raise ValueError(part)


def fetch_month(part, ym):
    y, m = int(ym[:4]), int(ym[4:])
    start = "%04d/%02d/01" % (y, m)
    last = dt.date(y, m, calendar.monthrange(y, m)[1])
    last = min(last, today_tw())
    end = last.strftime("%Y/%m/%d")
    if part == "txf_inst":
        return parse_txf_inst(fetch(TAIFEX + "/3/futContractsDateDown", data={
            "queryStartDate": start, "queryEndDate": end, "commodityId": "TXF"}, encoding="cp950"))
    if part == "pc":
        return parse_pc(fetch(TAIFEX + "/3/pcRatioDown", data={
            "queryStartDate": start, "queryEndDate": end}, encoding="cp950"))
    raise ValueError(part)


# ====================================================================== 交易日曆

def load_calendar():
    c = read_json(CAL_PATH, {}) or {}
    c.setdefault("closed", [])
    c.setdefault("trading", [])
    return c


def save_calendar(c):
    c["closed"] = sorted(set(c["closed"]))
    c["trading"] = sorted(set(c["trading"]))
    write_json(CAL_PATH, c)


def candidate_days(n_days, cal):
    """往回找 n_days 個可能的交易日（週一到週五，排除已知休市日）。"""
    closed = set(cal["closed"])
    d = today_tw()
    # 下午 2 點前今天的收盤資料還沒出來
    if now_tw().hour < 14:
        d -= dt.timedelta(days=1)
    out = []
    guard = 0
    while len(out) < n_days and guard < n_days * 2 + 60:
        guard += 1
        s = ymd(d)
        if d.weekday() < 5 and s not in closed:
            out.append(s)
        d -= dt.timedelta(days=1)
    return out


# ====================================================================== 主流程

class Progress:
    def __init__(self, cb=None):
        self.cb = cb
        self.lock = threading.Lock()
        self.state = {"phase": "", "done": 0, "total": 0, "msg": "", "errors": []}

    def set(self, **kw):
        with self.lock:
            self.state.update(kw)
            s = dict(self.state)
        if self.cb:
            self.cb(s)

    def step(self, msg=None):
        with self.lock:
            self.state["done"] += 1
            if msg:
                self.state["msg"] = msg
            s = dict(self.state)
        if self.cb:
            self.cb(s)

    def error(self, msg):
        log("錯誤：" + msg)
        with self.lock:
            self.state["errors"] = (self.state["errors"] + [msg])[-20:]


def _need(part, d):
    return not os.path.exists(part_path(part, d))


def collect_days(days, parts, prog, cal):
    """依網站分組平行抓取（證交所、櫃買、期交所各一條線），每條線內依序並遵守限速。"""
    groups = {
        "twse": [p for p in parts if p.startswith("twse")],
        "tpex": [p for p in parts if p.startswith("tpex")],
        "taifex": [p for p in parts if p == "fut"],
    }
    today = ymd(today_tw())
    cal_lock = threading.Lock()
    closed_new = set()
    written = [0]

    def worker(group_parts):
        fails, total_fails = 0, 0
        for d in days:
            if d in closed_new:
                continue
            for p in group_parts:
                if not _need(p, d):
                    continue
                if d in closed_new:
                    break
                if total_fails > 25:
                    break
                try:
                    res = fetch_part(p, d)
                    write_json(part_path(p, d), res, gz=True)
                    with cal_lock:
                        written[0] += 1
                    fails = 0
                    if p == "twse_px":
                        with cal_lock:
                            cal["trading"].append(d)
                except NoData:
                    fails = 0
                    # 證交所日行情沒資料＝休市（今天且時間還早則視為尚未公布）
                    if p == "twse_px" and (d < today or now_tw().hour >= 17):
                        with cal_lock:
                            closed_new.add(d)
                            cal["closed"].append(d)
                except Exception as e:
                    fails += 1
                    total_fails += 1
                    prog.error("%s %s：%s" % (p, d, e))
                    if fails >= 4:
                        # 連續失敗多半是被網站暫時限流，休息一下再繼續
                        prog.set(msg="資料來源回應異常，暫停 90 秒後重試")
                        import time as _t
                        _t.sleep(90)
                        fails = 0
                prog.step("%s %s" % (p, d))
            if total_fails > 25:
                prog.error("%s 失敗次數過多，本次先停止這個來源，下次更新會自動接續" % group_parts[0].split("_")[0])
                break

    total = sum(1 for d in days for p in parts if _need(p, d))
    prog.set(done=0, total=max(total, 1))
    threads = [threading.Thread(target=worker, args=(g,), daemon=True) for g in groups.values() if g]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with cal_lock:
        save_calendar(cal)
    return written[0]


def collect_months(days, prog):
    months = sorted(set(d[:6] for d in days))
    cur = ymd(today_tw())[:6]
    for ym in months:
        for part in ("txf_inst", "pc"):
            path = month_path(part, ym)
            if os.path.exists(path) and ym != cur:
                old = read_json(path, {})
                # 月份已過且資料完整就不重抓
                if old:
                    continue
            try:
                write_json(path, fetch_month(part, ym))
            except Exception as e:
                prog.error("%s %s：%s" % (part, ym, e))


# ---------------------------------------------------------------- 快照（只保留最新）

def _oa(url):
    try:
        j = fetch_json(url)
        return j if isinstance(j, list) else []
    except Exception as e:
        log("快照抓取失敗 %s：%s" % (url, e))
        return []


def collect_snapshot(latest_day, prog):
    snap_dir = os.path.join(DB, "snapshot")
    info = read_json(os.path.join(snap_dir, "info.json"), {}) or {}
    if info.get("day") == latest_day and info.get("complete"):
        return
    prog.set(phase="snapshot", msg="抓取基本面與權證資料")
    complete = True

    # --- 基本面：本益比、殖利率、淨值比
    fund = {}
    try:
        j = fetch_json("%s/afterTrading/BWIBBU_d?date=%s&selectType=ALL&response=json" % (TWSE, latest_day))
        f = _fields(j.get("fields") or [])
        if j.get("data"):
            ic, iy, ipe, ipb = (_idx(f, "證券代號"), _idx(f, "殖利率(%)"), _idx(f, "本益比"), _idx(f, "股價淨值比"))
            for r in j["data"]:
                fund.setdefault(str(r[ic]).strip(), {}).update(
                    pe=num(r[ipe]), yld=num(r[iy]), pb=num(r[ipb]))
    except Exception as e:
        complete = False
        prog.error("上市本益比：%s" % e)
    for r in _oa(TPEX_OA + "/tpex_mainboard_peratio_analysis"):
        fund.setdefault(str(r.get("SecuritiesCompanyCode", "")).strip(), {}).update(
            pe=num(r.get("PriceEarningRatio")), yld=num(r.get("YieldRatio")), pb=num(r.get("PriceBookRatio")))

    # --- 月營收
    industry = {}
    for url in (TWSE_OA + "/opendata/t187ap05_L", TPEX_OA + "/mopsfin_t187ap05_O"):
        rows = _oa(url)
        if not rows:
            complete = False
        for r in rows:
            code = str(r.get("公司代號", "")).strip()
            if not code:
                continue
            industry[code] = (r.get("產業別") or "").strip()
            fund.setdefault(code, {}).update(
                rev_ym=r.get("資料年月"),
                rev=num(r.get("營業收入-當月營收")),
                rev_yoy=num(r.get("營業收入-去年同月增減(%)")),
                rev_mom=num(r.get("營業收入-上月比較增減(%)")),
                rev_cum_yoy=num(r.get("累計營業收入-前期比較增減(%)")))

    # --- 獲利能力（上市）
    for r in _oa(TWSE_OA + "/opendata/t187ap17_L"):
        code = str(r.get("公司代號", "")).strip()
        g = {}
        for k, v in r.items():
            if k.startswith("毛利率"):
                g["gm"] = num(v)
            elif k.startswith("營業利益率"):
                g["om"] = num(v)
            elif k.startswith("稅後純益率"):
                g["nm"] = num(v)
        g["q"] = "%s/Q%s" % (r.get("年度"), r.get("季別"))
        fund.setdefault(code, {}).update(g)

    # --- EPS（上市、上櫃各產業別報表）
    eps_urls = [TWSE_OA + "/opendata/t187ap06_L_" + s for s in ("ci", "basi", "bd", "fh", "ins", "mim")]
    eps_urls += [TPEX_OA + "/mopsfin_t187ap06_O_" + s for s in ("ci", "basi", "bd", "fh", "ins", "mim")]
    for url in eps_urls:
        for r in _oa(url):
            code = str(r.get("公司代號") or r.get("SecuritiesCompanyCode") or "").strip()
            if not code:
                continue
            eps = None
            for k, v in r.items():
                if "每股盈餘" in k:
                    eps = num(v)
            yr = r.get("年度") or r.get("Year")
            qt = r.get("季別") or r.get("Season")
            f = fund.setdefault(code, {})
            if eps is not None:
                f.update(eps=eps, eps_q="%s/Q%s" % (yr, qt))
            # 由損益表補算毛利率、營業利益率（上櫃公司沒有營益分析表）
            rev = num(r.get("營業收入"))
            if rev and rev > 0:
                op = num(r.get("營業利益（損失）"))
                gp = num(r.get("營業毛利（毛損）淨額")) or num(r.get("營業毛利（毛損）"))
                if f.get("om") is None and op is not None:
                    f["om"] = round(op / rev * 100, 2)
                if f.get("gm") is None and gp is not None:
                    f["gm"] = round(gp / rev * 100, 2)
                f.setdefault("q", "%s/Q%s" % (yr, qt))

    write_json(os.path.join(snap_dir, "fund.json"), fund)
    # 每天留一份，日後模型就能用歷史資料檢驗基本面因子的效果
    write_json(part_path("fund", latest_day), fund, gz=True)
    write_json(os.path.join(snap_dir, "industry.json"), industry)

    # --- 個股期貨對照
    try:
        sf = parse_stock_futures(fetch(TAIFEX + "/2/stockLists"))
        if sf:
            write_json(os.path.join(snap_dir, "stockfut.json"), sf)
    except Exception as e:
        prog.error("個股期貨清單：%s" % e)

    # --- 權證
    prog.set(msg="抓取權證條款與行情（資料量較大）")
    try:
        collect_warrants(latest_day, snap_dir)
    except Exception as e:
        complete = False
        prog.error("權證：%s" % e)

    write_json(os.path.join(snap_dir, "info.json"), {"day": latest_day, "complete": complete,
                                                      "at": now_tw().strftime("%Y-%m-%d %H:%M")})


def collect_warrants(d, snap_dir):
    # 條款
    terms = {}
    for url in (TWSE_OA + "/opendata/t187ap37_L", TPEX_OA + "/mopsfin_t187ap37_O"):
        for r in _oa(url):
            code = str(r.get("權證代號", "")).strip()
            if not code:
                continue
            last = roc_to_ymd(r.get("最後交易日", ""))
            if not last or last < d:
                continue
            ratio = num(r.get("最新標的履約配發數量(每仟單位權證)"))
            terms[code] = {
                "n": r.get("權證簡稱", "").strip(),
                "t": "C" if "購" in (r.get("權證類型") or "") else "P",
                "cat": (r.get("類別") or "").strip(),
                "un": (r.get("標的證券/指數") or "").strip(),
                "k": num(r.get("最新履約價格(元)/履約指數")),
                "r": (ratio / 1000.0) if ratio else None,
                "last": last,
                "iss": num(r.get("發行單位數量(仟單位)")),
                "lp": (r.get("流動量提供者報價方式") or "").strip(),
            }
    # 行情：上市認購、認售
    quotes = {}
    for typ in ("0999", "0999P"):
        try:
            j = fetch_json("%s/afterTrading/MI_INDEX?date=%s&type=%s&response=json" % (TWSE, d, typ), timeout=120)
        except Exception as e:
            log("上市權證行情 %s：%s" % (typ, e))
            continue
        for t in j.get("tables", []):
            f = _fields(t.get("fields") or [])
            if "證券代號" not in f or "標的代號" not in f:
                continue
            ic, icl, ib, ia, iv = (_idx(f, "證券代號"), _idx(f, "收盤價"), _idx(f, "最後揭示買價"),
                                   _idx(f, "最後揭示賣價"), _idx(f, "成交股數"))
            iu, ius = _idx(f, "標的代號"), _idx(f, "標的收盤價/指數")
            for r in t.get("data") or []:
                quotes[str(r[ic]).strip()] = {"c": num(r[icl]), "b": num(r[ib]), "a": num(r[ia]),
                                              "v": num(r[iv]) or 0, "u": str(r[iu]).strip(), "s": num(r[ius])}
    # 上櫃權證行情（含買賣價）
    under = {}
    for r in _oa(TPEX_OA + "/tpex_warrant_daily_quts"):
        under[str(r.get("Code", "")).strip()] = (str(r.get("UnderlyingStockCode", "")).strip(),
                                                 num(r.get("UnderlyingStockClosePrice")))
    try:
        j = fetch_json("%s/afterTrading/dailyQuotes?date=%s&id=&response=json" % (TPEX, _tpex_date(d).replace("/", "%2F")), timeout=120)
        tab = (j.get("tables") or [{}])[0]
        f = _fields(tab.get("fields") or [])
        ic, icl, ib, ia, iv, iref = (_idx(f, "代號"), _idx(f, "收盤"), _idx(f, "最後買價"),
                                     _idx(f, "最後賣價"), _idx(f, "成交股數"), _idx(f, "次日 參考價", "次日參考價"))
        for r in tab.get("data") or []:
            code = str(r[ic]).strip()
            if len(code) != 6 or code not in under:
                continue
            u, us = under[code]
            quotes[code] = {"c": num(r[icl]) or num(r[iref]), "b": num(r[ib]), "a": num(r[ia]),
                            "v": num(r[iv]) or 0, "u": u, "s": us}
    except Exception as e:
        log("上櫃權證行情：%s" % e)

    out = {}
    for code, t in terms.items():
        q = quotes.get(code)
        if not q:
            continue
        t = dict(t)
        t.update(q)
        out[code] = t
    write_json(os.path.join(snap_dir, "warrants.json.gz"), {"day": d, "w": out}, gz=True)
    log("權證：條款 %d 檔、行情 %d 檔、合併 %d 檔" % (len(terms), len(quotes), len(out)))


def run_collect(prog, total_days=250, chip_days=120, quick_days=70, on_stage=None):
    """抓取資料。先抓最近 quick_days 天（讓工具能盡快可用），再往回補到 total_days 天。"""
    cal = load_calendar()
    days_all = candidate_days(total_days, cal)
    days_quick = days_all[:quick_days]
    prog.set(phase="collect", msg="抓取最近 %d 個交易日" % len(days_quick))
    changed = collect_days(days_quick, DAY_PARTS, prog, cal)
    cal = load_calendar()
    latest = max([d for d in days_quick if os.path.exists(part_path("twse_px", d))], default=None)
    collect_months(days_all, prog)
    if latest:
        collect_snapshot(latest, prog)
    if on_stage:
        on_stage("quick", changed)
    older = [d for d in days_all[quick_days:] if d not in set(cal["closed"])]
    if older:
        prog.set(phase="backfill", msg="補齊較早的歷史資料（%d 天）" % len(older))
        chip_set = set(days_all[:chip_days])
        n1 = collect_days([d for d in older if d in chip_set], DAY_PARTS, prog, cal)
        n2 = collect_days([d for d in older if d not in chip_set], list(PRICE_PARTS), prog, load_calendar())
        if on_stage and (n1 + n2) > 0:
            on_stage("full", n1 + n2)
    return latest
