# -*- coding: utf-8 -*-
"""大盤預測（加權指數）：短中長期的上漲機率、到期時的漲跌範圍、期間內可能的高點與低點。

資料：加權指數 2000 年以來的每日收盤（Yahoo，db/twii_long.json）。只有兩年資料時，
「上漲比例」與「漲跌範圍」會被這兩年的大多頭帶偏，所以用二十多年的歷史當基準。

1. 上漲機率：台股主模型的大盤分數（模型讀數 × 可信度 ＋ 歷史上漲比例 ×（1 − 可信度））換算而來；
   歷史上漲比例＝最近一年的比例，向「二十多年長期比例」收斂（一年內真正獨立的樣本不多）。
   用 2006～2026 年逐日回測（walk-forward）：這樣算的機率比只看最近一年準（Brier 分數較低）。
2. 漲跌範圍：把過去每一段 h 天的漲跌，除以「當時的波動度」（近 20 天與近 250 天每日波動各半），
   得到不受行情冷熱影響的標準化分布；乘上今天的波動度，再整體平移到「上漲機率＝第 1 點的機率」，
   取 10%／50%／90% 位置。逐日回測：8 成區間實際涵蓋約 78%～81%。
3. 期間內高點／低點：同樣做法，看 h 天內收盤的最高點與最低點。
全程只用「當天以前」已知的資料。
"""
import bisect
import math
import os

from util import DB, read_json

PATH = os.path.join(DB, "twii_long.json")
MIN_SAMPLES = 500
SHRINK_W = 10.0


class Long:
    def __init__(self, series):
        self.dates = sorted(series)
        self.c = [series[d] for d in self.dates]
        n = len(self.c)
        r = [0.0] + [math.log(self.c[i] / self.c[i - 1]) if self.c[i - 1] > 0 and self.c[i] > 0 else 0.0 for i in range(1, n)]
        self.r = r
        p1, p2 = [0.0], [0.0]
        for x in r:
            p1.append(p1[-1] + x)
            p2.append(p2[-1] + x * x)

        def var(i, w):
            a = max(1, i - w + 1)
            m = i - a + 1
            if m < 10:
                return None
            s1, s2 = p1[i + 1] - p1[a], p2[i + 1] - p2[a]
            return max(0.0, s2 / m - (s1 / m) ** 2)
        self.sig = []
        for i in range(n):
            v20, v250 = var(i, 20), var(i, 250)
            self.sig.append(math.sqrt(0.5 * v20 + 0.5 * v250) if v20 is not None and v250 is not None and i >= 250 else None)
        self._cache = {}

    def idx_before(self, day):
        """日期早於 day 的最後一個位置。"""
        return bisect.bisect_left(self.dates, day) - 1

    def ups(self, h):
        if ("u", h) not in self._cache:
            n = len(self.c)
            cum = [0]
            for j in range(n - h):
                cum.append(cum[-1] + (1 if self.c[j + h] > self.c[j] else 0))
            self._cache[("u", h)] = cum
        return self._cache[("u", h)]

    def prior(self, day, h):
        """day 以前「已經揭曉」的所有 h 天漲跌中，上漲的比例。"""
        k = self.idx_before(day) + 1          # dates[:k] < day
        m = k - h                              # 第 j 段（j < m）的結果在 day 以前已知
        if m < MIN_SAMPLES:
            return None
        cum = self.ups(h)
        return cum[m] / m

    def arrays(self, h):
        """每個起點 j 的 h 天標準化漲跌、期間最高、期間最低（結果在位置 j+h 揭曉）。"""
        if ("a", h) not in self._cache:
            n = len(self.c)
            z, zx, zn = [None] * n, [None] * n, [None] * n
            for j in range(250, n - h):
                s = self.sig[j]
                if not s:
                    continue
                d = s * math.sqrt(h)
                w = self.c[j + 1:j + h + 1]
                z[j] = math.log(self.c[j + h] / self.c[j]) / d
                zx[j] = math.log(max(w) / self.c[j]) / d
                zn[j] = math.log(min(w) / self.c[j]) / d
            self._cache[("a", h)] = (z, zx, zn)
        return self._cache[("a", h)]

    def zdist(self, h, k_end, extremes=True):
        """位置 < k_end 已揭曉（j + h < k_end）的分布，已排序。"""
        z, zx, zn = self.arrays(h)
        m = max(0, k_end - h)
        a = sorted(x for x in z[:m] if x is not None)
        if not extremes:
            return a, None, None
        return a, sorted(x for x in zx[:m] if x is not None), sorted(x for x in zn[:m] if x is not None)


def _q(xs, p):
    if not xs:
        return None
    x = p * (len(xs) - 1)
    i = int(x)
    f = x - i
    return xs[i] if i + 1 >= len(xs) else xs[i] * (1 - f) + xs[i + 1] * f


def load(D=None):
    j = read_json(PATH, {}) or {}
    s = j.get("s") or {}
    if len(s) < 2000:
        return None
    if D is not None:
        # 和本地的收盤資料對齊：只用到最新交易日（避免 Yahoo 多出還沒收盤的今天）
        last = D.days[-1]
        s = {d: v for d, v in s.items() if d <= last}
    return Long(s)


def coverage(L, h, years=5, step=5):
    """最近幾年逐日回測：8 成區間的實際涵蓋率（只用當時已知的資料）。"""
    n = len(L.c)
    start = max(1500, n - 250 * years)
    hit = tot = 0
    z = None
    for t in range(start, n - h, step):
        s = L.sig[t]
        if not s:
            continue
        if (t - start) % 20 == 0 or z is None:
            z, _, _ = L.zdist(h, t + 1, extremes=False)     # 每 20 天更新一次分布，省時間
        if len(z) < MIN_SAMPLES:
            continue
        d = s * math.sqrt(h)
        r = math.log(L.c[t + h] / L.c[t])
        tot += 1
        hit += 1 if _q(z, 0.1) * d <= r <= _q(z, 0.9) * d else 0
    return round(hit / tot, 3) if tot else None


def forecast(L, day, level, h, p_up):
    """回傳今天的預測：到期時的中間值與 8 成範圍、期間內高點／低點（皆為指數點數與漲跌幅）。"""
    k = L.idx_before(day) + 1
    t = L.idx_before(day + "z")              # 今天（day 當天）在長期序列的位置
    if t < 0 or L.dates[t] != day:
        t = k - 1
    s = L.sig[t] if 0 <= t < len(L.sig) else None
    if not s:
        return None
    z, zx, zn = L.zdist(h, t + 1)
    if len(z) < MIN_SAMPLES:
        return None
    d = s * math.sqrt(h)
    # 整體平移，讓「到期時上漲」的機率＝p_up（和方向判斷一致）
    sh = -_q(z, 1 - p_up) * d
    q = {p: _q(z, p) * d + sh for p in (0.1, 0.5, 0.9)}
    mx = {p: max(0.0, _q(zx, p) * d + sh) for p in (0.5, 0.9)}
    mn = {p: min(0.0, _q(zn, p) * d + sh) for p in (0.1, 0.5)}
    lv = lambda x: round(level * math.exp(x), 0)
    pc = lambda x: round(math.exp(x) - 1, 4)
    return {"p_up": round(p_up, 3), "med": pc(q[0.5]), "lo": pc(q[0.1]), "hi": pc(q[0.9]),
            "med_lv": lv(q[0.5]), "lo_lv": lv(q[0.1]), "hi_lv": lv(q[0.9]),
            "max50": pc(mx[0.5]), "max90": pc(mx[0.9]), "min50": pc(mn[0.5]), "min10": pc(mn[0.1]),
            "max90_lv": lv(mx[0.9]), "min10_lv": lv(mn[0.1]), "max50_lv": lv(mx[0.5]), "min50_lv": lv(mn[0.5]),
            "vol": round(s * math.sqrt(250), 4), "years": round(len(L.c) / 250.0, 1), "since": L.dates[0][:4]}
