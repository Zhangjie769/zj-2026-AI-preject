"""Validate solver.py's interactive policy by playing whole games."""
import random
from solver import Solver, N

s = Solver()
random.seed(5)
results = []
for g in range(40):
    t = random.randrange(s.n)
    T = int(s.configs[t])
    obs = {}
    empties = 0
    clicks = 0
    while True:
        mv, why = s.next_move(obs)
        if mv is None:
            break
        r, c = mv
        occ = (T >> (r * N + c)) & 1
        obs[(r, c)] = occ
        clicks += 1
        if not occ:
            empties += 1
    # every occupied cell must be known/clicked; count total needed = 16 + empties
    results.append(empties)
    if g < 5:
        print(f"game {g}: empties={empties} forced/ambiguous clicks={clicks} total={16+empties}")

import statistics
print("mean empties over 40 games:", round(statistics.mean(results), 3),
      "min", min(results), "max", max(results), "mean total", round(16 + statistics.mean(results), 3))
