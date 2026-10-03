# -*- coding: utf-8 -*-
"""
New model engine:
  - Click a cell: if it belongs to an un-found shape, the WHOLE shape auto-reveals
    (so we learn all its cells are covered).  If empty, it is a wasted click.
  - Goal: find all 5 shapes (one cell each) with the fewest clicks.
  - Recommendation = the uncovered cell with the highest posterior occupancy
    probability, given which cells are known-covered and which are known-empty.
"""
import os, sys, time
import numpy as np

if getattr(sys, "frozen", False):
    HERE = sys._MEIPASS          # PyInstaller 打包后的资源目录
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
N = 7

_RNG = np.random.default_rng()

SHAPES = {
    "H2":   [(0, 0), (0, 1)],
    "V2":   [(0, 0), (1, 0)],
    "L3":   [(0, 0), (1, 0), (1, 1)],
    "SQ4":  [(0, 0), (0, 1), (1, 0), (1, 1)],
    "DEER5":[(0, 1), (1, 0), (1, 1), (2, 0), (2, 1)],
}
ORDER = ["DEER5", "SQ4", "L3", "H2", "V2"]
ANIMALS = {"DEER5": "鹿", "SQ4": "野猪", "L3": "兔子", "H2": "野鸭", "V2": "鸡"}

def bit(r, c):
    return 1 << (r * N + c)

def _placements(offsets):
    maxr = max(r for r, c in offsets)
    maxc = max(c for r, c in offsets)
    out = []
    for r0 in range(N - maxr):
        for c0 in range(N - maxc):
            m = 0
            for dr, dc in offsets:
                m |= bit(r0 + dr, c0 + dc)
            out.append(m)
    return out

ensure = None
if __name__ == "__main__" or True:
    if not os.path.exists(os.path.join(HERE, "data_new.npz")):
        raise SystemExit("缺少数据文件 data_new.npz（请把程序和 data_new.npz 放在一起）")
    _z = np.load(os.path.join(HERE, "data_new.npz"))
    OCC = _z["occ"]
    PS = _z["ps"]
    CNT = len(OCC)
    PSM = [_placements(SHAPES[s]) for s in ORDER]
    BITS = np.array([bit(r, c) for r in range(N) for c in range(N)], dtype=np.int64)

    PCELL = [
        [[i for i in range(N * N) if (m >> i) & 1] for m in PSM[s]]
        for s in range(5)
    ]


def detect_shapes(covered):
    """Given the set of covered cells (a union of fully-revealed shapes),
    return the list of (shape_idx, placement_codepoint) IF the decomposition
    is unambiguous, else [] (caller falls back to occupancy-only)."""
    covered = set(covered)
    if not covered:
        return []
    results = []

    def dfs(rem, used_types, assign):
        if not rem:
            results.append(list(assign))
            return
        if len(results) >= 4:   # safety cap
            return
        anchor = min(rem)
        for s in range(5):
            if s in used_types:
                continue
            for codep, cells in enumerate(PCELL[s]):
                if anchor not in cells:
                    continue
                if all(c in rem for c in cells):
                    for c in cells:
                        rem.discard(c)
                    used_types.add(s)
                    assign.append((s, codep))
                    dfs(rem, used_types, assign)
                    assign.pop()
                    used_types.discard(s)
                    for c in cells:
                        rem.add(c)

    dfs(set(covered), set(), [])
    if len(results) == 1:
        return results[0]
    return []


class Advisor:
    """Takes occupied / empty sets of known cells, returns the next best click."""

    def __init__(self):
        self.occ = OCC
        self.ps = PS
        self.psm = PSM
        self.bits = BITS
        self.bit_u64 = self.bits.astype(np.uint64)

    def _sel(self, occupied, empty, found=None):
        """found: optional list of (shape_idx, placement_codepoint) for shapes
        already revealed; using their identity tightens the posterior."""
        sel = np.ones(CNT, dtype=bool)
        if empty:
            em = 0
            for e in empty:
                em |= self.bit_u64[e]
            sel &= (self.occ & np.uint64(em)) == 0
        if occupied:
            om = 0
            for o in occupied:
                om |= self.bit_u64[o]
            sel &= (self.occ & np.uint64(om)) != 0
        if found:
            ps = self.ps  # (n,5)
            for s, codep in found:
                sel &= (ps[:, s] == int(codep))
        return sel

    def counts(self, sel):
        sub = self.occ[sel]
        cs = np.empty(N * N, dtype=np.int64)
        for c in range(N * N):
            cs[c] = np.count_nonzero(sub & self.bit_u64[c])
        return cs

    def next_move(self, occupied, empty, found=None):
        """occupied/empty: iterables of cell idx (0..48).  Returns (cell(r,c)|None, info)."""
        sel = self._sel(occupied, empty, found)
        total = int(sel.sum())
        if total == 0:
            return None, "观测与实际布局矛盾，请检查标记"
        cs = self.counts(sel)
        cand = [c for c in range(N * N) if (c not in occupied) and (c not in empty)]
        if not cand:
            return None, "所有格都已标记"
        best = max(cand, key=lambda c: cs[c])
        if cs[best] == 0:
            return None, "所有未标记的格子都确定是空的 —— 5 只已全部找到，结束"
        prob = cs[best] / total
        return (best // N, best % N), f"覆盖概率 {prob:.1%}（{total} 种可能布局一致）"

    def lookahead_next_move(self, occupied, empty, found=None, K=900, top=9, LIMIT=4000):
        """One-step lookahead, used ONLY when the remaining belief is small
        (sample noise would otherwise dominate).  Large belief -> greedy."""
        step0 = time.perf_counter()
        sel = self._sel(occupied, empty, found)
        total = int(sel.sum())
        if total == 0:
            return None, "观测与实际布局矛盾"
        cs = self.counts(sel)
        cand = [c for c in range(N * N) if (c not in occupied) and (c not in empty)]
        if not cand:
            return None, "所有格都已标记"
        idx = np.flatnonzero(sel)
        n_sel = len(idx)

        if n_sel > LIMIT:
            b = max(cand, key=lambda c: cs[c])
            return (b // N, b % N), f"剩余可能布局很多({total})，用贪心；候选其实接近"
        # small belief -> exact one-step lookahead over ALL remaining layouts
        samp = idx
        n_use = n_sel
        keys = [[0] * n_use for _ in range(49)]
        for pos, h in enumerate(samp):
            for s in range(5):
                m = int(self.psm[s][int(self.ps[int(h), s])])
                enc = (m << 3) | (s + 1)
                for i in range(49):
                    if (m >> i) & 1:
                        keys[i][pos] = enc
        sys.setrecursionlimit(1000000)
        memo = {}
        def rec(subset):
            m = len(subset)
            if m <= 1:
                return 0.0
            if subset in memo:
                return memo[subset]
            best_p = -1.0; best_groups = None
            for c in range(49):
                kc = keys[c]
                groups = {}
                for p in subset:
                    k = kc[p]
                    groups.setdefault(k, []).append(p)
                if len(groups) <= 1:
                    continue
                none_cnt = len(groups.get(0, []))
                p_occ = 1.0 - none_cnt / m
                if p_occ > best_p:
                    best_p = p_occ; best_groups = groups
            val = 0.0
            for k, poses in best_groups.items():
                cnt = len(poses)
                val += (cnt / m) * ((1.0 if k == 0 else 0.0) + rec(tuple(poses)))
            memo[subset] = val
            return val
        tops = sorted(cand, key=lambda c: -int(cs[c]))[:top]
        best_c = tops[0]; bestQ = 1e18
        n = n_use
        for c in tops:
            kc = keys[c]
            groups = {}
            for p in range(n):
                k = kc[p]
                groups.setdefault(k, []).append(p)
            if len(groups) <= 1:
                continue
            Q = 0.0
            for k, poses in groups.items():
                cnt = len(poses)
                Q += (cnt / n) * ((1.0 if k == 0 else 0.0) + rec(tuple(poses)))
            if Q < bestQ:
                bestQ = Q; best_c = c
        el = time.perf_counter() - step0
        return (best_c // N, best_c % N), f"精确前瞻({total} 种布局, {el:.1f}秒)"