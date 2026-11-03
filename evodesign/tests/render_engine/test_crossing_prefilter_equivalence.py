"""The crossing pre-filters must return exactly what the plain predicate does."""
import random

from evodesign.agentic_system.render_engine.shared import edge_crossing_detector as ecd


def _reference_count(segment, arrows):
    count = 0
    for arrow in arrows:
        if not ecd._is_visible_arrow(arrow):
            continue
        for existing in ecd._arrow_segments(arrow):
            if ecd._shares_endpoint(segment, existing):
                continue
            if ecd._segments_intersect(segment, existing):
                count += 1
                break
    return count


def _reference_pairs(arrows):
    indexed = [(a["id"], ecd._arrow_segments(a)) for a in arrows if ecd._is_visible_arrow(a)]
    pairs = []
    for i, (id_i, segs_i) in enumerate(indexed):
        for id_j, segs_j in indexed[i + 1:]:
            if any(not ecd._shares_endpoint(s, t) and ecd._segments_intersect(s, t)
                   for s in segs_i for t in segs_j):
                pairs.append(tuple(sorted((id_i, id_j))))
    return pairs


def _coordinate(rng):
    # Grid values, values just around the 1 px gap, and float noise.
    base = rng.choice([0.0, 10.0, 20.0, 21.0, 21.0000001, 22.0, 30.0])
    return base + rng.choice([0.0, 0.0, 1e-7, -1e-7, 0.5, 0.999, 1.0, 1.001, 1e-6, 3e-6])


def _segment(rng):
    x, y = _coordinate(rng), _coordinate(rng)
    kind = rng.random()
    if kind < 0.4:
        return (x, y, _coordinate(rng), y)          # horizontal
    if kind < 0.8:
        return (x, y, x, _coordinate(rng))          # vertical
    if kind < 0.9:
        return (x, y, x + rng.choice([1e-7, 2e-6, 1e-5]), y)  # tiny
    return (x, y, _coordinate(rng), _coordinate(rng))          # diagonal


def _arrow(rng, index):
    points = [(0.0, 0.0)]
    start = _segment(rng)
    origin = (start[0], start[1])
    for _ in range(rng.randint(1, 3)):
        seg = _segment(rng)
        points.append((seg[2] - origin[0], seg[3] - origin[1]))
    return {"id": f"a{index}", "type": "arrow", "x": origin[0], "y": origin[1], "points": [list(p) for p in points]}


def test_prepared_counts_and_pairs_match_the_plain_predicate():
    rng = random.Random(20261103)
    for _ in range(400):
        arrows = [_arrow(rng, i) for i in range(rng.randint(1, 6))]
        prepared = ecd.prepare_crossing_segments(arrows)
        for _ in range(25):
            segment = _segment(rng)
            assert ecd.count_prepared_crossings(segment, prepared) == _reference_count(segment, arrows)
            assert ecd.count_segment_crossings(segment, arrows) == _reference_count(segment, arrows)
        assert [(a, b) for a, b, _ in ecd.detect_crossings(arrows)] == _reference_pairs(arrows)
