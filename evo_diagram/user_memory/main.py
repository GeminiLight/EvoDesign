from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from evo_diagram.user_memory.extractors.diff_extractor import EnhancedDiffExtractor
    from evo_diagram.user_memory.extractors.llm_preference_agent import (
        LLMPreferenceExtractionAgent,
    )
    from evo_diagram.user_memory.extractors.vlm_observer import VLMImageObserver

logger = logging.getLogger(__name__)

# Dependency injection hooks. They stay unset until a code path actually needs
# the storage, VLM, JSON diff, or LLM stack; tests can monkeypatch them directly.
LLMFactory: Any = None
EnhancedDiffExtractor: Any = None
LLMPreferenceExtractionAgent: Any = None
VLMImageObserver: Any = None
Mem0PreferenceStorage: Any = None


def _get_llm_factory():
    global LLMFactory
    if LLMFactory is None:
        from evo_diagram.core.llm_factory import LLMFactory as _LLMFactory

        LLMFactory = _LLMFactory
    return LLMFactory


def _get_diff_extractor_class():
    global EnhancedDiffExtractor
    if EnhancedDiffExtractor is None:
        from .extractors.diff_extractor import EnhancedDiffExtractor as _EnhancedDiffExtractor

        EnhancedDiffExtractor = _EnhancedDiffExtractor
    return EnhancedDiffExtractor


def _get_preference_agent_class():
    global LLMPreferenceExtractionAgent
    if LLMPreferenceExtractionAgent is None:
        from .extractors.llm_preference_agent import (
            LLMPreferenceExtractionAgent as _LLMPreferenceExtractionAgent,
        )

        LLMPreferenceExtractionAgent = _LLMPreferenceExtractionAgent
    return LLMPreferenceExtractionAgent


def _get_vlm_observer_class():
    global VLMImageObserver
    if VLMImageObserver is None:
        from .extractors.vlm_observer import VLMImageObserver as _VLMImageObserver

        VLMImageObserver = _VLMImageObserver
    return VLMImageObserver


def _get_storage_class():
    global Mem0PreferenceStorage
    if Mem0PreferenceStorage is None:
        from .storage.mem0_storage import Mem0PreferenceStorage as _Mem0PreferenceStorage

        Mem0PreferenceStorage = _Mem0PreferenceStorage
    return Mem0PreferenceStorage


def _require_cli_args(parser, args, fields: List[str], *, mode: str) -> None:
    missing = [
        f"--{field.replace('_', '-')}"
        for field in fields
        if not getattr(args, field)
    ]
    if missing:
        parser.error(f"--mode {mode} requires: {', '.join(missing)}")


class UserPreferenceMemorySystem:
    """Orchestrates the 4-layer user preference learning system."""

    def __init__(
        self,
        user_id: str = "diagram_user_default",
        memory_db_path: Optional[str] = None,
        allow_in_memory_fallback: bool = False,
    ):
        """Initialize the preference memory system.

        Args:
            user_id: User identifier for preference isolation
            memory_db_path: Optional ChromaDB persistence path override.
            allow_in_memory_fallback: Explicitly allow volatile in-memory storage
                if persistent storage fails.
        """
        self.user_id = user_id
        self.memory_db_path = memory_db_path
        self._vlm_observer: Optional[VLMImageObserver] = None
        self._diff_extractor: Optional[EnhancedDiffExtractor] = None
        self._preference_agent: Optional[LLMPreferenceExtractionAgent] = None

        # Retrieve-only paths only need storage. The VLM, JSON diff extractor,
        # and LLM preference agent are created lazily by learn_from_edit().
        self.storage = _get_storage_class()(
            user_id=user_id,
            vector_db_path=memory_db_path,
            allow_in_memory_fallback=allow_in_memory_fallback,
        )
        logger.info("Layer 4 (Mem0 Storage) initialized")

    @property
    def vlm_observer(self) -> VLMImageObserver:
        """Layer 1 VLM observer, initialized only when learning from edits."""
        if self._vlm_observer is None:
            self._vlm_observer = _get_vlm_observer_class()()
            logger.info("Layer 1 (VLM Observer) initialized")
        return self._vlm_observer

    @property
    def diff_extractor(self) -> EnhancedDiffExtractor:
        """Layer 2 JSON diff extractor, initialized only when needed."""
        if self._diff_extractor is None:
            self._diff_extractor = _get_diff_extractor_class()()
            logger.info("Layer 2 (JSON Diff Extractor) initialized")
        return self._diff_extractor

    @property
    def preference_agent(self) -> LLMPreferenceExtractionAgent:
        """Layer 3 preference agent, initialized only when learning from edits."""
        if self._preference_agent is None:
            llm = _get_llm_factory().create_for_role("generator", temperature=0.7)
            self._preference_agent = _get_preference_agent_class()(model=llm)
            logger.info("Layer 3 (LLM Preference Agent) initialized")
        return self._preference_agent

    def learn_from_edit(
        self,
        task_json: Dict,
        model_manifest_path: str,
        model_image_path: str,
        user_manifest_path: str,
        user_image_path: str,
        session_id: str,
    ) -> Dict:
        """Learn preferences from user's manual diagram adjustments.

        Args:
            task_json: Task context (task_description, diagram_type, content_area, etc.)
            model_manifest_path: Path to model-generated diagram manifest
            model_image_path: Path to model-generated diagram image
            user_manifest_path: Path to user-adjusted diagram manifest
            user_image_path: Path to user-adjusted diagram image
            session_id: Session identifier

        Returns:
            Dict with extraction results and statistics
        """
        logger.info(f"Learning preferences from session {session_id}")

        # Extract task context
        task_description = task_json.get("task_description", task_json.get("content", ""))
        task_context = {
            "diagram_type": task_json.get("diagram_type", "unknown"),
            "content_area": task_json.get("content_area", "unknown"),
            "vertical_domain": task_json.get(
                "vertical_domain",
                task_json.get("domain", "unknown"),
            ),
            "query": task_json.get(
                "query",
                task_json.get("user_query", task_description),
            ),
            "task_id": task_json.get("id", session_id),
        }

        # Layer 1: VLM Observation
        logger.info("Layer 1: Running VLM observation...")
        visual_observation = self.vlm_observer.observe_differences(
            model_image_path=model_image_path,
            user_image_path=user_image_path,
            task_description=task_description,
        )
        logger.info(
            f"VLM observation complete. Overall intent: {visual_observation.overall_intent}"
        )

        # Layer 2: JSON Diff Extraction
        logger.info("Layer 2: Extracting JSON diff...")
        with open(model_manifest_path) as f:
            model_manifest = json.load(f)
        with open(user_manifest_path) as f:
            user_manifest = json.load(f)

        guided_diff = self.diff_extractor.extract_diff(
            model_manifest=model_manifest,
            user_manifest=user_manifest,
            visual_observation=visual_observation,
        )
        logger.info(
            f"JSON diff extracted: {len(guided_diff.modifications)} modifications, "
            f"{len(guided_diff.additions)} additions, {len(guided_diff.deletions)} deletions"
        )

        # Layer 3: LLM Preference Extraction
        logger.info("Layer 3: Extracting semantic preferences with LLM...")
        extraction_result = self.preference_agent.extract_preferences(
            visual_observation=visual_observation,
            guided_diff=guided_diff,
            task_context=task_context,
        )
        logger.info(
            f"Extracted {len(extraction_result.preferences)} preferences "
            f"(filtered {extraction_result.filtered_count} low-confidence, "
            f"status={extraction_result.status})"
        )

        # Build category counts
        category_counts = Counter(p.agent_category for p in extraction_result.preferences)
        if extraction_result.status == "failed":
            status = "failed"
        elif extraction_result.preferences:
            status = "stored_preferences"
        else:
            status = "no_preferences"

        if status == "stored_preferences":
            # Layer 4: Store in Mem0. Failed or empty extraction results are not
            # learning artifacts; storing their observations/diffs would pollute
            # long-term user memory with unverified evidence.
            logger.info("Layer 4: Storing preference learning artifacts in Mem0...")
            self.storage.store_preferences(
                visual_observation=visual_observation,
                guided_diff=guided_diff,
                extraction_result=extraction_result,
                session_id=session_id,
            )
            logger.info("Preference learning artifacts stored successfully")
        else:
            logger.info(
                "Skipping preference storage for session %s (status=%s)",
                session_id,
                extraction_result.status,
            )

        return {
            "status": status,
            "session_id": session_id,
            "visual_observation": visual_observation.model_dump(),
            "guided_diff": guided_diff,
            "diff_stats": {
                "modifications": len(guided_diff.modifications),
                "additions": len(guided_diff.additions),
                "deletions": len(guided_diff.deletions),
            },
            "preferences": {
                "extracted": len(extraction_result.preferences),
                "filtered": extraction_result.filtered_count,
                "items": extraction_result.preferences,
                "by_category": {
                    "Structure": category_counts.get("Structure", 0),
                    "Styling": category_counts.get("Styling", 0),
                    "Layout": category_counts.get("Layout", 0),
                },
                "extraction_status": extraction_result.status,
                "errors": extraction_result.errors,
                "warnings": extraction_result.warnings,
            },
            "task_context": task_context,
        }

    def retrieve_preferences(
        self,
        query: str,
        agent_category: Optional[str] = None,
        diagram_type: Optional[str] = None,
        content_area: Optional[str] = None,
        min_confidence: float = 0.7,
        top_k: int = 5,
    ) -> List[Dict]:
        """Retrieve semantic preferences for a new task.

        Args:
            query: Natural language query describing what preferences to retrieve
            agent_category: Filter by agent category (Structure, Styling, Layout)
            diagram_type: Filter by diagram type (e.g., "class", "dataflow")
            content_area: Filter by content area (e.g., "Software Engineering")
            min_confidence: Minimum confidence threshold (0.0-1.0)
            top_k: Maximum number of preferences to retrieve

        Returns:
            List of preference dictionaries with content and metadata
        """
        logger.info(f"Retrieving preferences: query='{query}', category={agent_category}")

        results = self.storage.retrieve_preferences(
            query=query,
            agent_category=agent_category,
            diagram_type=diagram_type,
            content_area=content_area,
            min_confidence=min_confidence,
            layer="semantic_preference",
            top_k=top_k,
        )

        logger.info(f"Retrieved {len(results)} preferences")
        return results

    def format_preferences_for_prompt(
        self, preferences: List[Dict], max_length: int = 1000
    ) -> str:
        """Format retrieved preferences for injection into agent prompts.

        Args:
            preferences: List of preference dictionaries from retrieve_preferences()
            max_length: Maximum character length for formatted output

        Returns:
            Formatted string ready for prompt injection
        """
        if not preferences:
            return ""

        lines = [
            "### User Preferences (Learned from Previous Edits)",
            "",
            "**IMPORTANT**: The following preferences were learned from this user's previous diagram edits. "
            "If relevant to the current task, you SHOULD incorporate these preferences into your design decisions. "
            "These represent the user's personal style and design choices.",
            ""
        ]

        for i, pref in enumerate(preferences, 1):
            metadata = pref.get("metadata", {})
            content = pref.get("memory", "")

            # Extract key metadata
            category = metadata.get("agent_category", "Unknown")
            confidence = metadata.get("confidence", 0.0)
            rationale = metadata.get("design_rationale", "")

            # Format preference
            line = f"{i}. **[{category}]** {content}"
            if rationale:
                line += f"\n   - Rationale: {rationale}"
            line += f"\n   - Confidence: {confidence:.0%}"
            lines.append(line)

            # Check length limit
            current_text = "\n".join(lines)
            if len(current_text) > max_length:
                lines = lines[:-1]  # Remove last line
                lines.append(f"... and {len(preferences) - i + 1} more preferences")
                break

        return "\n".join(lines)


def _print_learn_result(result: Dict) -> None:
    """Print formatted learn_from_edit result for CLI output."""
    obs = result["visual_observation"]
    diff = result["guided_diff"]
    prefs = result["preferences"]

    # Layer 1
    print("\n" + "-" * 80)
    print("LAYER 1: VLM Image Observation")
    print("-" * 80)
    print(f"  Overall Intent: {obs['overall_intent']}")
    for category in ["structural_changes", "styling_changes", "layout_changes"]:
        changes = obs[category]
        label = category.replace("_", " ").title()
        print(f"\n  {label}:")
        print(f"    - Description: {changes['description']}")
        print(f"    - Magnitude: {changes['magnitude']}")
        print(f"    - Affected Properties: {changes['affected_properties']}")

    # Layer 2
    print("\n" + "-" * 80)
    print("LAYER 2: JSON Diff Extraction")
    print("-" * 80)
    print(f"  Statistics:")
    print(f"    - Modifications: {result['diff_stats']['modifications']}")
    print(f"    - Additions: {result['diff_stats']['additions']}")
    print(f"    - Deletions: {result['diff_stats']['deletions']}")

    if diff.modifications:
        print(f"\n  Modifications (top 5):")
        for i, mod in enumerate(diff.modifications[:5]):
            print(f"    [{i+1}] Shape: {mod.shape_id}")
            for change in mod.changes[:3]:
                print(f"        - {change.property_path}: {change.from_value} -> {change.to_value} [{change.category}]")
            if len(mod.changes) > 3:
                print(f"        ... and {len(mod.changes) - 3} more changes")

    # Layer 3
    print("\n" + "-" * 80)
    print("LAYER 3: LLM Semantic Preference Extraction")
    print("-" * 80)
    print(f"  Total Preferences Extracted: {prefs['extracted']}")
    print(f"  Filtered (confidence < 0.7): {prefs['filtered']}")

    if prefs["items"]:
        print(f"\n  Extracted Preferences:")
        for i, pref in enumerate(prefs["items"], 1):
            print(f"\n    [{i}] {pref.agent_category} (confidence: {pref.confidence:.0%})")
            print(f"        Preference: {pref.preference_text[:100]}")
            print(f"        Rationale: {pref.design_rationale[:80]}")
            print(f"        Evidence: {pref.evidence_summary[:80]}")
            if pref.applies_to:
                print(f"        Applies to: diagram_type={pref.applies_to.get('diagram_type')}, element_type={pref.applies_to.get('element_type')}")

    # Layer 4
    print("\n" + "-" * 80)
    print("LAYER 4: Mem0 Storage")
    print("-" * 80)
    print(f"  Status: {result.get('status', 'unknown')}")
    print(f"  Session ID: {result['session_id']}")
    print(f"  Preferences Stored: {prefs['extracted']}")
    print(f"  By Category:")
    for cat, count in prefs["by_category"].items():
        print(f"    {cat}: {count}")


def main():
    """CLI entry point for testing."""
    import argparse

    parser = argparse.ArgumentParser(
        description="User Preference Memory System - Learn and retrieve user preferences"
    )
    parser.add_argument("--mode", choices=["learn", "retrieve"], required=True)
    parser.add_argument("--task-json", type=str, help="Path to task.json")
    parser.add_argument("--model-manifest", type=str, help="Path to model manifest")
    parser.add_argument("--model-image", type=str, help="Path to model image")
    parser.add_argument("--user-manifest", type=str, help="Path to user-adjusted manifest")
    parser.add_argument("--user-image", type=str, help="Path to user-adjusted image")
    parser.add_argument("--session-id", type=str, help="Session identifier")
    parser.add_argument("--user-id", type=str, default="diagram_user_default")
    parser.add_argument("--memory-db-path", type=str, default=None,
                        help="User preference DB path (default: from settings.yaml)")
    parser.add_argument("--query", type=str, help="Search query for retrieval")
    parser.add_argument("--agent-category", type=str, help="Filter by category")
    parser.add_argument("--diagram-type", type=str, help="Filter by diagram type")

    args = parser.parse_args()

    if args.mode == "learn":
        _require_cli_args(
            parser,
            args,
            [
                "task_json",
                "model_manifest",
                "model_image",
                "user_manifest",
                "user_image",
                "session_id",
            ],
            mode="learn",
        )
    elif args.mode == "retrieve":
        _require_cli_args(parser, args, ["query"], mode="retrieve")

    # Initialize system
    system = UserPreferenceMemorySystem(
        user_id=args.user_id,
        memory_db_path=args.memory_db_path,
    )

    if args.mode == "learn":
        # Load task.json
        with open(args.task_json) as f:
            task_json = json.load(f)

        # Learn from edit
        result = system.learn_from_edit(
            task_json=task_json,
            model_manifest_path=args.model_manifest,
            model_image_path=args.model_image,
            user_manifest_path=args.user_manifest,
            user_image_path=args.user_image,
            session_id=args.session_id,
        )

        _print_learn_result(result)

    elif args.mode == "retrieve":
        # Retrieve preferences
        prefs = system.retrieve_preferences(
            query=args.query,
            agent_category=args.agent_category,
            diagram_type=args.diagram_type,
        )

        # Print results
        print("\n" + "=" * 80)
        print("RETRIEVED PREFERENCES")
        print("=" * 80)
        print(f"Query: {args.query}")
        print(f"Results: {len(prefs)}\n")

        for i, pref in enumerate(prefs, 1):
            metadata = pref.get("metadata", {})
            content = pref.get("memory", "")

            print(f"{i}. [{metadata.get('agent_category')}] {content}")
            print(f"   Confidence: {metadata.get('confidence', 0.0):.1%}")
            print(f"   Rationale: {metadata.get('design_rationale', 'N/A')}")
            print()

        print("=" * 80)


if __name__ == "__main__":
    from evo_diagram.utils.env_loader import ensure_env_loaded

    ensure_env_loaded()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    main()
