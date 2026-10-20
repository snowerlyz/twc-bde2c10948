# -*- coding: utf-8 -*-
"""以官方格式產生模擬資料，用來在沒有網路的環境測試整條流程。"""
import datetime as dt
import json
import math
import random
import re
import urllib.parse

random.seed(7)
TODAY = dt.date(2026, 10, 19)
HOLI = {dt.date(2026, 10, 9), dt.date(2026, 9, 25), dt.date(2026, 6, 19)}
days = []
d = TODAY - dt.timedelta(days=420)
while d <= TODAY:
    if d.weekday() < 5 and d not in HOLI:
        days.append(d)
    d += dt.timedelta(days=1)
DI = {x.strftime("%Y%m%d"): i for i, x in enumerate(days)}
T = len(days)

import os
N_TW, N_OTC = int(os.environ.get("MOCK_TW", 320)), int(os.environ.get("MOCK_OTC", 220))
stocks = []
for k in range(N_TW + N_OTC):
    code = str(1000 + k * 3) if k < N_TW else str(5000 + (k - N_TW) * 4)
    stocks.append({"code": code, "name": "測試%s" % code, "mk": "TW" if k < N_TW else "OTC",
                   "ind": random.choice(["半導體業", "電子零組件業", "金融保險業", "航運業", "生技醫療業", "鋼鐵工業"])})
stocks.append({"code": "0050", "name": "元大台灣50", "mk": "TW", "ind": ""})
stocks.append({"code": "00679B", "name": "元大美債20年", "mk": "OTC", "ind": ""})
mkt_ret = [random.gauss(0.0004, 0.011) for _ in range(T)]
taiex = [20000.0]
for r in mkt_ret[1:]:
    taiex.append(taiex[-1] * (1 + r))
for s in stocks:
    p = random.uniform(15, 600)
    beta = random.uniform(0.6, 1.4)
    path, fi, it, mb = [], [], [], []
    alpha_state = 0.0
    shares = random.randint(50, 3000) * 1e6
    vol_base = shares * random.uniform(0.002, 0.01)
    m = random.randint(5000, 50000)
    for t in range(T):
        # 外資買超是隱藏訊號：今天買，未來幾天偏漲
        flow = random.gauss(0, 1)
        alpha_state = 0.8 * alpha_state + 0.2 * flow
        r = beta * mkt_ret[t] + 0.004 * alpha_state + random.gauss(0, 0.018)
        r = max(-0.095, min(0.095, r))
        p = p * (1 + r) if t else p
        exdiv = (t % 250 == 180 and random.random() < 0.5)
        path.append((p, exdiv))
        fi.append(flow * vol_base * 0.1)
        it.append(random.gauss(0.2 * flow, 1) * vol_base * 0.03)
        m = max(0, m + int(random.gauss(0, 300)))
        mb.append(m)
    # 除息：價格跳空下跌 3%，參考價也一併調低
    closes, refs = [], []
    adj = 1.0
    for t, (pp, ex) in enumerate(path):
        if ex:
            adj *= 0.97
        c = round(pp * adj, 2)
        closes.append(c)
    for t in range(T):
        if t == 0:
            refs.append(closes[0])
        else:
            prev = closes[t - 1]
            refs.append(round(prev * 0.97, 2) if path[t][1] else prev)
    s.update(c=closes, ref=refs, fi=fi, it=it, mb=mb, vol=vol_base, shares=shares)


def _fmt(x, d=2):
    return ("{:,.%df}" % d).format(x)


def _ohlc(s, t):
    c = s["c"][t]
    ref = s["ref"][t]
    o = round(ref * (1 + random.gauss(0, 0.004)), 2)
    h = round(max(o, c) * (1 + abs(random.gauss(0, 0.006))), 2)
    l = round(min(o, c) * (1 - abs(random.gauss(0, 0.006))), 2)
    v = int(s["vol"] * random.uniform(0.5, 1.6))
    return o, h, l, c, v, int(v * c), c - ref


def twse_mi(date):
    t = DI.get(date)
    if t is None:
        return {"stat": "很抱歉，沒有符合條件的資料!"}
    rows = []
    for s in stocks:
        if s["mk"] != "TW":
            continue
        o, h, l, c, v, val, chg = _ohlc(s, t)
        sign = "<p style= color:red>+</p>" if chg >= 0 else "<p style= color:green>-</p>"
        rows.append([s["code"], s["name"], _fmt(v, 0), "100", _fmt(val, 0), _fmt(o), _fmt(h), _fmt(l), _fmt(c), sign,
                     _fmt(abs(chg)), _fmt(c), "10", _fmt(c), "10", "12.3"])
    tx = taiex[t]
    ch = tx - taiex[t - 1] if t else 0
    return {"stat": "OK", "tables": [
        {"title": "價格指數(臺灣證券交易所)", "fields": ["指數", "收盤指數", "漲跌(+/-)", "漲跌點數", "漲跌百分比(%)", "特殊處理註記"],
         "data": [["寶島股價指數", _fmt(tx * 1.1), "+", "1", "0.1", ""],
                  ["發行量加權股價指數", _fmt(tx), "<p style ='color:%s'>%s</p>" % ("red" if ch >= 0 else "green", "+" if ch >= 0 else "-"), _fmt(abs(ch)), "0.3", ""]]},
        {"title": "漲跌證券數合計", "fields": ["類型", "整體市場", "股票"],
         "data": [["上漲(漲停)", "9,016(68)", "%d(5)" % random.randint(200, 700)], ["下跌(跌停)", "1(1)", "%d(3)" % random.randint(200, 700)], ["持平", "1", "100"]]},
        {"title": "每日收盤行情(全部(不含權證、牛熊證、可展延牛熊證))",
         "fields": ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌(+/-)", "漲跌價差", "最後揭示買價", "最後揭示買量", "最後揭示賣價", "最後揭示賣量", "本益比"],
         "data": rows},
        {}]}


def twse_t86(date):
    t = DI.get(date)
    if t is None:
        return {"stat": "很抱歉"}
    f = ["證券代號", "證券名稱", "外陸資買進股數(不含外資自營商)", "外陸資賣出股數(不含外資自營商)", "外陸資買賣超股數(不含外資自營商)",
         "外資自營商買進股數", "外資自營商賣出股數", "外資自營商買賣超股數", "投信買進股數", "投信賣出股數", "投信買賣超股數",
         "自營商買賣超股數", "自營商買進股數(自行買賣)", "自營商賣出股數(自行買賣)", "自營商買賣超股數(自行買賣)",
         "自營商買進股數(避險)", "自營商賣出股數(避險)", "自營商買賣超股數(避險)", "三大法人買賣超股數"]
    data = []
    for s in stocks:
        if s["mk"] != "TW":
            continue
        fi, it = int(s["fi"][t]), int(s["it"][t])
        data.append([s["code"], s["name"], "0", "0", _fmt(fi, 0), "0", "0", "0", "0", "0", _fmt(it, 0), "1,000",
                     "0", "0", "0", "0", "0", "0", _fmt(fi + it, 0)])
    return {"stat": "OK", "fields": f, "data": data}


def twse_mg(date):
    t = DI.get(date)
    if t is None:
        return {"stat": "很抱歉"}
    data = []
    for s in stocks:
        if s["mk"] != "TW":
            continue
        mb = s["mb"][t]
        data.append([s["code"], s["name"], "1", "1", "0", _fmt(mb, 0), _fmt(mb, 0), "100", "0", "0", "0", "100", _fmt(mb // 20, 0), "100", "0", ""])
    return {"stat": "OK", "tables": [
        {"title": "信用交易統計", "fields": ["項目", "買進", "賣出", "現金(券)償還", "前日餘額", "今日餘額"],
         "data": [["融資(交易單位)", "1", "1", "1", "9,000,000", _fmt(9000000 + t * 1000, 0)]]},
        {"title": "融資融券彙總 (全部)", "fields": ["代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額", "次一營業日限額",
                                              "買進", "賣出", "現券償還", "前日餘額", "今日餘額", "次一營業日限額", "資券互抵", "註記"], "data": data}]}


def tpex_otc(date):
    t = DI.get(date)
    if t is None:
        return {"tables": [{"data": [], "fields": []}], "stat": "ok"}
    data = []
    for s in stocks:
        if s["mk"] != "OTC":
            continue
        o, h, l, c, v, val, chg = _ohlc(s, t)
        data.append([s["code"], s["name"], _fmt(c), ("+" if chg >= 0 else "") + _fmt(chg), _fmt(o), _fmt(h), _fmt(l), _fmt(v, 0), _fmt(val, 0),
                     "100", _fmt(c), "10", _fmt(c), "10", _fmt(s["shares"], 0), "1", "1"])
    return {"tables": [{"title": "上櫃股票每日收盤行情(不含定價)", "fields": ["代號", "名稱", "收盤 ", "漲跌", "開盤 ", "最高 ", "最低", "成交股數  ", " 成交金額(元)", " 成交筆數 ", "最後買價", "最後買量<br>(張數)", "最後賣價", "最後賣量<br>(張數)", "發行股數 ", "次日漲停價 ", "次日跌停價"], "data": data}], "stat": "ok"}


def tpex_ins(date):
    t = DI.get(date)
    if t is None:
        return {"tables": [{"data": []}]}
    data = []
    for s in stocks:
        if s["mk"] != "OTC":
            continue
        fi, it = int(s["fi"][t]), int(s["it"][t])
        row = [s["code"], s["name"]] + ["0"] * 22
        row[10] = _fmt(fi, 0)
        row[13] = _fmt(it, 0)
        row[22] = "0"
        row[23] = _fmt(fi + it, 0)
        data.append(row)
    return {"tables": [{"fields": ["x"] * 24, "data": data}]}


def tpex_mg(date):
    t = DI.get(date)
    if t is None:
        return {"tables": [{"data": []}]}
    data = []
    for s in stocks:
        if s["mk"] != "OTC":
            continue
        row = [s["code"], s["name"]] + ["0"] * 18
        row[6] = _fmt(s["mb"][t], 0)
        row[14] = _fmt(s["mb"][t] // 30, 0)
        data.append(row)
    return {"tables": [{"data": data}]}


def fut_csv(date):
    t = DI.get(date)
    head = "交易日期,契約,到期月份(週別),開盤價,最高價,最低價,收盤價,漲跌價,漲跌%,成交量,結算價,未沖銷契約數,最後最佳買價,最後最佳賣價,歷史最高價,歷史最低價,是否因訊息面暫停交易,交易時段,價差對單式委託成交量\r\n"
    if t is None:
        return head
    dd = days[t].strftime("%Y/%m/%d")
    ym = days[t].strftime("%Y%m")
    nxt = (days[t].replace(day=1) + dt.timedelta(days=32)).strftime("%Y%m")
    lines = []
    tx = taiex[t] * 1.002
    for cid, px in (("TX", tx), ("MTX", tx), ("TMF", tx), ("TE", 1500.0), ("TF", 2000.0)):
        lines.append("%s,%s,%s  ,%d,%d,%d,%d,1,0.1%%,%d,%d,%d,1,1,1,1,,一般,," % (dd, cid, ym, px, px * 1.01, px * 0.99, px, 50000, px, 100000))
        lines.append("%s,%s,%s  ,%d,%d,%d,%d,1,0.1%%,%d,%d,%d,1,1,1,1,,一般,," % (dd, cid, nxt, px, px, px, px + 30, 3000, px, 9000))
        lines.append("%s,%s,%s  ,%d,%d,%d,%d,1,0.1%%,%d,-,-,1,1,1,1,,盤後,," % (dd, cid, ym, px, px, px, px, 20000))
    for k, s in enumerate(stocks[:30]):
        c = s["c"][t]
        lines.append("%s,%sF,%s  ,%.2f,%.2f,%.2f,%.2f,1,0.1%%,%d,%.2f,%d,1,1,1,1,,一般,," % (dd, "C" + chr(65 + k % 26) + ("" if k < 26 else "Z"), ym, c, c, c, c * 1.003, 1000 + k, c, 5000 + k))
    return head + "\r\n".join(lines) + "\r\n"


def txf_inst(start, end):
    out = ["日期,商品名稱,身份別,多方交易口數,多方交易契約金額(千元),空方交易口數,空方交易契約金額(千元),多空交易口數淨額,多空交易契約金額淨額(千元),多方未平倉口數,多方未平倉契約金額(千元),空方未平倉口數,空方未平倉契約金額(千元),多空未平倉口數淨額,多空未平倉契約金額淨額(千元)"]
    s0, e0 = dt.datetime.strptime(start, "%Y/%m/%d").date(), dt.datetime.strptime(end, "%Y/%m/%d").date()
    for t, d in enumerate(days):
        if s0 <= d <= e0:
            foi = int(-40000 + 20000 * math.sin(t / 15))
            dd = d.strftime("%Y/%m/%d")
            out.append("%s,臺股期貨,自營商,1,1,1,1,0,0,1,1,1,1,%d,1" % (dd, 2000))
            out.append("%s,臺股期貨,投信,1,1,1,1,0,0,1,1,1,1,%d,1" % (dd, 30000))
            out.append("%s,臺股期貨,外資及陸資,1,1,1,1,0,0,1,1,1,1,%d,1" % (dd, foi))
    return "\r\n".join(out) + "\r\n"


def pc(start, end):
    out = ["日期,賣權成交量,買權成交量,買賣權成交量比率%,賣權未平倉量,買權未平倉量,買賣權未平倉量比率%"]
    s0, e0 = dt.datetime.strptime(start, "%Y/%m/%d").date(), dt.datetime.strptime(end, "%Y/%m/%d").date()
    for t, d in enumerate(days):
        if s0 <= d <= e0:
            out.append("%s,1,1,90.0,1,1,%.2f," % (d.strftime("%Y/%m/%d"), 80 + 20 * math.sin(t / 9)))
    return "\r\n".join(out) + "\r\n"


def stocklists():
    rows = ['<table><tr><th>股票期貨、選擇權商品代碼</th><th>標的證券</th><th>證券代號</th><th>標的證券簡稱</th><th>是否為股票期貨標的</th></tr>']
    for k, s in enumerate(stocks[:30]):
        rows.append("<tr><td>%s</td><td>公司</td><td>%s</td><td>%s</td><td>● 是股票期貨標的</td></tr>" % (
            "C" + chr(65 + k % 26) + ("" if k < 26 else "Z"), s["code"], s["name"]))
    return "<html><body>" + "".join(rows) + "</table></body></html>"


WARRANTS = []
for k, s in enumerate(stocks[:60]):
    for j in range(6):
        call = j % 2 == 0
        c = s["c"][-1]
        K = round(c * random.uniform(0.8, 1.25), 2)
        code = ("%05d" % (30000 + k * 10 + j)) + ("" if call else "P")
        code = code[:6]
        WARRANTS.append({"code": code, "name": "%s測試%s%02d" % (s["name"][:2], "購" if call else "售", j), "call": call,
                         "u": s["code"], "un": s["name"], "K": K, "ratio": random.choice([50, 100, 200]),
                         "last": (TODAY + dt.timedelta(days=random.randint(20, 300))), "mk": s["mk"]})


def _roc(d):
    return "%d%02d%02d" % (d.year - 1911, d.month, d.day)


def warrant_terms(mk):
    out = []
    for w in WARRANTS:
        if w["mk"] != mk:
            continue
        out.append({"權證代號": w["code"], "權證簡稱": w["name"], "權證類型": "認購" if w["call"] else "認售", "類別": "一般型",
                    "流動量提供者報價方式": "主動報價", "最後交易日": _roc(w["last"]), "發行單位數量(仟單位)": "5000",
                    "標的證券/指數": w["un"], "最新標的履約配發數量(每仟單位權證)": "%.2f" % w["ratio"],
                    "最新履約價格(元)/履約指數": "%.4f" % w["K"]})
    return out


def _wprice(w, S):
    from derivs import bs
    T_ = max(1, (w["last"] - TODAY).days) / 365
    p = bs(S, w["K"], T_, random.uniform(0.3, 0.6), w["call"])[0] * w["ratio"] / 1000
    return max(0.01, round(p, 2))


def twse_warr(date, typ):
    t = DI.get(date)
    data = []
    for w in WARRANTS:
        if w["mk"] != "TW" or (typ == "0999") != w["call"]:
            continue
        s = next(x for x in stocks if x["code"] == w["u"])
        S = s["c"][t]
        p = _wprice(w, S)
        data.append(["", w["code"], w["name"], "10,000", "3", "1", _fmt(p), _fmt(p), _fmt(p), _fmt(p), "+", "0.01",
                     _fmt(p * 0.99), "10", _fmt(p * 1.01), "10", "0", w["u"], w["un"], _fmt(S)])
    tabs = [{}] * 9 + [{"title": "權證", "fields": ["暫停交易", "證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌(+/-)", "漲跌價差", "最後揭示買價", "最後揭示買量", "最後揭示賣價", "最後揭示賣量", "本益比", "標的代號", "標的名稱", "標的收盤價/指數"], "data": data}]
    return {"stat": "OK", "tables": tabs}


def tpex_dq(date):
    t = DI.get(date)
    data = []
    for w in WARRANTS:
        if w["mk"] != "OTC":
            continue
        s = next(x for x in stocks if x["code"] == w["u"])
        p = _wprice(w, s["c"][t])
        data.append([w["code"], w["name"], _fmt(p), "+0.01", _fmt(p), _fmt(p), _fmt(p), _fmt(p), "5,000", "100", "2", _fmt(p * 0.98), "10", _fmt(p * 1.02), "10", "5,000,000", _fmt(p), "1", "0.01"])
    return {"tables": [{"fields": ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "均價", "成交股數", "成交金額(元)", "成交筆數", "最後買價", "最後買量(張數)", "最後賣價", "最後賣量(張數)", "發行股數", "次日 參考價", "次日 漲停價", "次日 跌停價"], "data": data}]}


def tpex_wq():
    out = []
    for w in WARRANTS:
        if w["mk"] == "OTC":
            s = next(x for x in stocks if x["code"] == w["u"])
            out.append({"Code": w["code"], "UnderlyingStockCode": w["u"], "UnderlyingStockClosePrice": str(s["c"][-1])})
    return out


def revenue(mk):
    out = []
    for s in stocks:
        if s["mk"] == mk and len(s["code"]) == 4 and not s["code"].startswith("00"):
            out.append({"資料年月": "11509", "公司代號": s["code"], "產業別": s["ind"], "營業收入-當月營收": "100000",
                        "營業收入-去年同月增減(%)": "%.2f" % random.gauss(8, 25), "營業收入-上月比較增減(%)": "1.2",
                        "累計營業收入-前期比較增減(%)": "%.2f" % random.gauss(6, 20)})
    return out


def handle(url, data=None):
    u = urllib.parse.urlparse(url)
    q = dict(urllib.parse.parse_qsl(u.query))
    p = u.path
    if "MI_INDEX" in p:
        if q.get("type") in ("0999", "0999P"):
            return json.dumps(twse_warr(q["date"], q["type"]))
        return json.dumps(twse_mi(q["date"]))
    if p.endswith("/T86"):
        return json.dumps(twse_t86(q["date"]))
    if p.endswith("/MI_MARGN"):
        return json.dumps(twse_mg(q["date"]))
    if "BWIBBU_d" in p:
        return json.dumps({"stat": "OK", "fields": ["證券代號", "證券名稱", "收盤價", "殖利率(%)", "股利年度", "本益比", "股價淨值比", "財報年/季"],
                           "data": [[s["code"], s["name"], "1", "%.2f" % random.uniform(0, 7), 114, "%.2f" % random.uniform(6, 40), "%.2f" % random.uniform(0.6, 6), "115/2"] for s in stocks if s["mk"] == "TW"]})
    if p.endswith("/afterTrading/otc"):
        return json.dumps(tpex_otc(q["date"].replace("/", "")))
    if p.endswith("/insti/dailyTrade"):
        return json.dumps(tpex_ins(q["date"].replace("/", "")))
    if p.endswith("/margin/balance"):
        return json.dumps(tpex_mg(q["date"].replace("/", "")))
    if p.endswith("/afterTrading/dailyQuotes"):
        return json.dumps(tpex_dq(q["date"].replace("/", "")))
    if p.endswith("/futDataDown"):
        return fut_csv(data["queryStartDate"].replace("/", ""))
    if p.endswith("/futContractsDateDown"):
        return txf_inst(data["queryStartDate"], data["queryEndDate"])
    if p.endswith("/pcRatioDown"):
        return pc(data["queryStartDate"], data["queryEndDate"])
    if p.endswith("/stockLists"):
        return stocklists()
    if p.endswith("t187ap05_L"):
        return json.dumps(revenue("TW"))
    if p.endswith("mopsfin_t187ap05_O"):
        return json.dumps(revenue("OTC"))
    if p.endswith("tpex_mainboard_peratio_analysis"):
        return json.dumps([{"SecuritiesCompanyCode": s["code"], "PriceEarningRatio": "15.2", "YieldRatio": "3.1", "PriceBookRatio": "1.8"} for s in stocks if s["mk"] == "OTC"])
    if p.endswith("t187ap17_L"):
        return json.dumps([{"年度": "115", "季別": "2", "公司代號": s["code"], "毛利率(%)(營業毛利)/(營業收入)": "30", "營業利益率(%)(營業利益)/(營業收入)": "%.1f" % random.gauss(10, 8), "稅後純益率(%)(稅後純益)/(營業收入)": "8"} for s in stocks if s["mk"] == "TW"])
    if p.endswith("t187ap06_L_ci"):
        return json.dumps([{"年度": "115", "季別": "2", "公司代號": s["code"], "基本每股盈餘（元）": "%.2f" % random.gauss(2, 2)} for s in stocks if s["mk"] == "TW"])
    if p.endswith("t187ap37_L"):
        return json.dumps(warrant_terms("TW"))
    if p.endswith("mopsfin_t187ap37_O"):
        return json.dumps(warrant_terms("OTC"))
    if p.endswith("tpex_warrant_daily_quts"):
        return json.dumps(tpex_wq())
    if "openapi" in url:
        return "[]"
    raise Exception("mock: 未知網址 " + url)
