# -*- coding: utf-8 -*-
import numpy as np
N = 7
def bit(r,c): return 1 << (r*N+c)
def placements(off):
    mr=max(r for r,c in off); mc=max(c for r,c in off); out=[]
    for r0 in range(N-mr):
        for c0 in range(N-mc):
            m=0
            for dr,dc in off: m|=bit(r0+dr,c0+dc)
            out.append(m)
    return out

def first_move(deer):
    shapes={"H2":[(0,0),(0,1)],"V2":[(0,0),(1,0)],"L3":[(0,0),(0,1),(1,0)],
            "SQ4":[(0,0),(0,1),(1,0),(1,1)],"DEER5":deer}
    order=["DEER5","SQ4","L3","H2","V2"]
    pl=[placements(shapes[o]) for o in order]
    freq=np.zeros(49,dtype=np.int64); total=[0]
    def rec(i,occ):
        if i==5:
            total[0]+=1
            for c in range(49):
                if (occ>>c)&1: freq[c]+=1
            return
        for m in pl[i]:
            if not (m&occ): rec(i+1,occ|m)
    rec(0,0)
    idx=int(np.argmax(freq))
    return total[0], divmod(idx,N), round(100*freq[idx]/total[0],1)

print("用户最初给的鹿 [(0,0),(0,1),(1,0),(1,1),(1,2)]:")
print("  total, first move, prob =", first_move([(0,0),(0,1),(1,0),(1,1),(1,2)]))
print("截图里看到的鹿 [(0,1),(1,0),(1,1),(2,0),(2,1)]:")
print("  total, first move, prob =", first_move([(0,1),(1,0),(1,1),(2,0),(2,1)]))
