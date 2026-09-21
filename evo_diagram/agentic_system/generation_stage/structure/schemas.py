from collections import Counter
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
    branch_id: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class GraphEdge(BaseModel):
    """A relation between nodes with explicit semantic directionality.

    ``from``/``to`` are tolerated only as LLM-boundary aliases for
    ``source``/``target``.
    """

    id: str
    source: str = Field(validation_alias=AliasChoices("source", "from"))
    target: str = Field(validation_alias=AliasChoices("target", "to"))
    relation: Optional[str] = None
    label: Optional[str] = None  # Optional label for the edge if different from relation
    relation_type: Optional[str] = None
    evidence_basis: Optional[str] = None
    directionality: Optional[str] = None
    evidence: Optional[str] = None

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


def validate_structure_semantic_ledger(
    specification: Any,
    instantiation: Dict[str, Any],
) -> None:
    """Verify an emitted fact ledger against the concrete relation graph.

    The ledger is optional for legacy outputs. Once either ledger is emitted,
    it becomes an auditable contract: source facts must map one-to-one to
    explicit edges and organizer entries must map one-to-one to structural
    edges. Counters preserve legitimate parallel relations with the same
    endpoints but different predicates.
    """
    if not isinstance(specification, dict):
        return
    semantic_typology = specification.get("semantic_typology")
    if not isinstance(semantic_typology, dict):
        return
    has_fact_ledger = "fact_ledger" in semantic_typology
    has_organizer_ledger = "organizer_ledger" in semantic_typology
    if not has_fact_ledger and not has_organizer_ledger:
        return

    fact_ledger = semantic_typology.get("fact_ledger")
    organizer_ledger = semantic_typology.get("organizer_ledger")
    if not isinstance(fact_ledger, list) or not isinstance(organizer_ledger, list):
        raise StructureValidationError(
            "Structure semantic_typology must provide fact_ledger and "
            "organizer_ledger as lists once ledger validation is enabled."
        )

    def normalized(value: Any) -> str:
        return " ".join(str(value or "").strip().lower().split())

    def ledger_key(
        entry: Any,
        *,
        source_field: str,
        label_field: str,
        target_field: str,
        ledger_name: str,
    ) -> tuple[str, str, str]:
        if not isinstance(entry, dict):
            raise StructureValidationError(
                f"Structure {ledger_name} entries must be objects."
            )
        source = entry.get(source_field)
        label = normalized(entry.get(label_field))
        target = entry.get(target_field)
        if not all(isinstance(value, str) and value.strip() for value in (source, target)):
            raise StructureValidationError(
                f"Structure {ledger_name} entry must include non-empty "
                f"{source_field} and {target_field}."
            )
        if not label:
            raise StructureValidationError(
                f"Structure {ledger_name} entry must include non-empty {label_field}."
            )
        return str(source), label, str(target)

    fact_keys = Counter(
        ledger_key(
            entry,
            source_field="subject_id",
            label_field="predicate",
            target_field="object_id",
            ledger_name="fact_ledger",
        )
        for entry in fact_ledger
    )
    organizer_keys = Counter(
        ledger_key(
            entry,
            source_field="source_id",
            label_field="label",
            target_field="target_id",
            ledger_name="organizer_ledger",
        )
        for entry in organizer_ledger
    )

    explicit_edges: Counter[tuple[str, str, str]] = Counter()
    structural_edges: Counter[tuple[str, str, str]] = Counter()
    for edge in instantiation.get("edges", []) or []:
        if not isinstance(edge, dict):
            continue
        key = (
            str(edge.get("source", "")),
            normalized(edge.get("label") or edge.get("relation")),
            str(edge.get("target", "")),
        )
        if edge.get("evidence_basis") == "explicit":
            explicit_edges[key] += 1
        elif edge.get("evidence_basis") == "structural":
            structural_edges[key] += 1

    def compare(
        ledger: Counter[tuple[str, str, str]],
        edges: Counter[tuple[str, str, str]],
        ledger_name: str,
    ) -> None:
        if ledger == edges:
            return
        missing = list((ledger - edges).elements())
        unledgered = list((edges - ledger).elements())
        details = []
        if missing:
            details.append(f"missing edges for {missing!r}")
        if unledgered:
            details.append(f"unledgered edges {unledgered!r}")
        raise StructureValidationError(
            f"Structure {ledger_name} does not match the relation graph: "
            + "; ".join(details)
            + "."
        )

    compare(fact_keys, explicit_edges, "fact_ledger")
    compare(organizer_keys, structural_edges, "organizer_ledger")


_RELATION_TYPE_ALIASES = {
    "hierarchical": "hierarchy",
    "subtype": "hierarchy",
    "compositional": "composition",
    "containment": "composition",
    "membership": "composition",
    "example": "exemplification",
    "dependency": "dependency",
    "enabling": "causal",
    "cause": "causal",
    "associative": "association",
    "link": "association",
}
_STRUCTURAL_RELATION_TYPES = {
    "hierarchy",
    "composition",
    "exemplification",
}
_CONCEPT_RELATION_TYPES = _STRUCTURAL_RELATION_TYPES | {
    "dependency",
    "causal",
    "association",
}
_EVIDENCE_BASES = {"explicit", "structural"}
_DIRECTIONALITIES = {"directed", "undirected"}
_STRUCTURAL_RELATION_LABELS = {
    "organized into",
    "has subtype",
    "includes",
    "contains",
    "has example",
}
_RELATION_LABEL_TYPES = {
    "hierarchy": {"organized into", "has subtype", "is subtype of"},
    "composition": {"includes", "contains", "has part", "part of"},
    "exemplification": {"has example", "exemplifies", "is example of"},
    "dependency": {"depends on", "requires", "relies on"},
    "causal": {
        "causes",
        "drives",
        "enables",
        "improves",
        "raises",
        "transforms",
    },
    "association": {"associated with", "linked to", "relates to"},
}


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

    if normalized["chart_type"] == "concept_map":
        normalized["edges"] = _normalize_concept_map_relation_metadata(
            normalized["nodes"],
            normalized["edges"],
        )
        normalized["edges"] = _reduce_concept_map_hierarchy_edges(
            normalized["nodes"],
            normalized["edges"],
        )
        _validate_concept_map_semantic_metadata(
            normalized["nodes"],
            normalized["edges"],
        )

    nodes = _as_sequence(normalized.get("nodes"), "nodes")
    edges = _as_sequence(normalized.get("edges"), "edges")
    groups = _as_sequence(normalized.get("groups"), "groups")

    node_ids = _collect_unique_ids(nodes, "node")
    edge_ids = _collect_unique_ids(edges, "edge")
    group_ids = _collect_unique_ids(groups, "group")
    _ensure_disjoint_ids(node_ids, edge_ids, group_ids)
    if normalized["chart_type"] == "concept_map":
        _validate_concept_map_branch_ids(nodes)

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
        relation_type = normalized.get("relation_type")
        if isinstance(relation_type, str) and relation_type.strip():
            relation_type = relation_type.strip().lower().replace("-", "_").replace(" ", "_")
            normalized["relation_type"] = _RELATION_TYPE_ALIASES.get(
                relation_type,
                relation_type,
            )
        evidence_basis = normalized.get("evidence_basis")
        if isinstance(evidence_basis, str) and evidence_basis.strip():
            normalized["evidence_basis"] = evidence_basis.strip().lower()
        directionality = normalized.get("directionality")
        if isinstance(directionality, str) and directionality.strip():
            normalized["directionality"] = directionality.strip().lower()
        normalized_edges.append(normalized)
    return normalized_edges


def _reduce_concept_map_hierarchy_edges(
    nodes: Sequence[Dict[str, Any]],
    edges: Sequence[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    """Drop redundant organizer shortcuts while preserving explicit source facts.

    ``relation_type`` and ``evidence_basis`` answer different questions. An
    explicit taxonomy fact is still a hierarchy relation, but it must not be
    reduced through a path of layout organizers. Only edges whose evidence is
    structural are reducible once the modern metadata contract is present.
    """
    node_classes = {
        str(node.get("id")): str(node.get("class", "")).lower()
        for node in nodes
        if isinstance(node.get("id"), str)
    }
    core_ids = {
        node_id for node_id, node_class in node_classes.items()
        if node_class in {"core", "core_concept"}
    }
    anchor_ids = {
        node_id for node_id, node_class in node_classes.items()
        if node_class in {"branch_anchor", "category"}
    }
    anchor_ids.update(
        str(edge.get("target"))
        for edge in edges
        if edge.get("source") in core_ids and isinstance(edge.get("target"), str)
    )
    hierarchy_sources = core_ids | anchor_ids

    modern_metadata = any("branch_id" in node for node in nodes)

    def is_reducible_organizer_edge(edge: Dict[str, Any]) -> bool:
        evidence_basis = str(edge.get("evidence_basis", "")).strip().lower()
        if modern_metadata:
            return evidence_basis == "structural"
        relation_type = str(edge.get("relation_type", "")).strip().lower()
        if relation_type:
            return relation_type in _STRUCTURAL_RELATION_TYPES
        label = str(edge.get("label") or edge.get("relation") or "").strip().lower()
        if label:
            return label in _STRUCTURAL_RELATION_LABELS
        return edge.get("source") in hierarchy_sources

    def has_alternative_path(source: str, target: str) -> bool:
        adjacency: Dict[str, set[str]] = {}
        for edge in edges:
            edge_source = edge.get("source")
            edge_target = edge.get("target")
            if not isinstance(edge_source, str) or not isinstance(edge_target, str):
                continue
            if not is_reducible_organizer_edge(edge):
                continue
            # Parallel relations with the same endpoints can carry distinct
            # semantics; they do not constitute a transitive alternative.
            if edge_source == source and edge_target == target:
                continue
            adjacency.setdefault(edge_source, set()).add(edge_target)
        queue = list(adjacency.get(source, set()))
        visited = {source}
        while queue:
            current = queue.pop(0)
            if current == target:
                return True
            if current in visited:
                continue
            visited.add(current)
            queue.extend(adjacency.get(current, set()) - visited)
        return False

    return [
        dict(edge)
        for edge in edges
        if not (
            isinstance(edge.get("source"), str)
            and isinstance(edge.get("target"), str)
            and edge["source"] in hierarchy_sources
            and is_reducible_organizer_edge(edge)
            and has_alternative_path(edge["source"], edge["target"])
        )
    ]


def _infer_concept_relation_type(label: str) -> Optional[str]:
    normalized = label.strip().lower()
    for relation_type, labels in _RELATION_LABEL_TYPES.items():
        if normalized in labels:
            return relation_type
    if "depend" in normalized or "rely" in normalized:
        return "dependency"
    if "example" in normalized or "exemplif" in normalized:
        return "exemplification"
    if "associat" in normalized or "link" in normalized:
        return "association"
    return None


def _normalize_concept_map_relation_metadata(
    nodes: Sequence[Dict[str, Any]],
    edges: Sequence[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    """Canonicalize relation semantics without inventing source facts."""
    node_classes = {
        str(node.get("id")): str(node.get("class", "")).lower()
        for node in nodes
        if isinstance(node.get("id"), str)
    }
    core_ids = {
        node_id for node_id, node_class in node_classes.items()
        if node_class in {"core", "core_concept"}
    }
    anchor_ids = {
        node_id for node_id, node_class in node_classes.items()
        if node_class in {"branch_anchor", "category"}
    }
    normalized_edges: list[Dict[str, Any]] = []
    for edge in edges:
        normalized = dict(edge)
        evidence_basis = str(normalized.get("evidence_basis", "")).strip().lower()
        if evidence_basis in {"inferred", "world_knowledge", "plausible"}:
            continue

        label = str(normalized.get("label") or normalized.get("relation") or "").strip()
        relation_type = str(normalized.get("relation_type", "")).strip().lower()
        if not relation_type and label:
            inferred_type = _infer_concept_relation_type(label)
            if inferred_type:
                relation_type = inferred_type
                normalized["relation_type"] = inferred_type

        if edge.get("source") in core_ids and edge.get("target") in anchor_ids:
            normalized["label"] = "organized into"
            normalized["relation_type"] = "hierarchy"
            normalized["evidence_basis"] = "structural"
            if "relation" in normalized:
                normalized["relation"] = "organized into"
        elif (
            edge.get("source") in anchor_ids
            and relation_type == "exemplification"
            and label.lower() in {"exemplifies", "is example of"}
        ):
            normalized["label"] = "has example"
            if "relation" in normalized:
                normalized["relation"] = "has example"
        elif relation_type == "association" and label.lower() in _RELATION_LABEL_TYPES["causal"]:
            normalized["label"] = "associated with"
            if "relation" in normalized:
                normalized["relation"] = "associated with"
        elif relation_type == "causal" and label.lower() in _RELATION_LABEL_TYPES["association"]:
            normalized["relation_type"] = "association"
            relation_type = "association"

        # Direction is part of the semantic contract, not a styling guess.
        # Preserve explicit model output, while upgrading older modern concept
        # maps deterministically so saved structures remain re-renderable.
        if not str(normalized.get("directionality", "")).strip():
            normalized["directionality"] = (
                "undirected" if relation_type == "association" else "directed"
            )
        normalized_edges.append(normalized)
    return normalized_edges


def _validate_concept_map_branch_ids(nodes: Sequence[Dict[str, Any]]) -> None:
    """Validate explicit branch ownership when the model emits it."""
    node_classes = {
        str(node.get("id")): str(node.get("class", "")).strip().lower()
        for node in nodes
        if isinstance(node.get("id"), str)
    }
    anchor_ids = {
        node_id
        for node_id, node_class in node_classes.items()
        if node_class in {"branch_anchor", "category"}
    }
    core_ids = {
        node_id
        for node_id, node_class in node_classes.items()
        if node_class in {"core", "core_concept"}
    }
    for node in nodes:
        if "branch_id" not in node:
            continue
        node_id = node.get("id")
        branch_id = node.get("branch_id")
        if node_id in core_ids:
            if branch_id is not None:
                raise StructureValidationError(
                    f"Concept-map core node {node_id!r} must use branch_id=null."
                )
            continue
        if node_id in anchor_ids:
            if branch_id != node_id:
                raise StructureValidationError(
                    f"Concept-map branch anchor {node_id!r} must own itself via branch_id."
                )
            continue
        if branch_id not in anchor_ids:
            raise StructureValidationError(
                f"Concept-map node {node_id!r} branch_id {branch_id!r} must reference "
                "a branch_anchor node."
            )


def _validate_concept_map_semantic_metadata(
    nodes: Sequence[Dict[str, Any]],
    edges: Sequence[Dict[str, Any]],
) -> None:
    """Require complete semantic metadata once a concept map opts into it."""
    modern_mode = any("branch_id" in node for node in nodes)
    if not modern_mode:
        return

    missing_branch_ids = [
        str(node.get("id"))
        for node in nodes
        if "branch_id" not in node
    ]
    if missing_branch_ids:
        raise StructureValidationError(
            "Modern concept-map structures require branch_id on every node; "
            f"missing: {', '.join(missing_branch_ids)}."
        )

    for edge in edges:
        edge_id = str(edge.get("id"))
        relation_type = edge.get("relation_type")
        if relation_type not in _CONCEPT_RELATION_TYPES:
            allowed = ", ".join(sorted(_CONCEPT_RELATION_TYPES))
            raise StructureValidationError(
                f"Concept-map edge {edge_id!r} relation_type {relation_type!r} "
                f"must be one of: {allowed}."
            )
        evidence_basis = edge.get("evidence_basis")
        if evidence_basis not in _EVIDENCE_BASES:
            raise StructureValidationError(
                f"Concept-map edge {edge_id!r} evidence_basis {evidence_basis!r} "
                "must be 'explicit' or 'structural'."
            )
        directionality = edge.get("directionality")
        if directionality not in _DIRECTIONALITIES:
            allowed = ", ".join(sorted(_DIRECTIONALITIES))
            raise StructureValidationError(
                f"Concept-map edge {edge_id!r} directionality {directionality!r} "
                f"must be one of: {allowed}."
            )
        if evidence_basis == "explicit":
            evidence = edge.get("evidence")
            if not isinstance(evidence, str) or not evidence.strip():
                raise StructureValidationError(
                    f"Explicit concept-map edge {edge_id!r} must include evidence."
                )


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
