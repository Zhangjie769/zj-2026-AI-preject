# -*- coding: utf-8 -*-
import random
import engine_new as E

def cells(m):
    return {i for i in range(49) if (m >> i) & 1}

random.seed(1)
ok = 0
amb = 0
for trial in range(300):
    Ti = random.randrange(E.CNT)
    sm = [int(E.PSM[s][int(E.PS[Ti, s])]) for s in range(5)]
    k = random.randrange(1, 6)
    chosen = set(range(k))           # which shapes we "found"
    covered = set()
    for s in chosen:
        covered |= cells(sm[s])
    found = E.detect_shapes(covered)
    if not found:
        amb += 1
        continue
    got = {s for s, _ in found}
    if got == chosen:
        ok += 1
    else:
        # check whether tiling actually covers
        print("MISMATCH trial", trial, "chosen", chosen, "got", got)
        break
else:
    print(f"ok {ok}, ambiguous {amb} (fallback), total 300")