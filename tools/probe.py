# -*- coding: utf-8 -*-
"""連線測試：比較幾個即時行情來源的更新頻率（盤中執行）。"""
import json, os, re, time, urllib.request, ssl, http.cookiejar
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
ctx = ssl.create_default_context(); ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), urllib.request.HTTPCookieProcessor(cj))
os.makedirs("probe_files", exist_ok=True)
res = {}
def get(url, ref=None, accept="*/*"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": ref or url, "Accept": accept})
    with op.open(req, timeout=20) as r:
        return r.read()
def save(name, b):
    open("probe_files/" + name, "wb").write(b)
# 1) fibest 頁面與它用的 JS（看網頁版用什麼方式更新）
try:
    h = get("https://mis.twse.com.tw/stock/fibest.jsp?stock=2330", accept="text/html").decode("utf-8", "ignore")
    save("fibest.html", h.encode())
    for js in re.findall(r'src="([^"]+\.js[^"]*)"', h)[:12]:
        u = js if js.startswith("http") else "https://mis.twse.com.tw/stock/" + js.lstrip("./")
        try:
            save("js_" + re.sub(r"[^A-Za-z0-9.]", "_", js)[-60:], get(u))
        except Exception as e:
            res["js " + js] = str(e)
except Exception as e:
    res["fibest"] = str(e)
# 2) MIS 每 2 秒一次，60 秒
seq = []
t0 = time.time()
while time.time() - t0 < 60:
    try:
        j = json.loads(get("https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_2330.tw&json=1&delay=0&_=%d" % int(time.time() * 1000),
                           ref="https://mis.twse.com.tw/stock/fibest.jsp?stock=2330", accept="application/json"))
        x = (j.get("msgArray") or [{}])[0]
        seq.append({"at": round(time.time() - t0, 1), "t": x.get("t"), "tlong": x.get("tlong"), "v": x.get("v"), "z": x.get("z"),
                    "trade": x.get("trade"), "b": x.get("b", "")[:20], "g": x.get("g", "")[:20], "rtcode": j.get("rtcode"), "qt": j.get("queryTime")})
    except Exception as e:
        seq.append({"at": round(time.time() - t0, 1), "err": str(e)})
    time.sleep(2)
json.dump(seq, open("probe_files/mis_seq.json", "w"), ensure_ascii=False)
# 3) Yahoo 奇摩股市（台灣）報價與五檔
for name, url in [
    ("yq.json", "https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.stockList;fields=avgPrice%2Corderbook;symbols=2330.TW"),
    ("yob.json", "https://tw.stock.yahoo.com/_td-stock/api/resource/StockServices.getOrderBook;symbol=2330.TW"),
    ("ychart.json", "https://query1.finance.yahoo.com/v8/finance/chart/2330.TW?interval=1m&range=1d"),
]:
    try:
        save(name, get(url, ref="https://tw.stock.yahoo.com/quote/2330.TW", accept="application/json"))
        res[name] = "ok"
    except Exception as e:
        res[name] = str(e)
# Yahoo 1 分 K 連續看 3 次（每 20 秒），確認是不是即時
ys = []
for i in range(3):
    try:
        j = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/2330.TW?interval=1m&range=1d&_=%d" % time.time()))
        r = j["chart"]["result"][0]
        ys.append({"i": i, "now": int(time.time()), "last_ts": r["timestamp"][-1], "meta_time": r["meta"].get("regularMarketTime"), "price": r["meta"].get("regularMarketPrice")})
    except Exception as e:
        ys.append({"i": i, "err": str(e)})
    time.sleep(20)
json.dump(ys, open("probe_files/yseq.json", "w"))
json.dump(res, open("probe_result.json", "w"), ensure_ascii=False, indent=1)
