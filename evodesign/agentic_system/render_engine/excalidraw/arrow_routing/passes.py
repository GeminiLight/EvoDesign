"""Scene-wide route optimization once every edge has a first route.

Each pass mutates the arrow elements in place and records the faces it
chose in ``route_contexts`` so later passes and label placement agree.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ...shared.edge_crossing_detector import count_arrow_crossings, detect_crossings
from ..edge_router import compute_waypoints
from .detours import (
    _avoid_node_intersections,
    _facing_side_pairs,
    _prefer_architecture_outer_route,
    _prefer_crosscutting_lower_corridor_route,
)
from .geometry import (
    _absolute_arrow_points,
    _arrow_path_fields,
    _compress_orthogonal_path,
    _is_orthogonal,
    _path_avoids_endpoint_interiors,
    _path_crossing_count,
    _path_length,
    _path_parallel_channel_penalty,
    _route_is_legal,
    _visible_arrows,
    _waypoints,
    _xy,
)
from .labels import _refresh_bound_labels

RouteContexts = Dict[str, Dict[str, Any]]
# (crossings, length, arrow, waypoints, start_side, end_side)
_Update = Tuple[int, float, Dict[str, Any], List[Dict[str, float]], str, str]


def _trial_crossings(
    arrow: Dict[str, Any],
    candidate_fields: Dict[str, Any],
    others: List[Dict[str, Any]],
    scene_crossings: int,
) -> int:
    """Scene crossing count if ``arrow`` took the candidate path.

    Crossings are pairwise, so only the pairs involving ``arrow`` change.
    """
    candidate = {**arrow, **candidate_fields}
    return (
        scene_crossings
        - count_arrow_crossings(arrow, others)
        + count_arrow_crossings(candidate, others)
    )


def _commit_best_updates(
    arrow_elems: List[Dict[str, Any]],
    route_contexts: RouteContexts,
    propose: Callable[[], Optional[_Update]],
    max_rounds: Optional[int] = None,
    after_commit: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """Greedy descent: apply the best single-edge reroute until none helps."""
    rounds = 0
    while max_rounds is None or rounds < max_rounds:
        rounds += 1
        best_update = propose()
        if best_update is None:
            break
        _, _, arrow, candidate, start_side, end_side = best_update
        arrow.update(_arrow_path_fields(candidate))
        context = route_contexts[str(arrow["id"])]
        context["start_side"] = start_side
        context["end_side"] = end_side
        if after_commit:
            after_commit(arrow)


def _better(update: _Update, best: Optional[_Update]) -> _Update:
    return update if best is None or update[:2] < best[:2] else best


def _reduce_crossings(
    arrow_elems: List[Dict[str, Any]],
    route_contexts: RouteContexts,
    elements_by_id: Dict[str, Dict[str, Any]],
    port_spacing: float,
) -> None:
    """Draw.io-style global port reconsideration.

    The layout model supplies the first route, then a deterministic
    coordinate-descent pass tries the two facing axes and their L-shaped
    combinations for every crossing edge. A candidate is committed only when
    it lowers the complete scene's crossing count.
    """

    def propose() -> Optional[_Update]:
        crossing_pairs = detect_crossings(arrow_elems)
        current_crossings = len(crossing_pairs)
        if current_crossings == 0:
            return None
        crossing_neighbors: Dict[str, Set[str]] = {}
        for first_id, second_id, _ in crossing_pairs:
            crossing_neighbors.setdefault(first_id, set()).add(second_id)
            crossing_neighbors.setdefault(second_id, set()).add(first_id)
        best_update: Optional[_Update] = None
        for arrow in arrow_elems:
            arrow_id = str(arrow.get("id", ""))
            context = route_contexts.get(arrow_id) if arrow_id in crossing_neighbors else None
            if not context:
                continue
            source_bbox = context["source_bbox"]
            target_bbox = context["target_bbox"]
            horizontal, vertical = _facing_side_pairs(source_bbox, target_bbox)
            side_pairs = list(dict.fromkeys([
                (context["start_side"], context["end_side"]),
                horizontal,
                vertical,
                (horizontal[0], vertical[1]),
                (vertical[0], horizontal[1]),
            ]))
            current_length = max(_path_length(_absolute_arrow_points([arrow])), 1.0)
            other_arrows = [item for item in arrow_elems if item is not arrow]
            # Seed the visibility grid only with the routes that currently
            # conflict with this edge. The complete scene is still scored
            # before committing.
            conflicting_arrows = [
                item for item in other_arrows
                if str(item.get("id", "")) in crossing_neighbors[arrow_id]
            ]
            for start_side, end_side in side_pairs:
                candidate, _, _ = compute_waypoints(
                    start_side,
                    end_side,
                    source_bbox,
                    target_bbox,
                    start_port_index=context["source_x_index" if start_side in {"top", "bottom"} else "source_y_index"],
                    start_port_total=context["source_degree"],
                    end_port_index=context["target_x_index" if end_side in {"top", "bottom"} else "target_y_index"],
                    end_port_total=context["target_degree"],
                    port_spacing=port_spacing,
                )
                candidate = _avoid_node_intersections(
                    candidate, context["obstacles"], existing_arrows=conflicting_arrows,
                )
                points = _xy(candidate)
                candidate_length = _path_length(points)
                if (
                    not _route_is_legal(points, context["obstacles"], source_bbox, target_bbox)
                    or candidate_length > current_length * 1.6
                ):
                    continue
                trial_crossings = _trial_crossings(
                    arrow, _arrow_path_fields(candidate), other_arrows, current_crossings,
                )
                if trial_crossings >= current_crossings:
                    continue
                best_update = _better(
                    (trial_crossings, candidate_length, arrow, candidate, start_side, end_side),
                    best_update,
                )
        return best_update

    _commit_best_updates(
        arrow_elems,
        route_contexts,
        propose,
        max_rounds=8,
        after_commit=lambda arrow: _refresh_bound_labels(arrow, elements_by_id),
    )


def _route_concept_corridors(
    arrow_elems: List[Dict[str, Any]],
    route_contexts: RouteContexts,
    elements_by_id: Dict[str, Dict[str, Any]],
    concept_frames: List[Tuple[str, Dict[str, float]]],
    port_spacing: float,
) -> None:
    """Send long concept-map cross-section relations along a clear corridor.

    The regular router intentionally ignores group backgrounds as obstacles,
    so without this composition-aware pass a dependency can run straight
    through an unrelated band even though it avoids every node.
    """
    if len(concept_frames) < 3:
        return
    frame_index = {frame_id: index for index, (frame_id, _) in enumerate(concept_frames)}

    def containing_frame(box: Dict[str, float]) -> Optional[str]:
        center_x = box["x"] + box["w"] / 2.0
        center_y = box["y"] + box["h"] / 2.0
        for frame_id, frame in concept_frames:
            if (
                frame["x"] <= center_x <= frame["x"] + frame["w"]
                and frame["y"] <= center_y <= frame["y"] + frame["h"]
            ):
                return frame_id
        return None

    frame_by_id = dict(concept_frames)
    min_left = min(frame["x"] for _, frame in concept_frames)
    max_right = max(frame["x"] + frame["w"] for _, frame in concept_frames)
    corridor_margin = 28.0
    band_clearance = 14.0
    for arrow in arrow_elems:
        context = route_contexts.get(str(arrow.get("id", "")))
        if not context or not context.get("cross_branch"):
            continue
        source_frame_id = containing_frame(context["source_bbox"])
        target_frame_id = containing_frame(context["target_bbox"])
        if not source_frame_id or not target_frame_id:
            continue
        source_frame_index = frame_index[source_frame_id]
        target_frame_index = frame_index[target_frame_id]
        if abs(target_frame_index - source_frame_index) < 2:
            continue

        source_box = context["source_bbox"]
        target_box = context["target_bbox"]
        source_frame = frame_by_id[source_frame_id]
        target_frame = frame_by_id[target_frame_id]
        downward = target_frame_index > source_frame_index
        source_x = source_box["x"] + source_box["w"] / 2.0
        target_x = target_box["x"] + target_box["w"] / 2.0
        source_y = source_box["y"] + source_box["h"] if downward else source_box["y"]
        target_y = target_box["y"] if downward else target_box["y"] + target_box["h"]
        source_gap_y = (
            source_frame["y"] + source_frame["h"] + band_clearance
            if downward
            else source_frame["y"] - band_clearance
        )
        target_gap_y = (
            target_frame["y"] - band_clearance
            if downward
            else target_frame["y"] + target_frame["h"] + band_clearance
        )
        route_candidates: List[Tuple[int, float, List[Dict[str, float]], str]] = []
        other_arrows = [item for item in arrow_elems if item is not arrow]

        def consider(raw_candidate, start_side: str) -> None:
            compressed = _compress_orthogonal_path(raw_candidate)
            if not _route_is_legal(compressed, context["obstacles"], source_box, target_box):
                return
            route_candidates.append((
                _path_crossing_count(compressed, other_arrows),
                _path_length(compressed),
                _waypoints(compressed),
                start_side,
            ))

        # First consider clear rails inside the band composition. A
        # draw.io-style router derives these channels from obstacle
        # boundaries instead of sending every long relation around the page
        # perimeter. Candidate rails stay in the whitespace immediately
        # beside nodes and are accepted only after full obstacle and crossing
        # checks.
        interior_corridors = {source_x, target_x}
        for left, _, width, _ in context["obstacles"]:
            interior_corridors.update((left - band_clearance, left + width + band_clearance))
        source_ports = {source_x}
        source_margin = 8.0
        for offset_index in range(1, int(context["source_degree"]) + 2):
            offset = float(offset_index) * float(port_spacing)
            for candidate_x in (source_x - offset, source_x + offset):
                if source_box["x"] + source_margin <= candidate_x <= source_box["x"] + source_box["w"] - source_margin:
                    source_ports.add(candidate_x)

        for source_port_x in sorted(source_ports):
            for corridor_x in sorted(interior_corridors):
                if not (min_left + band_clearance < corridor_x < max_right - band_clearance):
                    continue
                consider(
                    [
                        (source_port_x, source_y),
                        (source_port_x, source_gap_y),
                        (corridor_x, source_gap_y),
                        (corridor_x, target_gap_y),
                        (target_x, target_gap_y),
                        (target_x, target_y),
                    ],
                    "bottom" if downward else "top",
                )

        # The exterior rails remain a robust fallback when every internal
        # channel is blocked by a populated intermediate band. Scoring
        # crossings first preserves readability; length then naturally favors
        # a clear internal rail when available.
        for corridor_x, side in ((min_left - corridor_margin, "left"), (max_right + corridor_margin, "right")):
            side_source_x = source_box["x"] if side == "left" else source_box["x"] + source_box["w"]
            side_source_y = source_box["y"] + source_box["h"] / 2.0
            # Escape above a downward source (or below an upward one) before
            # entering an exterior rail. A source in the middle of a populated
            # row cannot reach the rail through its row peers, and dropping
            # through its local fan-out can cross several meaningful edges.
            escape_y = source_box["y"] - 24.0 if downward else source_box["y"] + source_box["h"] + 24.0
            consider(
                [
                    (source_x, source_y),
                    (source_x, source_gap_y),
                    (corridor_x, source_gap_y),
                    (corridor_x, target_gap_y),
                    (target_x, target_gap_y),
                    (target_x, target_y),
                ],
                "bottom" if downward else "top",
            )
            consider(
                [
                    (side_source_x, side_source_y),
                    (corridor_x, side_source_y),
                    (corridor_x, target_gap_y),
                    (target_x, target_gap_y),
                    (target_x, target_y),
                ],
                "bottom" if side_source_x == source_x and downward
                else "top" if side_source_x == source_x
                else side,
            )
            consider(
                [
                    (source_x, source_box["y"] if downward else source_box["y"] + source_box["h"]),
                    (source_x, escape_y),
                    (corridor_x, escape_y),
                    (corridor_x, target_gap_y),
                    (target_x, target_gap_y),
                    (target_x, target_y),
                ],
                "top" if downward else "bottom",
            )
        if not route_candidates:
            continue
        _, _, candidate, candidate_start_side = min(route_candidates, key=lambda item: (item[0], item[1]))
        arrow.update(_arrow_path_fields(candidate))
        context["start_side"] = candidate_start_side
        context["end_side"] = "top" if downward else "bottom"
        _detach_corridor_labels(arrow, elements_by_id, candidate, target_x, target_gap_y, downward)


def _detach_corridor_labels(
    arrow: Dict[str, Any],
    elements_by_id: Dict[str, Dict[str, Any]],
    candidate: List[Dict[str, float]],
    target_x: float,
    target_gap_y: float,
    downward: bool,
) -> None:
    """Pin a corridor route's predicate beside its final approach.

    A path-length midpoint would put the predicate beside the outer canvas
    edge. Keep the semantic label, but attach it to the final horizontal
    approach where readers naturally reconnect the perimeter route with its
    target section.
    """
    retained_bindings: List[Dict[str, Any]] = []
    for binding in arrow.get("boundElements", []) or []:
        if binding.get("type") != "text" or not binding.get("id"):
            retained_bindings.append(binding)
            continue
        label = elements_by_id.get(str(binding["id"]))
        if label is None:
            continue
        label_width = float(label.get("width", 0.0) or 0.0)
        label_height = float(label.get("height", 0.0) or 0.0)
        approach_x = float(candidate[-2]["x"])
        label_x = target_x - label_width - 18.0 if approach_x < target_x else target_x + 18.0
        label_y = target_gap_y - label_height - 8.0 if downward else target_gap_y + 8.0
        label.update({
            "x": max(0.0, label_x),
            "y": max(0.0, label_y),
            "containerId": None,
            "meta": {"semantic_edge_id": arrow.get("meta", {}).get("semantic_edge_id")},
        })
    if retained_bindings:
        arrow["boundElements"] = retained_bindings
    else:
        arrow.pop("boundElements", None)


def _reroute_architecture_edges(
    arrow_elems: List[Dict[str, Any]],
    route_contexts: RouteContexts,
    side_group_ids: Set[str],
    source_degrees: Dict[str, int],
    target_degrees: Dict[str, int],
) -> None:
    """Move unlabeled architecture edges onto outer faces or the lower corridor.

    Only single edges between their endpoints and edges touching a
    cross-cutting group move; a move may not add crossings, and keeping the
    count equal is allowed only when it clears a crowded parallel channel.
    """

    def propose() -> Optional[_Update]:
        current_crossings = len(detect_crossings(arrow_elems))
        best_update: Optional[_Update] = None
        for arrow in arrow_elems:
            context = route_contexts.get(str(arrow.get("id", "")))
            if not context or arrow.get("boundElements"):
                continue
            is_crosscutting = (
                context.get("source_group") in side_group_ids
                or context.get("target_group") in side_group_ids
            )
            if not is_crosscutting and (
                source_degrees[context["source_ref"]] != 1
                or target_degrees[context["target_ref"]] != 1
            ):
                continue
            current_points = [
                {
                    "x": float(arrow.get("x", 0.0)) + float(point[0]),
                    "y": float(arrow.get("y", 0.0)) + float(point[1]),
                }
                for point in arrow.get("points", [])
            ]
            other_arrows = [item for item in arrow_elems if item is not arrow]
            route_args = (
                context["start_side"],
                context["end_side"],
                context["source_bbox"],
                context["target_bbox"],
                context["obstacles"],
                other_arrows,
            )
            # A lower-corridor move for a cross-cutting edge takes precedence
            # over trying its outer faces.
            crosscutting_candidate = (
                _prefer_crosscutting_lower_corridor_route(current_points, *route_args)
                if is_crosscutting
                else None
            )
            used_crosscutting_candidate = bool(crosscutting_candidate) and crosscutting_candidate != current_points
            if used_crosscutting_candidate:
                candidate, start_side, end_side = crosscutting_candidate, context["start_side"], context["end_side"]
            else:
                candidate, start_side, end_side = _prefer_architecture_outer_route(current_points, *route_args)
            if candidate == current_points:
                continue
            candidate_points = _xy(candidate)
            if not _path_avoids_endpoint_interiors(candidate_points, context["source_bbox"], context["target_bbox"]):
                continue
            trial_crossings = _trial_crossings(
                arrow, _arrow_path_fields(candidate), other_arrows, current_crossings,
            )
            if trial_crossings > current_crossings:
                continue
            if trial_crossings == current_crossings and not (
                used_crosscutting_candidate
                and _path_parallel_channel_penalty(candidate, other_arrows)
                < _path_parallel_channel_penalty(current_points, other_arrows)
            ):
                continue
            best_update = _better(
                (trial_crossings, _path_length(candidate_points), arrow, candidate, start_side, end_side),
                best_update,
            )
        return best_update

    _commit_best_updates(arrow_elems, route_contexts, propose)


def _spread_final_target_ports(
    arrows: List[Dict[str, Any]],
    route_contexts: RouteContexts,
    spacing: float,
) -> None:
    """Separate incoming ports after route optimization has changed faces."""
    if spacing <= 0:
        return
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for arrow in _visible_arrows(arrows):
        context = route_contexts.get(str(arrow.get("id", "")))
        if context:
            groups.setdefault((context["target_ref"], context["end_side"]), []).append(arrow)

    for (_, side), siblings in groups.items():
        if len(siblings) < 2:
            continue
        axis = 0 if side in {"top", "bottom"} else 1
        box = route_contexts[str(siblings[0]["id"])]["target_bbox"]
        span = box["w"] if axis == 0 else box["h"]
        step = min(spacing, max(0.0, span - 16.0) / (len(siblings) - 1))
        if step <= 0:
            continue
        paths = {str(arrow["id"]): _absolute_arrow_points([arrow]) for arrow in siblings}
        # Preserve simple direct connections; changing their end would also
        # move their source or make a formerly orthogonal line diagonal.
        if any(len(points) < 3 for points in paths.values()):
            continue
        ordered = sorted(siblings, key=lambda arrow: (
            paths[str(arrow["id"])][-1][axis],
            paths[str(arrow["id"])][0][axis],
            str(arrow["id"]),
        ))
        positions = [paths[str(arrow["id"])][-1][axis] for arrow in ordered]
        if min(b - a for a, b in zip(positions, positions[1:])) >= step - 1e-6:
            continue
        center = box["x" if axis == 0 else "y"] + span / 2.0
        boundary = box["y" if axis == 0 else "x"]
        if side == "bottom":
            boundary += box["h"]
        elif side == "right":
            boundary += box["w"]
        replacements: Dict[str, Dict[str, Any]] = {}
        for rank, arrow in enumerate(ordered):
            arrow_id = str(arrow["id"])
            points = [list(point) for point in paths[arrow_id]]
            # The final segment must enter this actual face normally. Context
            # left over from a custom route must not shift a different face.
            if (
                abs(points[-1][1 - axis] - boundary) > 1e-6
                or abs(points[-2][axis] - points[-1][axis]) > 1e-6
            ):
                break
            coordinate = center + (rank - (len(ordered) - 1) / 2.0) * step
            points[-1][axis] = coordinate
            points[-2][axis] = coordinate
            candidate_points = [tuple(point) for point in points]
            context = route_contexts[arrow_id]
            if not (
                _is_orthogonal(candidate_points)
                and _route_is_legal(
                    candidate_points, context["obstacles"], context["source_bbox"], context["target_bbox"]
                )
            ):
                break
            replacements[arrow_id] = {**arrow, **_arrow_path_fields(_waypoints(candidate_points))}
        if len(replacements) != len(siblings):
            continue
        trial = [replacements.get(str(arrow["id"]), arrow) for arrow in arrows]
        if len(detect_crossings(trial)) > len(detect_crossings(arrows)):
            continue
        for arrow in siblings:
            arrow.update(replacements[str(arrow["id"])])


def _separate_final_channels(
    arrows: List[Dict[str, Any]],
    route_contexts: RouteContexts,
) -> None:
    """Separate crowded dogleg channels without changing either endpoint."""
    for _ in range(2):
        changed = False
        for arrow in _visible_arrows(arrows):
            context = route_contexts.get(str(arrow.get("id", "")))
            points = _absolute_arrow_points([arrow])
            if context is None or len(points) != 4:
                continue
            middle = (points[1], points[2])
            vertical = abs(middle[0][0] - middle[1][0]) < 1e-6
            horizontal = abs(middle[0][1] - middle[1][1]) < 1e-6
            if vertical == horizontal or _path_length(list(middle)) < 24.0:
                continue
            axis = 0 if vertical else 1
            other_arrows = [item for item in arrows if item is not arrow]
            penalty = _path_parallel_channel_penalty(points, other_arrows)
            if penalty <= 1e-6:
                continue
            crossings = _path_crossing_count(points, other_arrows)
            length = _path_length(points)
            best = None
            for delta in (-16.0, -8.0, 8.0, 16.0):
                candidate = [list(point) for point in points]
                candidate[1][axis] += delta
                candidate[2][axis] += delta
                candidate_points = [tuple(point) for point in candidate]
                candidate_length = _path_length(candidate_points)
                if (
                    candidate_length > length + 32.0
                    or not _is_orthogonal(candidate_points)
                    or not _route_is_legal(
                        candidate_points, context["obstacles"], context["source_bbox"], context["target_bbox"]
                    )
                    or _path_crossing_count(candidate_points, other_arrows) > crossings
                ):
                    continue
                candidate_penalty = _path_parallel_channel_penalty(candidate_points, other_arrows)
                if candidate_penalty >= penalty - 1e-6:
                    continue
                score = (candidate_penalty, candidate_length, abs(delta))
                if best is None or score < best[0]:
                    best = (score, candidate_points)
            if best is None:
                continue
            arrow.update(_arrow_path_fields(_waypoints(best[1])))
            changed = True
        if not changed:
            break
