"""Shared distance calculation for a label box clear of a connector segment."""

from math import hypot


def disjoint_segment_box_distance(start, end, box) -> float:
    """Return the exact gap after the caller has ruled out an intersection."""
    left, top, width, height = box
    right, bottom = left + width, top + height
    distances = [
        hypot(max(left - x, x - right, 0), max(top - y, y - bottom, 0))
        for x, y in (start, end)
    ]
    dx, dy = end[0] - start[0], end[1] - start[1]
    squared_length = dx * dx + dy * dy
    if squared_length:
        for x, y in ((left, top), (right, top), (left, bottom), (right, bottom)):
            fraction = max(0.0, min(1.0, ((x - start[0]) * dx + (y - start[1]) * dy) / squared_length))
            distances.append(hypot(x - start[0] - fraction * dx, y - start[1] - fraction * dy))
    return min(distances)
