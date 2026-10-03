# -*- coding: utf-8 -*-
import time, numpy as np
import engine_new as E
from exact_new import exact_value, greedy_value, build_masks, keys_table
from policy_eval_new import evaluate

def run(S, trials=3, cap=45.0):
    rng = np.random.default_rng(3)
    res = {"exact": [], "greedy": [], "la": []}
    ok = True
    for k in range(trials):
        idx = rng.choice(E.CNT, S, replace=False)
        masks = build_masks(idx); keys = keys_table(masks)
        t = time.time(); x = exact_value(masks, keys); dt = time.time() - t
        if dt > cap:
            ok = False
            break
        g = greedy_value(masks, keys)
        la = evaluate(keys, "lookahead")
        res["exact"].append(x); res["greedy"].append(g); res["la"].append(la)
    print(f"S={S:4d} trials={len(res['exact'])} exact {np.mean(res['exact']) if res['exact'] else float('nan'):.4f} "
          f"greedy {np.mean(res['greedy']) if res['greedy'] else float('nan'):.4f} "
          f"lookahead {np.mean(res['la']) if res['la'] else float('nan'):.4f} "
          f"la==exact? {all(abs(a-b) < 1e-9 for a,b in zip(res['la'], res['exact']))} "
          f"(exact time/trial {dt:.1f}s)", flush=True)
    return ok

if __name__ == "__main__":
    for S in [20, 30, 50, 100]:
        if not run(S, trials=2 if S >= 100 else 3):
            print("give up at S =", S); break