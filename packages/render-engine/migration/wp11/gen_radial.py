import json, sys, random, itertools
from evodesign.agentic_system.render_engine.excalidraw import radial_concept_compactor as rc
random.seed(5)
out = {"branch": [], "slots": [], "perms": []}
for i in range(300):
    n = random.randint(0, 8)
    pool = ["upper_left", "upper_right", "lower_left", "lower_right", "b1", "b2", "c", "1", "0", "z"]
    ids = random.sample(pool, min(n, len(pool)))
    inter = {}
    for _ in range(random.randint(0, 6)):
        if len(ids) < 2: break
        a, b = random.sample(ids + (["ghost"] if random.random() < .1 else []), 2)
        pair = tuple(sorted((a, b)))
        inter[pair] = inter.get(pair, 0.0) + random.choice([0.25, 1.0])
    enc = [[list(k), v] for k, v in inter.items()]
    for kind, fn in (("branch", rc._best_branch_order), ("slots", rc._best_radial_slots)):
        try:
            r = fn(list(ids), inter); out[kind].append({"ids": ids, "inter": enc, "result": r if kind == "branch" else [[k, v] for k, v in r.items()]})
        except Exception as e:
            out[kind].append({"ids": ids, "inter": enc, "raises": type(e).__name__})
for pool, r in [("abcd", None), ("abc", 2), ("aab", None), ("", None), ("abcde", 3), ("ab", 3)]:
    out["perms"].append({"pool": list(pool), "r": r, "result": [list(p) for p in itertools.permutations(pool, r)]})
json.dump(out, open(sys.argv[1], "w"))
print({k: len(v) for k, v in out.items()})
