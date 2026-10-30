from typing import Any, Dict, List, Optional, Sequence

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from evo_diagram.agentic_system.common.diagram_types import (
    DiagramTypeValidationError,
    normalize_supported_diagram_type,
)


class GraphNode(BaseModel):
    """A node in the final Semantic Topology.

    Validation accepts a small alias set at the LLM boundary; downstream code
    receives the canonical field names from ``model_dump(by_alias=False)``.
    """

    id: str
    label: str
    semantic_class: str = Field(validation_alias=AliasChoices("class", "type"))

    model_config = ConfigDict(extra="allow")


class GraphEdge(BaseModel):
    """A directed edge acting as a relation between nodes.

    ``from``/``to`` are tolerated only as LLM-boundary aliases for
    ``source``/``target``.
    """

    id: str
    source: str = Field(validation_alias=AliasChoices("source", "from"))
    target: str = Field(validation_alias=AliasChoices("target", "to"))
    relation: Optional[str] = None
    label: Optional[str] = None  # Optional label for the edge if different from relation

    model_config = ConfigDict(extra="allow")


class GraphGroup(BaseModel):
    """A logical grouping of nodes (hierarchy)."""

    id: str
    label: Optional[str] = None
    parent_group_id: Optional[str] = None
    members: List[str] = Field(default_factory=list, description="List of member node ids or sub-group ids")
    relations: List[str] = Field(default_factory=list, description="List of edge ids that connect members")
    group_member_relation: Optional[str] = Field(
        default=None,
        description="Relation among members: parallel, progression, causal, contrast, conditional, temporal, hierarchical, compositional, exemplification",
    )

    model_config = ConfigDict(extra="allow")


class ElementStructure(BaseModel):
    """The final structured output optimized for diagramming."""
    chart_type: str = Field(
        description="Type of chart: flow chart, mind map, org chart, etc.",
        # LLM-boundary alias tolerance. Canonical output remains chart_type.
        validation_alias=AliasChoices("chart_type", "diagram_type"),
    )
    nodes: List[GraphNode]  # Required
    edges: List[GraphEdge] = Field(default_factory=list)  # Optional, default empty list
    groups: List[GraphGroup] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class StructureValidationError(ValueError):
    """Raised when Structure output violates the graph contract."""


def validate_structure_instantiation(instantiation: Any) -> Dict[str, Any]:
    """Validate and canonicalize a Structure stage instantiation.

    The Structure stage is the foreign-key root for Styling, Layout, Render,
    and Refiner.  This guard catches hard graph-contract failures immediately
    instead of letting dangling ids become missing arrows or misleading
    verifier findings downstream. The returned artifact uses canonical fields:
    ``chart_type``, node ``class``, and edge ``source`` / ``target``.
    """
    if not isinstance(instantiation, dict):
        raise StructureValidationError(
            "Structure instantiation must be a JSON object; "
            f"got {type(instantiation).__name__}."
        )

    normalized = dict(instantiation)
    chart_type = normalized.get("chart_type", normalized.get("diagram_type"))
    try:
        normalized["chart_type"] = normalize_supported_diagram_type(
            chart_type,
            field_name="chart_type",
        )
    except DiagramTypeValidationError as exc:
        raise StructureValidationError(str(exc)) from exc
    normalized.pop("diagram_type", None)

    normalized["nodes"] = _canonicalize_nodes(normalized.get("nodes"))
    normalized["edges"] = _canonicalize_edges(normalized.get("edges", []))
    normalized.setdefault("groups", [])

    try:
        ElementStructure.model_validate(normalized)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(part) for part in first.get("loc", ())) or "structure"
        msg = first.get("msg", str(exc))
        raise StructureValidationError(
            f"Invalid Structure instantiation schema at {loc}: {msg}"
        ) from exc

    nodes = _as_sequence(normalized.get("nodes"), "nodes")
    edges = _as_sequence(normalized.get("edges"), "edges")
    groups = _as_sequence(normalized.get("groups"), "groups")

    node_ids = _collect_unique_ids(nodes, "node")
    edge_ids = _collect_unique_ids(edges, "edge")
    group_ids = _collect_unique_ids(groups, "group")
    _ensure_disjoint_ids(node_ids, edge_ids, group_ids)

    valid_member_ids = node_ids | group_ids
    for edge in edges:
        edge_id = edge.get("id")
        source = edge.get("source")
        target = edge.get("target")
        if source not in node_ids:
            raise StructureValidationError(
                f"Edge {edge_id!r} source {source!r} does not reference an existing node."
            )
        if target not in node_ids:
            raise StructureValidationError(
                f"Edge {edge_id!r} target {target!r} does not reference an existing node."
            )
        _validate_edge_id(edge_id, source, target)

    memberships: Dict[str, str] = {}
    for group in groups:
        group_id = group.get("id")
        if group.get("parent_group_id") is not None and group["parent_group_id"] not in group_ids:
            raise StructureValidationError(
                f"Group {group_id!r} parent_group_id {group['parent_group_id']!r} "
                "does not reference an existing group."
            )
        for member_id in group.get("members", []) or []:
            if member_id == group_id:
                raise StructureValidationError(f"Group {group_id!r} cannot include itself as a member.")
            if member_id not in valid_member_ids:
                raise StructureValidationError(
                    f"Group {group_id!r} member {member_id!r} does not reference an existing node or group."
                )
            previous_group = memberships.get(member_id)
            if previous_group and previous_group != group_id:
                raise StructureValidationError(
                    f"Member {member_id!r} belongs to multiple groups: "
                    f"{previous_group!r} and {group_id!r}."
                )
            memberships[member_id] = group_id
        for edge_id in group.get("relations", []) or []:
            if edge_id not in edge_ids:
                raise StructureValidationError(
                    f"Group {group_id!r} relation {edge_id!r} does not reference an existing edge."
                )

    _ensure_group_graph_acyclic(groups)
    _validate_type_specific_fields(normalized["chart_type"], nodes, edges, node_ids)
    return normalized


def _canonicalize_nodes(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    normalized_nodes: list[Any] = []
    for node in value:
        if not isinstance(node, dict):
            normalized_nodes.append(node)
            continue
        normalized = dict(node)
        class_values = [
            value
            for value in (
                normalized.get("class"),
                normalized.get("semantic_class"),
                normalized.get("type"),
            )
            if value is not None
        ]
        if class_values and any(value != class_values[0] for value in class_values[1:]):
            raise StructureValidationError(
                f"Node {normalized.get('id')!r} has conflicting class/type values: "
                f"{class_values!r}."
            )
        canonical_class = class_values[0] if class_values else None
        if canonical_class is not None:
            normalized["class"] = canonical_class
        normalized.pop("type", None)
        normalized.pop("semantic_class", None)
        normalized_nodes.append(normalized)
    return normalized_nodes


def _canonicalize_edges(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    normalized_edges: list[Any] = []
    for edge in value:
        if not isinstance(edge, dict):
            normalized_edges.append(edge)
            continue
        normalized = dict(edge)
        if (
            "source" in normalized
            and "from" in normalized
            and normalized["source"] != normalized["from"]
        ):
            raise StructureValidationError(
                f"Edge {normalized.get('id')!r} has conflicting source/from values: "
                f"{normalized['source']!r} vs {normalized['from']!r}."
            )
        if (
            "target" in normalized
            and "to" in normalized
            and normalized["target"] != normalized["to"]
        ):
            raise StructureValidationError(
                f"Edge {normalized.get('id')!r} has conflicting target/to values: "
                f"{normalized['target']!r} vs {normalized['to']!r}."
            )
        if "source" not in normalized and "from" in normalized:
            normalized["source"] = normalized["from"]
        if "target" not in normalized and "to" in normalized:
            normalized["target"] = normalized["to"]
        normalized.pop("from", None)
        normalized.pop("to", None)
        normalized_edges.append(normalized)
    return normalized_edges


def _as_sequence(value: Any, field_name: str) -> Sequence[Dict[str, Any]]:
    if not isinstance(value, list):
        raise StructureValidationError(
            f"Structure field {field_name!r} must be a list; got {type(value).__name__}."
        )
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise StructureValidationError(
                f"Structure field {field_name}[{index}] must be an object; "
                f"got {type(item).__name__}."
            )
    return value


def _collect_unique_ids(items: Sequence[Dict[str, Any]], category: str) -> set[str]:
    seen: set[str] = set()
    for index, item in enumerate(items):
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            raise StructureValidationError(f"{category.title()} at index {index} has no non-empty string id.")
        if item_id in seen:
            raise StructureValidationError(f"Duplicate {category} id {item_id!r}.")
        seen.add(item_id)
    return seen


def _ensure_disjoint_ids(node_ids: set[str], edge_ids: set[str], group_ids: set[str]) -> None:
    collisions = (node_ids & edge_ids) | (node_ids & group_ids) | (edge_ids & group_ids)
    if collisions:
        formatted = ", ".join(sorted(collisions))
        raise StructureValidationError(
            f"Structure ids must be unique across nodes, edges, and groups; duplicates: {formatted}."
        )


def _validate_edge_id(edge_id: Any, source: Any, target: Any) -> None:
    if not all(isinstance(value, str) and value.strip() for value in (edge_id, source, target)):
        return
    expected = f"edge:{source}2{target}"
    if edge_id == expected:
        return
    if edge_id.startswith(f"{expected}_") and edge_id[len(expected) + 1 :].isdigit():
        return
    raise StructureValidationError(
        f"Edge {edge_id!r} must use canonical id {expected!r} "
        "or append a numeric suffix for parallel edges."
    )


def _ensure_group_graph_acyclic(groups: Sequence[Dict[str, Any]]) -> None:
    parent_for: Dict[str, str] = {}
    member_groups: Dict[str, set[str]] = {}
    group_ids = {
        group.get("id")
        for group in groups
        if isinstance(group.get("id"), str) and group.get("id")
    }

    for group in groups:
        group_id = group.get("id")
        if not isinstance(group_id, str):
            continue
        parent_group_id = group.get("parent_group_id")
        if isinstance(parent_group_id, str) and parent_group_id:
            parent_for[group_id] = parent_group_id
        for member_id in group.get("members", []) or []:
            if isinstance(member_id, str) and member_id in group_ids:
                member_groups.setdefault(member_id, set()).add(group_id)

    parent_sources: Dict[str, str] = {}
    adjacency: Dict[str, set[str]] = {group_id: set() for group_id in group_ids}
    for child_id, parent_id in parent_for.items():
        parent_sources[child_id] = parent_id
        adjacency.setdefault(parent_id, set()).add(child_id)
    for child_id, parents in member_groups.items():
        for parent_id in parents:
            previous_parent = parent_sources.get(child_id)
            if previous_parent and previous_parent != parent_id:
                raise StructureValidationError(
                    f"Group {child_id!r} has conflicting parents: "
                    f"{previous_parent!r} and {parent_id!r}."
                )
            parent_sources[child_id] = parent_id
            adjacency.setdefault(parent_id, set()).add(child_id)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(group_id: str, path: list[str]) -> None:
        if group_id in visiting:
            cycle = " -> ".join(path + [group_id])
            raise StructureValidationError(f"Group hierarchy contains a cycle: {cycle}.")
        if group_id in visited:
            return
        visiting.add(group_id)
        for child_id in adjacency.get(group_id, set()):
            visit(child_id, path + [group_id])
        visiting.remove(group_id)
        visited.add(group_id)

    for group_id in sorted(group_ids):
        visit(group_id, [])


def _validate_type_specific_fields(
    chart_type: str,
    nodes: Sequence[Dict[str, Any]],
    edges: Sequence[Dict[str, Any]],
    node_ids: set[str],
) -> None:
    if chart_type in {"mindmap", "tree", "orgchart"}:
        _validate_parent_id_fields(chart_type, nodes, node_ids)
    elif chart_type == "matrix":
        _validate_matrix_fields(nodes)
    elif chart_type == "sequence_diagram":
        _validate_sequence_fields(nodes, edges)
    elif chart_type == "gantt":
        _validate_gantt_fields(nodes)


def _validate_parent_id_fields(
    chart_type: str,
    nodes: Sequence[Dict[str, Any]],
    node_ids: set[str],
) -> None:
    roots: list[str] = []
    parent_for: Dict[str, Optional[str]] = {}
    for node in nodes:
        node_id = node.get("id")
        if "parent_id" not in node:
            raise StructureValidationError(
                f"{chart_type} node {node_id!r} must include parent_id."
            )
        parent_id = node.get("parent_id")
        if parent_id is None:
            roots.append(str(node_id))
        elif not isinstance(parent_id, str) or not parent_id.strip():
            raise StructureValidationError(
                f"{chart_type} node {node_id!r} parent_id must be null or a non-empty node id."
            )
        elif parent_id == node_id:
            raise StructureValidationError(
                f"{chart_type} node {node_id!r} cannot reference itself as parent_id."
            )
        elif parent_id not in node_ids:
            raise StructureValidationError(
                f"{chart_type} node {node_id!r} parent_id {parent_id!r} "
                "does not reference an existing node."
            )
        parent_for[str(node_id)] = parent_id if isinstance(parent_id, str) else None

    if not roots:
        raise StructureValidationError(f"{chart_type} must include one root node with parent_id null.")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str, path: list[str]) -> None:
        if node_id in visiting:
            cycle = " -> ".join(path + [node_id])
            raise StructureValidationError(f"{chart_type} parent_id hierarchy contains a cycle: {cycle}.")
        if node_id in visited:
            return
        visiting.add(node_id)
        parent_id = parent_for.get(node_id)
        if parent_id:
            visit(parent_id, path + [node_id])
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in sorted(parent_for):
        visit(node_id, [])


def _validate_matrix_fields(nodes: Sequence[Dict[str, Any]]) -> None:
    for node in nodes:
        node_id = node.get("id")
        if not _is_non_negative_int(node.get("row")):
            raise StructureValidationError(
                f"matrix node {node_id!r} must include non-negative integer row."
            )
        if not _is_non_negative_int(node.get("col")):
            raise StructureValidationError(
                f"matrix node {node_id!r} must include non-negative integer col."
            )


def _validate_sequence_fields(
    nodes: Sequence[Dict[str, Any]],
    edges: Sequence[Dict[str, Any]],
) -> None:
    for node in nodes:
        node_id = node.get("id")
        actor_id = node.get("actor_id")
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise StructureValidationError(
                f"sequence_diagram node {node_id!r} must include non-empty actor_id."
            )
    for edge in edges:
        edge_id = edge.get("id")
        if not _is_non_negative_int(edge.get("sequence_idx")):
            raise StructureValidationError(
                f"sequence_diagram edge {edge_id!r} must include non-negative integer sequence_idx."
            )


def _validate_gantt_fields(nodes: Sequence[Dict[str, Any]]) -> None:
    for node in nodes:
        node_id = node.get("id")
        start = node.get("start_ts")
        end = node.get("end_ts")
        if not _is_timestamp_like(start):
            raise StructureValidationError(
                f"gantt node {node_id!r} must include non-empty start_ts."
            )
        if not _is_timestamp_like(end):
            raise StructureValidationError(
                f"gantt node {node_id!r} must include non-empty end_ts."
            )
        if isinstance(start, (int, float)) and isinstance(end, (int, float)) and start > end:
            raise StructureValidationError(
                f"gantt node {node_id!r} start_ts must not be after end_ts."
            )
        if isinstance(start, str) and isinstance(end, str) and start > end:
            raise StructureValidationError(
                f"gantt node {node_id!r} start_ts must not be after end_ts."
            )


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_timestamp_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return isinstance(value, str) and bool(value.strip())
