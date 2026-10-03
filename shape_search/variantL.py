"""Sensitivity: what if the L-tromino is the letter-L orientation (0,0),(1,0),(1,1)?"""
import numpy as np, time, random, math
N = 7
def bit(r,c): return 1 << (r*N+c)
SHAPES = {
 "H2":[(0,0),(0,1)], "V2":[(0,0),(1,0)],
 "L3":[(0,0),(1,0),(1,1)],           # letter L
 "SQ4":[(0,0),(0,1),(1,0),(1,1)],
 "DEER5":[(0,0),(0,1),(1,0),(1,1),(1,2)],
}
def placements(off):
    mr=max(r for r,c in off); mc=max(c for r,c in off); out=[]
    for r0 in range(N-mr):
        for c0 in range(N-mc):
            m=0
            for dr,dc in off: m|=bit(r0+dr,c0+dc)
            out.append(m)
    return out
order=["DEER5","SQ4","L3","H2","V2"]
pls=[placements(SHAPES[k]) for k in order]
cfg=[]
def rec(i,occ):
    if i==len(order): cfg.append(occ); return
    for m in pls[i]:
        if not (m&occ): rec(i+1,occ|m)
t0=time.time(); rec(0,0)
configs=np.array(cfg,dtype=np.uint64); n=len(configs)
print("variant letter-L total configs",n,"time",round(time.time()-t0,2))
freq=np.array([np.count_nonzero(configs & np.uint64(1<<c)) for c in range(49)])
print("prior map (%):")
for r in range(N):
    print(" ".join(f"{100.0*freq[r*N+c]/n:5.1f}" for c in range(N)))
print("argmax first move:", divmod(int(np.argmax(freq)),N), "p=", round(float(freq.max())/n,3))

W=(n+63)//64
B=np.zeros((49,W),dtype=np.uint64)
for c in range(49):
    has=((configs>>np.uint64(c))&np.uint64(1)).astype(np.uint64)
    pad=np.zeros(W*64-n,dtype=np.uint64); hh=np.concatenate([has,pad])
    pw=np.zeros(W,dtype=np.uint64)
    for j in range(64): pw|=(hh[j::64]<<np.uint64(j))
    B[c]=pw
ALL=np.full(W,np.uint64(0xFFFFFFFFFFFFFFFF)); rem=n%64
if rem: ALL[-1]=np.uint64((1<<rem)-1)
def counts(bits): return np.bitwise_count(B&bits).sum(axis=1,dtype=np.int64)
def ptotal(bits): return int(np.bitwise_count(bits).sum(dtype=np.int64))
def play(t):
    T=configs[t]; bits=ALL.copy(); e=0
    while True:
        tot=ptotal(bits); cs=counts(bits)
        det=(cs==0)|(cs==tot)
        if det.all(): break
        c=int(np.argmax(np.where(det,-1,cs)))
        if (T>>np.uint64(c))&np.uint64(1): bits=bits&B[c]
        else: e+=1; bits=bits&~B[c]
    return e
random.seed(7); t0=time.time()
es=[play(random.randrange(n)) for _ in range(100)]
print("greedy MC mean empties",round(float(np.mean(es)),3),"std",round(float(np.std(es)),3),"time",round(time.time()-t0,1))
