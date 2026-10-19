# -*- coding: utf-8 -*-
"""共用工具：路徑、記錄、網路抓取（含限速與重試）、檔案讀寫、數字解析。"""
import datetime as dt
import gzip
import json
import os
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP_DIR)
DATA = os.environ.get("TWC_DATA") or os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "raw")
DB = os.path.join(DATA, "db")
RESULTS = os.path.join(DATA, "results")
LOGS = os.path.join(DATA, "logs")
for _d in (DATA, RAW, DB, RESULTS, LOGS):
    os.makedirs(_d, exist_ok=True)

_log_lock = threading.Lock()


def log(msg):
    line = "%s %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    with _log_lock:
        try:
            print(line, flush=True)
        except Exception:
            pass
        try:
            with open(os.path.join(LOGS, "run.log"), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


# ---------------------------------------------------------------- 檔案

def write_json(path, obj, gz=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if gz:
        data = gzip.compress(data, 6)
    with open(tmp, "wb") as f:
        f.write(data)
    for i in range(10):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            # Windows：檔案剛好被網頁讀取中，稍等再試
            time.sleep(0.2 * (i + 1))
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        with open(path, "rb") as f:
            data = f.read()
        if path.endswith(".gz"):
            data = gzip.decompress(data)
        return json.loads(data.decode("utf-8"))
    except FileNotFoundError:
        return default
    except Exception as e:
        log("讀取失敗 %s: %s" % (path, e))
        return default


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------- 網路

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# 各網站最短請求間隔（秒）。證交所對過快的請求會暫時封鎖 IP，所以放慢。
HOST_GAP = {
    "www.twse.com.tw": 3.2,
    "openapi.twse.com.tw": 1.0,
    "www.tpex.org.tw": 1.2,
    "www.taifex.com.tw": 1.5,
    "openapi.taifex.com.tw": 1.0,
}
_host_locks = {}
_host_last = {}
_hl_guard = threading.Lock()


def _ssl_ctx(strict=True):
    ctx = ssl.create_default_context()
    if not strict and hasattr(ssl, "VERIFY_X509_STRICT"):
        # 部分政府網站憑證缺少 Subject Key Identifier，新版 Python 嚴格模式會拒絕
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


_CTX_STRICT = _ssl_ctx(True)
_CTX_LOOSE = _ssl_ctx(False)


class FetchError(Exception):
    pass


def _wait_turn(host):
    with _hl_guard:
        lock = _host_locks.setdefault(host, threading.Lock())
    lock.acquire()
    try:
        gap = HOST_GAP.get(host, 1.0)
        last = _host_last.get(host, 0)
        now = time.time()
        if now - last < gap:
            time.sleep(gap - (now - last))
        _host_last[host] = time.time()
    finally:
        lock.release()


def fetch(url, data=None, timeout=60, retries=3, encoding=None, raw=False):
    """抓取網址。data 為 dict 時用 POST 表單。回傳文字（或 bytes）。"""
    host = urllib.parse.urlparse(url).netloc
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("ascii")
    last_err = None
    for attempt in range(retries):
        _wait_turn(host)
        req = urllib.request.Request(url, data=body, headers={
            "User-Agent": UA,
            "Accept": "application/json,text/csv,text/html,*/*",
            "Accept-Language": "zh-TW,zh;q=0.9",
        })
        if body is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        for ctx in (_CTX_STRICT, _CTX_LOOSE):
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                    b = r.read()
                    if r.headers.get("Content-Encoding") == "gzip":
                        b = gzip.decompress(b)
                    if raw:
                        return b
                    enc = encoding
                    if not enc:
                        ct = r.headers.get("Content-Type", "")
                        m = re.search(r"charset=([\w-]+)", ct)
                        enc = m.group(1) if m else "utf-8"
                        if enc.lower() in ("ms950", "big5"):
                            enc = "cp950"
                    return b.decode(enc, errors="replace")
            except ssl.SSLError as e:
                last_err = e
                continue  # 換寬鬆模式再試
            except urllib.error.URLError as e:
                if isinstance(getattr(e, "reason", None), ssl.SSLError):
                    last_err = e
                    continue
                last_err = e
                break
            except Exception as e:
                last_err = e
                break
        time.sleep(3 + attempt * 5)
    raise FetchError("%s：%s" % (url, last_err))


def fetch_json(url, **kw):
    t = fetch(url, **kw)
    t = t.strip()
    if not t or t[0] not in "[{":
        raise FetchError("%s 回傳的不是 JSON：%s" % (url, t[:120]))
    return json.loads(t)


# ---------------------------------------------------------------- 數字與日期

_num_re = re.compile(r"[^\d.\-+eE]")


def num(s):
    """把 '1,234.5'、'--'、'X0.00'、'<p>+</p>' 等轉成 float；無法解析回傳 None。"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    if not s or s in ("--", "---", "-", "－", "N/A", "除權息", "除息", "除權"):
        return None
    s = s.replace(",", "")
    s = _num_re.sub("", s)
    if s in ("", "-", "+", ".", "-."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def sign_num(sign_html, value):
    """證交所漲跌欄位：符號在 HTML 裡、數值在另一欄。"""
    v = num(value)
    if v is None:
        return None
    if sign_html and "-" in re.sub(r"<[^>]+>", "", str(sign_html)).replace("color:green", ""):
        return -abs(v)
    if sign_html and "green" in str(sign_html):
        return -abs(v)
    return abs(v)


def ymd(d):
    return d.strftime("%Y%m%d")


def parse_ymd(s):
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def roc_to_ymd(s):
    """'1151016' 或 '115/10/16' → '20261016'"""
    s = str(s).strip().replace("/", "")
    if len(s) == 7:
        return "%04d%s" % (int(s[:3]) + 1911, s[3:])
    if len(s) == 8:
        return s
    return None


def today_tw():
    # 台灣時間（UTC+8），避免電腦時區設定不同造成誤判
    return (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()


def now_tw():
    return dt.datetime.utcnow() + dt.timedelta(hours=8)


def is_stock_code(code):
    """一般股票（4 碼數字）與 ETF（00 開頭），排除債券 ETF（B 結尾）。"""
    if re.fullmatch(r"[1-9]\d{3}", code):
        return True
    if re.fullmatch(r"00\d{2,4}[A-Z]?", code) and not code.endswith("B"):
        return True
    return False


def is_etf(code):
    return code.startswith("00")
