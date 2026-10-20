import os, sys, json, time
os.environ.setdefault("TWC_DATA", "/tmp/twc_test_data")
sys.path.insert(0, "/home/claude/twcompass/app"); sys.path.insert(0, "/home/claude/twcompass/test")
import util
util.HOST_GAP.clear()
import mock, collector
def f(url, data=None, **kw): return mock.handle(url, data)
def fj(url, **kw): return json.loads(mock.handle(url))
collector.fetch = f; collector.fetch_json = fj
import extra
def nofetch(*a, **k): raise Exception('mock: no network')
extra.fetch = nofetch; extra.fetch_json = nofetch
import finhist
finhist.fetch = nofetch
import main
t=time.time()
main.update(total_days=int(sys.argv[1]) if len(sys.argv)>1 else 250)
print("TOTAL", time.time()-t)
