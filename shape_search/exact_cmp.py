# -*- coding: utf-8 -*-
import numpy as np, time
import engine_new as E
from exact_new import exact_value, build_masks, keys_table
from policy_eval_new import evaluate

if __name__ == "__main__":
    rng = np.random.default_rng(555)
    for S in [7, 8, 9, 10, 11]:
        ex, gr, la = [], [], []
        t0 = time.time()
        for t in range(20):
            idx = rng.choice(E.CNT, S, replace=False)
            masks = build_masks(idx); keys = keys_table(masks)
            ex.append(exact_value(masks, keys))
            gr.append(evaluate(keys, "greedy"))
            la.append(evaluate(keys, "lookahead"))
        ex = np.array(ex); gr = np.array(gr); la = np.array(la)
        print(f"S={S:2d} exact {ex.mean():.4f} | greedy {gr.mean():.4f} (+{100*(gr.mean()-ex.mean())/max(ex.mean(),1e-9):.1f}%)"
              f" | lookahead {la.mean():.4f} (+{100*(la.mean()-ex.mean())/max(ex.mean(),1e-9):.1f}%)"
              f"  time {time.time()-t0:.1f}s", flush=True)
