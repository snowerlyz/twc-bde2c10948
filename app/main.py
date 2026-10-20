# -*- coding: utf-8 -*-
"""台股羅盤 主程式

  python main.py serve      啟動網頁（預設 http://localhost:8787），並在背景自動補資料
  python main.py update     抓取最新資料並重新分析（給每日排程用）
  python main.py analyze    只重新分析，不抓資料
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import threading
import time
import traceback

from util import DB, RESULTS, log, now_tw, read_json, write_json, LOGS

RESULT_VERSION = 2
STATUS_PATH = os.path.join(RESULTS, "status.json")
LOCK_PATH = os.path.join(DB, "update.lock")
_status_lock = threading.Lock()
_status = {"state": "idle"}


def set_status(**kw):
    with _status_lock:
        _status.update(kw)
        _status["at"] = now_tw().strftime("%Y-%m-%d %H:%M:%S")
        snap = dict(_status)
    try:
        write_json(STATUS_PATH, snap)
    except Exception:
        pass


def get_status():
    s = read_json(STATUS_PATH, {}) or {}
    return s


def _pid_alive(pid):
    """檢查上次更新的程式是否還在執行（視窗被關掉時，舊的鎖不應擋住新的更新）。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x1000, False, pid)
            if not h:
                return False
            code = ctypes.c_ulong()
            k.GetExitCodeProcess(h, ctypes.byref(code))
            k.CloseHandle(h)
            return code.value == 259
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_lock():
    if os.path.exists(LOCK_PATH):
        try:
            age = time.time() - os.path.getmtime(LOCK_PATH)
            with open(LOCK_PATH) as f:
                pid = f.read().strip()
        except OSError:
            age, pid = 0, None
        if age < 3 * 3600 and _pid_alive(pid):
            return False
    with open(LOCK_PATH, "w") as f:
        f.write(str(os.getpid()))
    return True


def _touch_lock():
    try:
        os.utime(LOCK_PATH, None)
    except OSError:
        pass


def _release_lock():
    try:
        os.remove(LOCK_PATH)
    except OSError:
        pass


def analyze(prog=None):
    # 每次分析都重新載入程式，更新程式檔後不必重開台股羅盤
    import importlib
    import engine as _e
    import derivs as _d
    import daytrade as _dt
    importlib.reload(_e)
    importlib.reload(_d)
    importlib.reload(_dt)
    from engine import run_engine, stock_detail, HN, ENGINE_VERSION
    from derivs import evaluate_warrants, evaluate_futures, hist_vol

    res, D, A_all = run_engine(prog)
    stocks = res["stocks"]
    try:
        dt, dt_scores = _dt.run(D, A_all, (lambda m: prog.set(msg=m)) if prog else None)
    except Exception as e:
        log("當沖模型失敗：%s\n%s" % (e, traceback.format_exc()))
        dt, dt_scores = None, {}
    for r in stocks:
        if r["c"] in dt_scores:
            r["dt"] = dt_scores[r["c"]]
    by_code = {r["c"]: r for r in stocks}
    mkt = res["market"]

    def score_of(code):
        if code in ("IX0001", "TAIEX"):
            return [mkt["horizons"][h]["score"] for h in HN]
        r = by_code.get(code)
        return r["s"] if r else None

    def close_of(code):
        r = by_code.get(code)
        return r["px"] if r else None

    def hv_of(code):
        if code in ("IX0001",):
            return hist_vol(D.mkt["taiex"])
        i = D.idx.get(code)
        if i is None:
            return None
        return hist_vol(A_all[i])

    name_to_code = {v: k for k, v in D.names.items()}
    name_to_code["臺股指數"] = "IX0001"
    if prog:
        prog.set(msg="評估權證")
    wmap, wpicks = evaluate_warrants(D.days[-1], hv_of, score_of, name_to_code)
    if prog:
        prog.set(msg="評估期貨")
    fut = evaluate_futures(D, mkt, score_of, close_of)

    # ---- 寫出結果
    if prog:
        prog.set(msg="寫入結果")
    sdir = os.path.join(RESULTS, "stock")
    os.makedirs(sdir, exist_ok=True)
    for code, (i, hz) in res["details"].items():
        det = stock_detail(code, i, hz, D, res["FA"], A_all)
        w = wmap.get(code)
        if w:
            det["warrants"] = {"n_call": w["n_call"], "n_put": w["n_put"],
                               "calls": w["calls"][:5], "puts": w["puts"][:5]}
        det["fut"] = next((f for f in fut["stock"] if f["stock"] == code), None)
        det["dt"] = dt_scores.get(code)
        write_json(os.path.join(sdir, code + ".json"), det)
    wdir = os.path.join(RESULTS, "warrants")
    os.makedirs(wdir, exist_ok=True)
    for u, w in wmap.items():
        if u:
            write_json(os.path.join(wdir, u + ".json"), w)
    write_json(os.path.join(RESULTS, "warrant_picks.json"), {"day": D.days[-1], "picks": wpicks,
                                                             "underlyings": sorted(
                                                                 [{"u": u, "n": (by_code.get(u) or {}).get("n") or ("臺股指數" if u == "IX0001" else u),
                                                                   "nc": w["n_call"], "np": w["n_put"]} for u, w in wmap.items() if u],
                                                                 key=lambda x: -(x["nc"] + x["np"]))})
    write_json(os.path.join(RESULTS, "futures.json"), fut)
    if dt:
        write_json(os.path.join(RESULTS, "daytrade.json"), dt)
    write_json(os.path.join(RESULTS, "model.json"), res["model"])
    snapinfo = read_json(os.path.join(DB, "snapshot", "info.json"), {}) or {}
    latest = {
        "day": D.days[-1], "days": D.T, "first_day": D.days[0],
        "generated": now_tw().strftime("%Y-%m-%d %H:%M"),
        "market": {k: v for k, v in mkt.items()},
        "industries": res["industries"],
        "stocks": stocks,
        "model": {hn: {k: res["model"]["horizons"][hn][k] for k in ("label", "top_hit", "base_hit", "spread_avg", "spread_win", "eval_days", "ic_avg")}
                  for hn in HN},
        "snapshot": snapinfo,
        "version": RESULT_VERSION,
        "engine": ENGINE_VERSION,
        "n_warrants": sum(w["n_call"] + w["n_put"] for w in wmap.values()),
    }
    write_json(os.path.join(RESULTS, "latest.json"), latest)
    log("分析完成：%s，%d 檔股票" % (D.days[-1], len(stocks)))
    return latest


def update(full=True, total_days=250, chip_days=120):
    from collector import Progress, run_collect
    if not _acquire_lock():
        log("另一個更新正在進行，略過")
        return False
    errors_all = []

    def cb(s):
        _touch_lock()
        set_status(state="running", phase=s.get("phase"), done=s.get("done"), total=s.get("total"),
                   msg=s.get("msg"), errors=s.get("errors", [])[-5:])

    prog = Progress(cb)
    set_status(state="running", phase="collect", msg="開始更新", started=now_tw().strftime("%Y-%m-%d %H:%M:%S"),
               done=0, total=1, errors=[])
    ok = True
    try:
        def on_stage(stage, changed):
            latest = read_json(os.path.join(RESULTS, "latest.json"), {}) or {}
            try:
                import importlib
                import engine as _e
                importlib.reload(_e)
                ev = _e.ENGINE_VERSION
            except Exception:
                ev = None
            if not changed and latest.get("version") == RESULT_VERSION and latest.get("engine") == ev:
                return
            try:
                analyze(prog)
                set_status(ready=True)
            except Exception as e:
                log("分析失敗：%s\n%s" % (e, traceback.format_exc()))
                prog.error("分析失敗：%s" % e)

        run_collect(prog, total_days=total_days if full else 70, chip_days=chip_days,
                    quick_days=70, on_stage=on_stage)
        errors_all = prog.state.get("errors", [])
    except Exception as e:
        ok = False
        log("更新失敗：%s\n%s" % (e, traceback.format_exc()))
        errors_all = prog.state.get("errors", []) + [str(e)]
    finally:
        _release_lock()
        set_status(state="idle", phase="done", msg="更新完成" if ok else "更新失敗",
                   finished=now_tw().strftime("%Y-%m-%d %H:%M:%S"), errors=errors_all[-5:])
    return ok


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "update":
        update()
    elif cmd == "analyze":
        analyze()
    elif cmd == "serve":
        from server import serve
        port = int(os.environ.get("TWC_PORT", "8787"))
        serve(port, update)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
