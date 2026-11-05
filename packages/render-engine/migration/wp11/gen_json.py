import json, sys, math, random
# Encode: floats -> {"__f": repr}, tuples -> lists (json would do the same), ints plain
def enc(v):
    if isinstance(v, bool) or v is None or isinstance(v, (str, int)): return v
    if isinstance(v, float): return {"__f": repr(v)}
    if isinstance(v, (list, tuple)): return [enc(x) for x in v]
    if isinstance(v, dict): return {"__d": [[enc(k), enc(x)] for k, x in v.items()]}
    raise TypeError(type(v))
floats = [1.0, 0.0, -0.0, 1e16, 1e15, 123456789012345678.0, 0.1+0.2, 1/3, 1e-5, 1e-4, 0.0001234, 5e-324, 1.7976931348623157e308, 2.5, -1.5, 100.0, 1e22, 1e21, 12345.678, float('nan'), float('inf'), -float('inf'), 9007199254740993.0, 2**53 + 0.0, 1e300*1e-10]
ints = [0, -1, 2**53, 2**53 - 1, 123]
strings = ["", "plain", "中文", "emoji😀", "quote\"back\\slash", "ctrl\x00\x01\x1f\x7f", "  ", "tab\tnl\nret\r\b\f", "é", "퟿", "/slash"]
nested = [
  {"b": 1, "a": {"d": [1.0, 2, {"z": None, "y": True}], "c": "x"}, "A": 0, "_": [], "": {}},
  {"中": 1, "a": 2, "Z": 3, "é": 4, "😀": 5, "￿": 6},
  [[], {}, [{}], {"k": [[]]}],
  {"x": (1.0, 2.5), "y": [0.1+0.2, -0.0]},
]
cases = []
opts = [dict(sort_keys=True, ensure_ascii=False, default=str), dict(), dict(ensure_ascii=False, separators=(",", ":")), dict(sort_keys=True, indent=2)]
vals = [*floats, *ints, *strings, *nested, floats, strings]
for oi, o in enumerate(opts):
    for v in vals:
        try: out = json.dumps(v, **o)
        except Exception as e: out = {"raises": type(e).__name__}
        cases.append({"opt": oi, "value": enc(v), "out": out})
# str/repr of floats
strs = [{"value": enc(f), "str": str(f), "repr": repr(f)} for f in floats]
rnd = []
random.seed(7)
pairs = [(2.5, None), (3.5, None), (-2.5, None), (0.5, None), (2.675, 2), (1.005, 2), (-0.125, 2), (12345.6789, -2), (0.285, 2), (1e16+2, None), (-0.4, None), (7.5, 0), (-7.5, 0), (2.5, 0), (0.0, 1)]
pairs += [(random.uniform(-1000, 1000), random.choice([None, 0, 1, 2, 3])) for _ in range(300)]
for x, n in pairs:
    r = round(x) if n is None else round(x, n)
    rnd.append({"x": repr(x), "n": n, "r": repr(float(r)) if isinstance(r, float) else repr(r), "isint": isinstance(r, int)})
json.dump({"dumps": cases, "strs": strs, "round": rnd}, open(sys.argv[1], "w"), ensure_ascii=True)
print(len(cases), len(strs), len(rnd))
