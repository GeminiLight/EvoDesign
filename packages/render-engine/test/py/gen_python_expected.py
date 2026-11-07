"""Generate test/py/python_expected.json: ground truth for the src/py runtime.

Run from the repository root:
  PYTHONPATH=. .venv/bin/python packages/render-engine/test/py/gen_python_expected.py

Floats are transported as float.hex() strings so every bit survives; JSON
value cases are transported as Python json text (``1.0`` stays ``1.0``) and
parsed in TS with floats kept as PyFloat.
"""
import hashlib
import json
import math
import random
import sys
import unicodedata
from pathlib import Path

random.seed(20261104)
OUT = Path(__file__).with_name("python_expected.json")


def rand_float():
    kind = random.randrange(8)
    if kind == 0:
        return float(random.randint(-10**6, 10**6))
    if kind == 1:
        return random.uniform(-1000, 1000)
    if kind == 2:
        return random.uniform(-1, 1) * 10 ** random.randint(-12, 22)
    if kind == 3:
        return random.randint(-4000, 4000) / 8  # exact halves/quarters/eighths
    if kind == 4:
        return round(random.uniform(-100, 100), random.randint(0, 4))
    if kind == 5:
        return random.choice([0.0, -0.0, 0.5, 1.5, 2.5, -0.5, -2.5, 1e16, 1e15, 1e-4, 1e-5, 123456789.0, 0.1, 0.2, 0.30000000000000004, 5e-324, 1.7976931348623157e308])
    if kind == 6:
        return random.uniform(0, 10)
    return struct_random()


def struct_random():
    import struct
    while True:
        x = struct.unpack("<d", random.getrandbits(64).to_bytes(8, "little"))[0]
        if math.isfinite(x):
            return x


floats = [rand_float() for _ in range(4000)]
cases = {}

cases["float_repr"] = [[x.hex(), repr(x), str(x)] for x in floats]

rounds = []
for x in floats:
    if abs(x) < 1e15:
        rounds.append([x.hex(), None, float(round(x)).hex()])
    for n in (0, 1, 2, 3, -1, -2, 6):
        rounds.append([x.hex(), n, round(x, n).hex()])
cases["round"] = rounds

divs = []
for _ in range(4000):
    a, b = rand_float(), rand_float()
    if b == 0:
        continue
    try:
        divs.append([a.hex(), b.hex(), (a // b).hex(), (a % b).hex()])
    except OverflowError:
        pass
for _ in range(2000):
    a, b = random.randint(-1000, 1000), random.choice([i for i in range(-30, 31) if i])
    divs.append([float(a).hex(), float(b).hex(), float(a // b).hex(), float(a % b).hex()])
cases["divmod"] = divs

fmt = []
for x in floats:
    if abs(x) < 1e17:
        for spec in (".0f", ".1f", ".2f", ".3f", ".0%", ".1%"):
            fmt.append([x.hex(), spec, format(x, spec)])
cases["format"] = fmt

pairs = []
for _ in range(20000):
    a, b = rand_float(), rand_float()
    pairs.append([a.hex(), b.hex(), math.hypot(a, b).hex()])
for _ in range(2000):
    p = [rand_float() for _ in range(3)]
    q = [rand_float() for _ in range(3)]
    pairs.append([[v.hex() for v in p], [v.hex() for v in q], math.dist(p, q).hex()])
cases["hypot"] = pairs

texts = [
    "", " ", "a", "  a  b \t c\n", "　中文　", "x\x1cy\x1dz", "\x85a\xa0b ", "a,b,,c", ",a,", "emoji 😀 test",
    "tab\tsep\tvalues", "  leading", "trailing  ", "​zero width​", "Ǆ Title", "ß straße", "İstanbul", "ΣΑΣ",
    "a b c d e", "--x--", "naïve café", "﻿bom", "日本語のテキスト", "한국어", "Ｆｕｌｌｗｉｄｔｈ", "a\r\nb\rc\nd",
]
strs = []
for t in texts:
    strs.append({
        "text": t,
        "split": t.split(), "split1": t.split(None, 1), "split_comma": t.split(","), "split_comma1": t.split(",", 1),
        "rsplit1": t.rsplit(None, 1), "rsplit_comma1": t.rsplit(",", 1),
        "strip": t.strip(), "lstrip": t.lstrip(), "rstrip": t.rstrip(), "strip_chars": t.strip("-a "),
        "lower": t.lower(), "upper": t.upper(), "isupper": t.isupper(), "islower": t.islower(), "isspace": t.isspace(),
        "isdigit": t.isdigit(), "len": len(t), "repr": repr(t), "slice": t[1:-1], "slice_step": t[::-2],
        "zfill": t.zfill(8),
    })
cases["strings"] = strs

sort_words = texts + ["a", "B", "b", "A", "￿", "\U0001f600", "", "ab", "a\U0001f600", "a￿", "Z"]
cases["sorted_strings"] = {"input": sort_words, "sorted": sorted(sort_words)}
tuples = [[random.randint(0, 3), random.choice("abc"), random.randint(0, 2)] for _ in range(60)]
cases["sorted_tuples"] = {
    "input": tuples,
    "sorted": sorted(tuples),
    "sorted_rev": sorted(tuples, reverse=True),
    "sorted_key0": sorted(tuples, key=lambda t: t[0]),
    "sorted_key0_rev": sorted(tuples, key=lambda t: t[0], reverse=True),
    "min_key0": min(tuples, key=lambda t: t[0]),
    "max_key0": max(tuples, key=lambda t: t[0]),
    "min_key2": min(tuples, key=lambda t: t[2]),
    "max_key2": max(tuples, key=lambda t: t[2]),
}

json_values = [
    {"b": 1, "a": [1, 2.0, -0.0, 1e16, 1.5e-05, 0.1], "c": None, "d": True, "e": "中文 😀   \x7f \x01 \"q\" \\ /"},
    ["semantic", "mobile_apps", [1, 2], {"z": {"y": 1.0, "x": 2}}],
    {"￿": 1, "\U0001f600": 2, "": 3, "a": 4, "B": 5, "": 6},
    {"nested": {"list": [], "dict": {}, "s": ""}, "num": [0, -1, 123456789012, 3.141592653589793, 1e-7, 2.5e22]},
    "plain \t\n\r\b\f string",
    [float("nan"), float("inf"), float("-inf")],
    1.0, 0, -0.0, 12345.678, "", [],
]
dumps = []
option_sets = [
    {},
    {"sort_keys": True, "ensure_ascii": False},
    {"sort_keys": True},
    {"ensure_ascii": False, "separators": [",", ":"]},
    {"indent": 2, "sort_keys": True, "ensure_ascii": False},
    {"indent": 2},
]
for value in json_values:
    text = json.dumps(value)
    for opts in option_sets:
        kw = dict(opts)
        if "separators" in kw:
            kw["separators"] = tuple(kw["separators"])
        dumps.append({"value": text, "options": opts, "expected": json.dumps(value, **kw)})
cases["json_dumps"] = dumps

hashes = []
for t in texts + ["", "abc", "a" * 55, "a" * 56, "a" * 64, "a" * 119, "b" * 1000, "excalidraw-id:[\"semantic\", \"x\"]"]:
    hashes.append([t, hashlib.sha256(t.encode("utf-8")).hexdigest(), hashlib.md5(t.encode("utf-8")).hexdigest()])
cases["hashes"] = hashes

widths = "".join({"N": "N", "Na": "n", "A": "A", "F": "F", "H": "H", "W": "W"}[unicodedata.east_asian_width(chr(cp))] for cp in range(0x110000))
cases["east_asian_width_sha256"] = hashlib.sha256(widths.encode()).hexdigest()
cases["unidata_version"] = unicodedata.unidata_version

loads = ['{"a": 1.0, "b": [1, 2.5e3, -0.0, NaN, Infinity, -Infinity], "c": "\\u00e9\\ud83d\\ude00", "a": 2}', '  [ ]  ', '"x"', "1e5", "-0"]
cases["json_loads"] = [[t, json.dumps(json.loads(t))] for t in loads]
cases["json_loads_errors"] = ["", "{", "[1,]", "{'a': 1}", "1 2", "\"a\x01\"", "nan", "01"]

OUT.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
print(f"wrote {OUT} ({OUT.stat().st_size} bytes)", file=sys.stderr)
