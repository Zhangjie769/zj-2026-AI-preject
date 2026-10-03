from solver import Solver, N

s = Solver()

def fmt_obs(obs):
    return "{}" if not obs else " ".join(f"({r},{c})={'#' if v else '.'}" for (r, c), v in sorted(obs.items()))

def dfs(obs, depth, indent=0):
    if depth == 0:
        return
    mv, why = s.next_move(obs)
    pad = "  " * indent
    if mv is None:
        print(f"{pad}[{fmt_obs(obs)}] -> resolved")
        return
    r, c = mv
    print(f"{pad}[{fmt_obs(obs)}] -> click ({r},{c})  {why}")
    for val in (1, 0):
        o2 = dict(obs)
        o2[mv] = val
        dfs(o2, depth - 1, indent + 1)

dfs({}, 3)
