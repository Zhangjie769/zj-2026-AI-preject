"""
Optimal-ish solver for the 7x7 hidden-shapes game.

Shapes (fixed orientation, translations only, no rotation/flip):
  H2   horizontal domino : (0,0),(0,1)
  V2   vertical domino   : (0,0),(1,0)
  L3   L-tromino         : (0,0),(0,1),(1,0)
  SQ4  square tetromino  : (0,0),(0,1),(1,0),(1,1)
  DEER pentomino         : (0,0),(0,1),(1,0),(1,1),(1,2)

Model:
  * The five shapes are placed on disjoint cells of a 7x7 board.
  * Prior = uniform over all 11,018,662 valid layouts.
  * A click on a cell reveals ONLY whether that cell is covered (occupied) or not.
  * Goal: click every covered cell.  Every covered cell must be clicked, so the
    only thing a strategy can minimise is the number of EMPTY clicks (wasted clicks).
    total clicks = 16 + (number of empty clicks).

Bayesian engine:
  * Precompute the set of all valid layouts once (configs.npy).
  * Represent the set of layouts consistent with the observations as a bitset
    over the 11M layouts.  Conditioning on "cell c occupied/empty" is a bitwise
    AND with the data of that cell.
  * posterior occupancy probability of a cell = (#consistent layouts covering it)
    / (#consistent layouts).

Policy:
  * greedy: click the unrevealed cell with the greatest posterior occupancy
    probability.  (Deterministic optimal for 2 hypotheses; empirically strong.)
  * info:   click the cell with the greatest expected information gain.
  * blend:  information gain + lambda * posterior probability.

Usage (interactive):
    python solver.py
    then type observations, e.g.  "(5,1)=1"  meaning row 5 col 1 is occupied,
    "(3,2)=0" meaning empty.  Type "next" to get the recommended next click,
    "show" to print the posterior occupancy map, "quit" to exit.
"""
import os, sys, math
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "configs.npy")
BCFG = os.path.join(HERE, "bitsets_B.npy")
N = 7

SHAPES = {
    "H2":   [(0, 0), (0, 1)],
    "V2":   [(0, 0), (1, 0)],
    "L3":   [(0, 0), (0, 1), (1, 0)],
    "SQ4":  [(0, 0), (0, 1), (1, 0), (1, 1)],
    "DEER5":[(0, 0), (0, 1), (1, 0), (1, 1), (1, 2)],
}
ORDER = ["DEER5", "SQ4", "L3", "H2", "V2"]


def enumerate_configs():
    def placements(offsets):
        maxr = max(r for r, c in offsets)
        maxc = max(c for r, c in offsets)
        out = []
        for r0 in range(N - maxr):
            for c0 in range(N - maxc):
                m = 0
                for dr, dc in offsets:
                    m |= 1 << ((r0 + dr) * N + (c0 + dc))
                out.append(m)
        return out
    pls = [placements(SHAPES[nm]) for nm in ORDER]
    res = []
    def rec(i, occ):
        if i == len(ORDER):
            res.append(occ)
            return
        for m in pls[i]:
            if not (m & occ):
                rec(i + 1, occ | m)
    rec(0, 0)
    return np.array(res, dtype=np.uint64)


class Solver:
    def __init__(self, configs=None):
        if configs is None:
            if os.path.exists(CFG):
                configs = np.load(CFG)
            else:
                configs = enumerate_configs()
                np.save(CFG, configs)
        self.configs = configs
        self.n = len(configs)
        self.W = (self.n + 63) // 64
        if os.path.exists(BCFG):
            self.B = np.load(BCFG)
            self.W = self.B.shape[1]
        else:
            self.B = self._build_bitsets()
            try:
                np.save(BCFG, self.B)
            except Exception:
                pass
        self.ALL = np.full(self.W, np.uint64(0xFFFFFFFFFFFFFFFF), dtype=np.uint64)
        rem = self.n % 64
        if rem:
            self.ALL[-1] = np.uint64((1 << rem) - 1)

    def _build_bitsets(self):
        B = np.zeros((N * N, self.W), dtype=np.uint64)
        for c in range(N * N):
            has = ((self.configs >> np.uint64(c)) & np.uint64(1)).astype(np.uint64)
            pad = np.zeros(self.W * 64 - self.n, dtype=np.uint64)
            hh = np.concatenate([has, pad])
            pw = np.zeros(self.W, dtype=np.uint64)
            for j in range(64):
                pw |= (hh[j::64] << np.uint64(j))
            B[c] = pw
        return B

    def condition(self, obs):
        """obs: dict (r,c) -> 0 (empty) or 1 (occupied)."""
        bits = self.ALL.copy()
        for (r, c), v in obs.items():
            idx = r * N + c
            if v:
                bits = bits & self.B[idx]
            else:
                bits = bits & ~self.B[idx]
        return bits

    def analyze(self, obs):
        bits = self.condition(obs)
        total = int(np.bitwise_count(bits).sum(dtype=np.int64))
        counts = np.bitwise_count(self.B & bits).sum(axis=1, dtype=np.int64) if total else np.zeros(N * N, dtype=np.int64)
        return bits, total, counts

    def next_move(self, obs, policy="greedy", lam=1.0):
        bits, total, counts = self.analyze(obs)
        if total == 0:
            return None, "inconsistent observations"
        determined = (counts == 0) | (counts == total)
        # cells already observed
        observed = np.zeros(N * N, dtype=bool)
        for (r, c) in obs:
            observed[r * N + c] = True
        # Any determined-and-unobserved occupied cell should simply be clicked (free).
        forced = [i for i in range(N * N) if counts[i] == total and not observed[i]]
        if forced:
            i = forced[0]
            return divmod(i, N), "forced occupied (free, 100% sure)"
        amb = ~determined & ~observed
        if not amb.any():
            # everything determined, any remaining occupied cells are known
            return None, "resolved"
        p = counts.astype(np.float64) / total
        if policy == "greedy":
            score = p.copy()
        elif policy == "info":
            score = self._entropy_gain(counts, total)
        elif policy == "blend":
            score = self._entropy_gain(counts, total) + lam * p
        else:
            raise ValueError(policy)
        score[~amb] = -1e18
        i = int(np.argmax(score))
        return divmod(i, N), f"p={p[i]:.3f}"

    @staticmethod
    def _entropy_gain(counts, total):
        t = float(total)
        H0 = math.log(t)
        cy = counts.astype(np.float64)
        cn = t - cy
        out = np.zeros_like(cy)
        m = (cy > 0) & (cy < t)
        out[m] = H0 - (cy[m] / t) * np.log(cy[m]) - (cn[m] / t) * np.log(cn[m])
        return out

    def show(self, obs=None):
        bits, total, counts = self.analyze(obs or {})
        print(f"consistent layouts: {total}")
        for r in range(N):
            row = []
            for c in range(N):
                if obs and (r, c) in obs:
                    row.append("  O " if obs[(r, c)] else "  . ")
                else:
                    row.append(f"{100.0*counts[r*N+c]/max(total,1):4.0f}")
            print(" ".join(row))


def _parse(tok):
    tok = tok.strip().replace(" ", "")
    if "=" not in tok:
        return None
    pos, val = tok.split("=")
    pos = pos.strip("()[]")
    r, c = pos.split(",")
    return (int(r), int(c)), int(val)


if __name__ == "__main__":
    s = Solver()
    obs = {}
    print("Bayesian hidden-shapes solver. Commands: (r,c)=1 / (r,c)=0, 'next', 'show', 'undo', 'quit'")
    history = []
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if line in ("quit", "q", "exit"):
            break
        if line == "show":
            s.show(obs)
            continue
        if line == "undo":
            if history:
                k = history.pop()
                del obs[k]
            continue
        if line == "next":
            mv, why = s.next_move(obs)
            print("next click:", mv, "|", why)
            continue
        parsed = _parse(line)
        if parsed:
            k, v = parsed
            obs[k] = v
            history.append(k)
            print("recorded", k, "=", v)
        else:
            print("unrecognised. use (r,c)=0 or (r,c)=1")
