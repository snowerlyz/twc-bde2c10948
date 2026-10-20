# -*- coding: utf-8 -*-
"""月營收與季財報的歷史資料（公開資訊觀測站）。

- 月營收：每月 10 日前公布上個月營收。存成 db/fin/rev_YYYYMM.json：{代號: [當月營收, 去年同月營收]}（千元）
- 季財報：存累計每股盈餘 db/fin/eps_YYYYQn.json：{代號: 累計 EPS}

用來計算：營收成長加速、營收創 12 個月新高、單季 EPS 年增率與成長加速（財報驚喜）。
回測時只在「法定公布期限之後」才使用，避免偷看未來。
"""
import datetime as dt
import os
import re

from util import DB, fetch, log, read_json, today_tw, write_json

FIN_DIR = os.path.join(DB, "fin")
MOPS = "https://mopsov.twse.com.tw"


def _num(s):
    s = re.sub(r"<[^>]+>", "", s).replace(",", "").replace("&nbsp;", "").strip()
    try:
        return float(s)
    except Exception:
        return None


def parse_rev(html):
    out = {}
    for row in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.S | re.I)
        if len(cells) < 10:
            continue
        code = re.sub(r"<[^>]+>", "", cells[0]).strip()
        if not re.fullmatch(r"\d{4}", code):
            continue
        cur, ly = _num(cells[2]), _num(cells[4])
        if cur is not None:
            out[code] = [cur, ly]
    return out


def parse_eps(html):
    out = {}
    for tb in re.finditer(r"<table class='hasBorder'(.*?)</table>", html, re.S):
        t = tb.group(1)
        heads = [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<th[^>]*>(.*?)</th>", t, re.S)]
        try:
            ic = next(i for i, h in enumerate(heads) if "代號" in h)
            ie = next(i for i, h in enumerate(heads) if "每股盈餘" in h)
        except StopIteration:
            continue
        for row in re.finditer(r"<tr class='(?:even|odd)'>(.*?)</tr>", t, re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.S)
            if len(cells) <= max(ic, ie):
                continue
            code = re.sub(r"<[^>]+>", "", cells[ic]).strip()
            v = _num(cells[ie])
            if re.fullmatch(r"\d{4}", code) and v is not None:
                out[code] = v
    return out


def _months_back(n):
    d = today_tw()
    y, m = d.year, d.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append((y, m))
    return out


def _quarters_back(n):
    d = today_tw()
    y, q = d.year, (d.month - 1) // 3 + 1
    out = []
    for _ in range(n):
        q -= 1
        if q == 0:
            y, q = y - 1, 4
        out.append((y, q))
    return out


def collect_fin(prog=None, months=38, quarters=14):
    os.makedirs(FIN_DIR, exist_ok=True)
    today = today_tw()
    n_new = 0
    for i, (y, m) in enumerate(_months_back(months)):
        path = os.path.join(FIN_DIR, "rev_%04d%02d.json" % (y, m))
        old = read_json(path)
        # 最近兩個月在公布期間內可能還在增加，每次都重抓
        if old and i >= 2:
            continue
        data = {}
        ok = False
        for mkt in ("sii", "otc"):
            for k in (0, 1):
                url = "%s/nas/t21/%s/t21sc03_%d_%d_%d.html" % (MOPS, mkt, y - 1911, m, k)
                try:
                    x = fetch(url, encoding="big5", retries=2)
                    data.update(parse_rev(x))
                    ok = True
                except Exception as e:
                    if "404" not in str(e):
                        log("月營收 %d/%d %s：%s" % (y, m, mkt, e))
        if ok and data and (not old or len(data) >= len(old)):
            write_json(path, data)
            n_new += 1
            if prog:
                prog.set(msg="下載月營收歷史（%d/%d 月）" % (y, m))
    for i, (y, q) in enumerate(_quarters_back(quarters)):
        path = os.path.join(FIN_DIR, "eps_%04dQ%d.json" % (y, q))
        old = read_json(path)
        if old and i >= 2:
            continue
        data = {}
        for typek in ("sii", "otc"):
            try:
                x = fetch(MOPS + "/mops/web/ajax_t163sb04", data={
                    "encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "isQuery": "Y",
                    "TYPEK": typek, "year": str(y - 1911), "season": "%02d" % q}, retries=2)
                data.update(parse_eps(x))
            except Exception as e:
                log("季財報 %dQ%d %s：%s" % (y, q, typek, e))
        if data and (not old or len(data) >= len(old)):
            write_json(path, data)
            n_new += 1
            if prog:
                prog.set(msg="下載季財報歷史（%d 年第 %d 季）" % (y, q))
    if n_new:
        log("月營收／季財報：更新 %d 份" % n_new)
    return n_new


# ====================================================================== 給分析引擎用

def _rev_avail_ym(d):
    """台股第 d 天（YYYYMMDD）可以用到哪個月份的營收：每月 10 日公布截止，11 日起才用上個月的。"""
    y, m, day = int(d[:4]), int(d[4:6]), int(d[6:8])
    back = 1 if day >= 11 else 2
    m -= back
    while m <= 0:
        y, m = y - 1, m + 12
    return y * 100 + m


FIN_INDUSTRY = ("金融保險業", "金融業")


def _eps_avail(y, q, fin):
    """第 y 年第 q 季財報的法定公布期限隔天（YYYYMMDD）。"""
    if q == 4:
        return "%04d0401" % (y + 1)
    if fin:
        return "%04d%s" % (y, {1: "0601", 2: "0901", 3: "1201"}[q])
    return "%04d%s" % (y, {1: "0516", 2: "0815", 3: "1115"}[q])


def load(days, industry):
    """回傳 {代號: {"rev_yoy": [...], "rev_cum": [...], "rev_yoy3": [...], "rev_acc": [...], "rev_high": [...],
                     "eps_yoy": [...], "eps_acc": [...]}}（長度 = 交易日數，沒有值為 None）。"""
    if not os.path.isdir(FIN_DIR):
        return {}
    revs, eps = {}, {}
    for f in os.listdir(FIN_DIR):
        m = re.fullmatch(r"rev_(\d{6})\.json", f)
        if m:
            revs[int(m.group(1))] = read_json(os.path.join(FIN_DIR, f)) or {}
        m = re.fullmatch(r"eps_(\d{4})Q(\d)\.json", f)
        if m:
            eps[(int(m.group(1)), int(m.group(2)))] = read_json(os.path.join(FIN_DIR, f)) or {}
    T = len(days)
    codes = set()
    for v in revs.values():
        codes |= set(v)
    for v in eps.values():
        codes |= set(v)
    yms = sorted(revs)

    def prev_ym(ym, k):
        y, m = divmod(ym, 100)
        m -= k
        while m <= 0:
            y, m = y - 1, m + 12
        return y * 100 + m

    avail = [_rev_avail_ym(d) for d in days]
    # 單季 EPS
    qs = sorted(eps)
    out = {}
    for code in codes:
        F = {k: [None] * T for k in ("rev_yoy", "rev_cum", "rev_yoy3", "rev_acc", "rev_high", "eps_yoy", "eps_acc")}
        # ---- 營收：先算每個月的指標，再對到交易日
        mv = {}
        for ym in yms:
            r = revs[ym].get(code)
            if not r or r[0] is None:
                continue
            mv[ym] = r
        cache = {}

        def month_feats(ym):
            if ym in cache:
                return cache[ym]
            res = None
            r = mv.get(ym)
            if r:
                cur, ly = r
                yoy = (cur / ly - 1) * 100 if ly and ly > 0 else None
                last3 = [mv.get(prev_ym(ym, k)) for k in range(3)]
                y3 = None
                if all(x and x[1] and x[1] > 0 for x in last3):
                    y3 = (sum(x[0] for x in last3) / sum(x[1] for x in last3) - 1) * 100
                older = [mv.get(prev_ym(ym, k)) for k in range(3, 12)]
                acc = None
                if y3 is not None and sum(1 for x in older if x and x[1] and x[1] > 0) >= 6:
                    oo = [x for x in older if x and x[1] and x[1] > 0]
                    acc = y3 - (sum(x[0] for x in oo) / sum(x[1] for x in oo) - 1) * 100
                prev12 = [mv.get(prev_ym(ym, k)) for k in range(1, 12)]
                prev12 = [x[0] for x in prev12 if x]
                high = (cur / max(prev12) - 1) if len(prev12) >= 9 and max(prev12) > 0 else None
                y0 = ym // 100
                cum = [mv.get(y0 * 100 + mm) for mm in range(1, ym % 100 + 1)]
                cumv = None
                if all(x and x[1] for x in cum):
                    s_ly = sum(x[1] for x in cum)
                    cumv = (sum(x[0] for x in cum) / s_ly - 1) * 100 if s_ly > 0 else None
                res = (yoy, cumv, y3, acc, high)
            cache[ym] = res
            return res

        # ---- EPS：單季值與年增率
        cum = {k: eps[k].get(code) for k in qs}
        single = {}
        for (y, q) in qs:
            c = cum.get((y, q))
            if c is None:
                continue
            if q == 1:
                single[(y, q)] = c
            elif cum.get((y, q - 1)) is not None:
                single[(y, q)] = c - cum[(y, q - 1)]
        qyoy = {}
        for (y, q), v in single.items():
            ly = single.get((y - 1, q))
            if ly is not None:
                qyoy[(y, q)] = max(-3.0, min(3.0, (v - ly) / max(abs(ly), 0.1)))
        fin = industry.get(code) in FIN_INDUSTRY
        qav = sorted(((_eps_avail(y, q, fin), (y, q)) for (y, q) in qyoy))
        qi = 0
        cur_q = None
        for t, d in enumerate(days):
            mf = month_feats(avail[t])
            if mf:
                F["rev_yoy"][t], F["rev_cum"][t], F["rev_yoy3"][t], F["rev_acc"][t], F["rev_high"][t] = mf
            while qi < len(qav) and qav[qi][0] <= d:
                cur_q = qav[qi][1]
                qi += 1
            if cur_q:
                F["eps_yoy"][t] = qyoy[cur_q]
                y, q = cur_q
                pq = (y, q - 1) if q > 1 else (y - 1, 4)
                if pq in qyoy:
                    F["eps_acc"][t] = qyoy[cur_q] - qyoy[pq]
        out[code] = F
    return out
