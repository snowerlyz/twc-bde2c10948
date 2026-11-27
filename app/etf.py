# -*- coding: utf-8 -*-
"""ETF 評價（2026-11-27，使用者要求「加入 ETF 的評估」）。

1. 類型：依代號與名稱分成 市值型／高股息／主動式／產業主題／海外股票／槓桿反向／原物料期貨／債券／平衡型／不動產。
2. 評價：只評「股票型」ETF（市值型、高股息、主動式、產業主題、海外股票），而且每天平均成交 3000 萬以上。
   分數沿用個股模型的綜合分數，但只在這些 ETF 之間排名；準確度＝之後跑贏（建議買）／跑輸（建議賣）加權指數的比例，
   和個股用同一套規則（rec.py）：最近 60 個已揭曉交易日、照「當時」規則 walk-forward，
   60% 以上合格、55%～60% 警示、低於 55% 不列「建議」改為「相對看好／看淡」。ETF 的準確度和個股分開計算、互不影響。
3. 槓桿／反向、原物料期貨、債券等不給評價，只顯示類型與風險提醒。
4. 折溢價：證交所「ETF 即時預估淨值」（盤後抓收盤時的數字，見 extra.collect_etf_nav），只做提醒、不進評分。
"""
import os
import re

from util import DB, is_etf, read_json

import rec as R

H = R.H
MIN_ROWS = 30            # 某一天至少要有這麼多檔 ETF 有結果才算
RATED = ("市值型", "高股息", "主動式", "產業主題", "海外股票")

_FOREIGN = re.compile(r"美國|美股|US|費城|NASDAQ|那斯達克|納斯達克|S&P|標普|道瓊|日本|日經|東證|中國|滬深|上証|上證|深証|深100|中証|"
                      r"A50|A股|恒生|香港|印度|越南|全球|世界|歐洲|韓國|KOSPI|亞太|亞洲|新興|洲際|FANG|MAG7|北美|ARK|藍籌100")
_DIV = re.compile(r"高息|高股息|股息|股利|收益|優息|填息|收息|豐收")
_IND = re.compile(r"半導體|科技|電子|IC|晶圓|AI|5G|通訊|網路|資安|電動車|未來車|智能車|電池|儲能|綠能|電力|潔淨能源|生技|基因|"
                  r"元宇宙|支付|太空|衛星|航運|航太|防衛|金融|機器人|PCB|算力|稀土|商社|工業|創新|研發|基建")


def kind(code, name):
    """回傳 (類型, 是否海外)。"""
    n = name or ""
    foreign = bool(_FOREIGN.search(n)) or code.endswith("K")
    if code.endswith(("L", "R")) or "正2" in n or "反1" in n:
        return "槓桿反向", foreign
    if code.endswith("U") or n.startswith("期") or re.search(r"黃金|石油|原油|白銀|黃豆|銅$|美元指", n):
        return "原物料期貨", foreign
    if code.endswith(("B", "D")) or "債" in n:
        return "債券", foreign
    if code.endswith("T") or n.startswith("平衡"):
        return "平衡型", foreign
    if re.search(r"REITs|不動產|地產|特別股", n):
        return "不動產", foreign
    if code.endswith("A") or n.startswith("主動"):
        return "主動式", foreign
    if foreign:
        return "海外股票", True
    if _DIV.search(n):
        return "高股息", False
    if _IND.search(n):
        return "產業主題", False
    return "市值型", False


KIND_NOTE = {
    "市值型": "追蹤一籃子大公司，走勢通常和加權指數接近。",
    "高股息": "挑殖利率高的股票，配息多，但漲勢常落後大盤；配息要繳稅與健保補充保費。",
    "主動式": "由經理人自己挑股票，表現看經理人；費用通常比被動型高。",
    "產業主題": "集中在單一產業或主題，漲跌常比大盤大。",
    "海外股票": "投資國外股市，漲跌主要看國外行情與匯率，和台股不同步。",
    "槓桿反向": "每天重新調整，只適合很短期操作；長期持有會因為每天重設而和指數的倍數越差越遠，盤整時特別明顯。",
    "原物料期貨": "用期貨追蹤原物料，換月有成本，長期持有可能和現貨價格差很多。",
    "債券": "主要投資債券，漲跌看利率與信用，不適合和加權指數比。",
    "平衡型": "股票和債券都有，波動比股票型小。",
    "不動產": "投資不動產信託或特別股，主要看配息與利率。",
}


def nav_info():
    """證交所 ETF 預估淨值與折溢價（盤後的最後一筆）。沒有資料時回傳空 dict。"""
    d = read_json(os.path.join(DB, "etf_nav.json"), {}) or {}
    return d.get("rows") or {}, d.get("day")


def build(D, A_all, pct_hist, v20s, stocks, live=None):
    """回傳 (out, per)：out 是三個期間的準確度把關與今天的清單；per[code][hn] 是每檔 ETF 的評價（格式同 rec 的 per_stock）。"""
    last = D.T - 1
    tx = D.mkt["taiex"]
    names = {r["c"]: r.get("n") or "" for r in stocks}
    uni = [D.idx[c] for c in names if is_etf(c) and c in D.idx and kind(c, names[c])[0] in RATED]
    out = {"day": D.days[last], "h": {}, "rule": {"pass": R.ACC_PASS, "fail": R.ACC_FAIL, "days": R.ACC_DAYS},
           "universe": len(uni)}
    per = {}
    for hn, h in H.items():
        ph = pct_hist.get(hn) or {}
        if not ph:
            continue

        def rank_of(u):
            pu = ph.get(u) or {}
            order = sorted((i for i in uni if i in pu and v20s[i][u] >= R.MIN_VAL), key=lambda i: pu[i])
            n = len(order)
            return {i: (j + 1) / n for j, i in enumerate(order)} if n else {}

        data = {}
        for u in sorted(ph):
            if u + h > last or R.isnan(tx[u]) or R.isnan(tx[u + h]) or tx[u] <= 0:
                continue
            bm = tx[u + h] / tx[u] - 1
            rows = []
            for i, p in rank_of(u).items():
                a0, a1 = A_all[i][u], A_all[i][u + h]
                if R.isnan(a0) or R.isnan(a1) or a0 <= 0:
                    continue
                r = a1 / a0 - 1
                rows.append((p, r, r - bm))
            if len(rows) >= MIN_ROWS:
                data[u] = rows
        known = sorted(data)

        def pick(rows, sd, c):
            return [x for x in rows if (x[0] >= c if sd == "buy" else x[0] <= 1 - c)]

        st = {}
        for sd in ("buy", "sell"):
            for c in R.CUTS:
                dd = {}
                for u in known:
                    xs = pick(data[u], sd, c)
                    good = sum(1 for x in xs if (x[2] > 0 if sd == "buy" else x[2] < 0))
                    dd[u] = (good, len(xs), sum(x[2] for x in xs))
                st[(sd, c)] = dd

        def trail(t, sd):
            tr = [u for u in known if t - h - R.ACC_DAYS < u <= t - h]
            acc = {}
            if len(tr) >= 20:
                for c in R.CUTS:
                    w = sum(st[(sd, c)][u][0] for u in tr)
                    n = sum(st[(sd, c)][u][1] for u in tr)
                    if n >= R.CUT_MIN_N:
                        acc[c] = w / n
            return acc, tr

        def watch_cut(t, sd):
            acc, _ = trail(t, sd)
            cs = [k for k in acc if k >= R.WATCH_MIN_CUT]
            return (max(cs, key=lambda k: (acc[k], k)) if cs else None), acc

        # walk-forward：過去每一天照「當時」的規則挑，之後真正的成績
        wf, wr = {"buy": {}, "sell": {}}, {"buy": {}, "sell": {}}
        for sd in ("buy", "sell"):
            for t in known:
                acc, _ = trail(t, sd)
                c, kd = R._choose(acc)
                if kd == "watch":
                    c, _ = watch_cut(t, sd)
                if c is not None:
                    wf[sd][t] = (kd, c) + st[(sd, c)][t]
                cw, _ = watch_cut(t, sd)
                if cw is not None:
                    wr[sd][t] = st[(sd, cw)][t]
        lv = ((((live or {}).get("rhe") or {}).get(hn)) or {})
        gate, label = {}, {}
        k60 = set(known[-R.ACC_DAYS:])
        for sd in ("buy", "sell"):
            ok_days = [t for t in known if t in wf[sd] and wf[sd][t][0] == "ok"]
            rec_days = [t for t in ok_days if t in k60]

            def agg(ts):
                w = sum(wf[sd][t][2] for t in ts)
                n = sum(wf[sd][t][3] for t in ts)
                return (w / n if n else None), n
            r_all, n_all = agg(ok_days)
            r_60, n_60 = agg(rec_days)
            lx = lv.get(sd) or {}
            r_lv = lx.get("win") if (lx.get("n") or 0) >= R.ACC_MIN_N else None
            rates = [x for x in ((r_60 if n_60 >= R.CUT_MIN_N else None), r_lv) if x is not None]
            rate = min(rates) if rates else None
            acc, tr = trail(last, sd)
            c, kd = R._choose(acc)
            off = kd == "ok" and rate is not None and rate < R.ACC_FAIL
            if off or kd == "watch":
                cw, accw = watch_cut(last, sd)
                if cw is not None:
                    c, acc = cw, accw
                kd = "watch"
            td = wf[sd].get(last - h)

            def _wr(xs):
                n = sum(x[1] for x in xs)
                return round(sum(x[0] for x in xs) / n, 4) if n else None
            wr_60 = [wr[sd][t] for t in known[-R.ACC_DAYS:] if t in wr[sd]]
            pool = [x for u in tr for x in pick(data.get(u, []), sd, c)] if c is not None else []
            label[sd] = {"c": c, "kind": kd, "ex": R._q([x[2] for x in pool], 0.5),
                         "up": sum(1 for x in pool if x[1] > 0) / len(pool) if pool else None,
                         "lo": R._q([x[1] for x in pool], 0.2), "hi": R._q([x[1] for x in pool], 0.8)}
            # 基準率：同一段時間全部（會評價的）ETF 跑贏／跑輸大盤的比例
            allx = [x for u in known[-R.ACC_DAYS:] for x in data[u]]
            base = (sum(1 for x in allx if (x[2] > 0 if sd == "buy" else x[2] < 0)) / len(allx)) if allx else None
            gate[sd] = {"rate": None if rate is None else round(rate, 4),
                        "bt": None if r_60 is None else round(r_60, 4), "bt_n": n_60,
                        "bt_all": None if r_all is None else round(r_all, 4), "bt_all_n": n_all,
                        "live": None if r_lv is None else round(r_lv, 4), "live_n": lx.get("n") or 0,
                        "status": R._status(rate) if kd == "ok" or off else ("相對" if kd == "watch" else "資料不足"),
                        "off": off, "mode": {"ok": "建議", "watch": "相對"}.get(kd),
                        "cut": c, "trail": None if c is None or c not in acc else round(acc[c], 4),
                        "today": round(td[2] / td[3], 4) if td and td[3] and td[0] == "ok" else None,
                        "today_n": td[3] if td and td[0] == "ok" else 0,
                        "w_all": _wr([wr[sd][t] for t in known if t in wr[sd]]), "w_60": _wr(wr_60),
                        "w_cnt": round(sum(x[1] for x in wr_60) / len(wr_60), 1) if wr_60 else 0,
                        "base": None if base is None else round(base, 4)}
        out["h"][hn] = {"gate": gate, "days": len(known), "sides": [sd for sd in label if label[sd]["kind"] == "ok"],
                        "active": any(label[sd]["kind"] == "ok" for sd in label),
                        "n_today": len(rank_of(last)) if last in ph else 0}
        for i, p in (rank_of(last) if last in ph else {}).items():
            a, x = "hold", None
            for sd in ("buy", "sell"):
                L_ = label[sd]
                if L_["c"] is None:
                    continue
                if (p >= L_["c"]) if sd == "buy" else (p <= 1 - L_["c"]):
                    a, x = (sd if L_["kind"] == "ok" else "w" + sd), L_
            d = per.setdefault(D.codes[i], {})
            if x is None:
                d[hn] = {"a": "hold", "ex": None, "lo": None, "hi": None, "up": None, "p": round(p, 4)}
            else:
                d[hn] = {"a": a, "ex": None if x["ex"] is None else round(x["ex"], 4), "lo": x["lo"], "hi": x["hi"],
                         "up": None if x["up"] is None else round(x["up"], 3), "p": round(p, 4)}
    return out, per
