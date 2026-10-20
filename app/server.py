# -*- coding: utf-8 -*-
"""本機網頁伺服器：提供網頁介面與分析結果，並在背景定時自動更新資料。"""
import gzip
import json
import mimetypes
import os
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from util import DATA, RESULTS, ROOT, log, now_tw, read_json, write_json

WEB = os.path.join(ROOT, "web")
WATCH_PATH = os.path.join(DATA, "watchlist.json")
_update_thread = None
_update_fn = None
_ut_lock = threading.Lock()

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")


def start_update():
    global _update_thread
    with _ut_lock:
        if _update_thread and _update_thread.is_alive():
            return False
        _update_thread = threading.Thread(target=_update_fn, daemon=True)
        _update_thread.start()
        return True


def updating():
    return bool(_update_thread and _update_thread.is_alive())


def lan_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return ips


SAFE = re.compile(r"^[A-Za-z0-9]{1,12}$")


class Handler(BaseHTTPRequestHandler):
    server_version = "TWCompass/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", cache="no-store"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        gz = "gzip" in (self.headers.get("Accept-Encoding") or "") and len(body) > 2048 and (
            ctype.startswith("application/json") or ctype.startswith("text/"))
        if gz:
            body = gzip.compress(body, 5)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False, separators=(",", ":")))

    def _file_json(self, path):
        if not os.path.exists(path):
            return self._json({"error": "notfound"}, 404)
        with open(path, "rb") as f:
            self._send(200, f.read())

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path.startswith("/api/"):
                return self.api_get(path[5:])
            return self.static(path)
        except BrokenPipeError:
            pass
        except Exception as e:
            log("伺服器錯誤 %s：%s" % (path, e))
            try:
                self._json({"error": str(e)}, 500)
            except Exception:
                pass

    def do_POST(self):
        path = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        if path == "/api/update":
            started = start_update()
            return self._json({"started": started, "running": updating()})
        if path == "/api/watchlist":
            try:
                lst = json.loads(body.decode("utf-8"))
                lst = [str(x) for x in lst if SAFE.match(str(x))][:200]
                write_json(WATCH_PATH, lst)
                return self._json({"ok": True, "list": lst})
            except Exception as e:
                return self._json({"error": str(e)}, 400)
        self._json({"error": "notfound"}, 404)

    def api_get(self, p):
        if p == "latest":
            return self._file_json(os.path.join(RESULTS, "latest.json"))
        if p == "status":
            st = read_json(os.path.join(RESULTS, "status.json"), {}) or {}
            st["running"] = updating() or st.get("state") == "running" and _recent(st.get("at"))
            lp = os.path.join(RESULTS, "latest.json")
            st["has_data"] = os.path.exists(lp)
            st["latest_mtime"] = int(os.path.getmtime(lp)) if st["has_data"] else None
            st["lan"] = lan_ips()
            st["port"] = self.server.server_address[1]
            st["now"] = now_tw().strftime("%Y-%m-%d %H:%M:%S")
            return self._json(st)
        if p == "model":
            return self._file_json(os.path.join(RESULTS, "model.json"))
        if p == "futures":
            return self._file_json(os.path.join(RESULTS, "futures.json"))
        if p == "daytrade":
            return self._file_json(os.path.join(RESULTS, "daytrade.json"))
        if p in ("sectors", "global", "report", "live", "recs"):
            return self._file_json(os.path.join(RESULTS, p + ".json"))
        if p == "tuning":
            return self._file_json(os.path.join(RESULTS, "tuning.json"))
        if p == "warrant_picks":
            return self._file_json(os.path.join(RESULTS, "warrant_picks.json"))
        if p == "watchlist":
            return self._json(read_json(WATCH_PATH, []) or [])
        m = re.match(r"^(stock|warrants)/([A-Za-z0-9]+)$", p)
        if m and SAFE.match(m.group(2)):
            sub = "stock" if m.group(1) == "stock" else "warrants"
            return self._file_json(os.path.join(RESULTS, sub, m.group(2) + ".json"))
        return self._json({"error": "notfound"}, 404)

    def static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        full = os.path.normpath(os.path.join(WEB, path.lstrip("/")))
        if not full.startswith(os.path.normpath(WEB)) or not os.path.isfile(full):
            full = os.path.join(WEB, "index.html")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript") or ctype.endswith("json"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype, cache="no-cache")


def _recent(at):
    try:
        t = time.mktime(time.strptime(at, "%Y-%m-%d %H:%M:%S"))
        n = time.mktime(now_tw().timetuple())
        return n - t < 600
    except Exception:
        return False


def scheduler():
    """伺服器開著的時候，平日下午到晚上每 20 分鐘檢查一次有沒有新資料。"""
    time.sleep(5)
    start_update()   # 開啟時先補一次
    while True:
        time.sleep(20 * 60)
        n = now_tw()
        if n.weekday() < 5 and (14 <= n.hour <= 23):
            start_update()


def serve(port, update_fn):
    global _update_fn
    _update_fn = update_fn
    httpd = None
    for p in range(port, port + 10):
        try:
            httpd = ThreadingHTTPServer(("0.0.0.0", p), Handler)
            port = p
            break
        except OSError:
            continue
    if not httpd:
        raise SystemExit("找不到可用的連接埠")
    write_json(os.path.join(DATA, "server.json"), {"port": port, "pid": os.getpid()})
    threading.Thread(target=scheduler, daemon=True).start()
    if os.environ.get("TWC_OPEN") == "1":
        def _open():
            time.sleep(1.5)
            try:
                import webbrowser
                webbrowser.open("http://localhost:%d/" % port)
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()
    log("台股羅盤已啟動：http://localhost:%d  （同一個 Wi-Fi 的手機：%s）" % (
        port, "、".join("http://%s:%d" % (ip, port) for ip in lan_ips()) or "無"))
    log("這個視窗請保持開著；關掉它台股羅盤就會停止。")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
