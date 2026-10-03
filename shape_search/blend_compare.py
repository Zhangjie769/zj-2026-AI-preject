import numpy as np, time
from policy_compare import mc

N = 150
t0 = time.time()
for pol, lam in [("greedy", 1.0), ("info", 0.0), ("blend", 0.25), ("blend", 0.5),
                 ("blend", 1.0), ("blend", 2.0), ("blend", 4.0)]:
    es = mc(pol, lam, N, 2024)
    print(f"{pol}_{lam}: mean {es.mean():.4f} std {es.std():.3f} SE {es.std()/np.sqrt(N):.3f} "
          f"min {es.min()} max {es.max()}  time {time.time()-t0:.1f}s", flush=True)
