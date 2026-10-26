"""Compare two verified renders without relying on independent score scales."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from evo_diagram.utils.io_utils import image_to_data_url
from evo_diagram.utils.llm_output import convert_json_output


COMPARISON_PROMPT = """Compare two diagrams of the same source, shown as Image 1 and
Image 2. Both have already passed the same objective checks. Choose the one that
communicates the source more clearly, considering readable relationship labels,
unambiguous endpoints, balanced spacing, alignment, typography and coherent color.
Judge visible results, not the number of edits or a guessed production order.

Preserve source meaning. Section containment can express membership; a collective
subject can have one outcome arrow. Navigation headings may be plain text while
headings that are relationship endpoints need a visible boundary. Longer routes
are acceptable when they avoid crossings. A shorter edge does not compensate for
pushing a balanced section against its border. Do not reward hidden facts.

Use tie when there is no clear overall improvement or the tradeoffs cancel out.
Give one concrete visible reason. Return only JSON:
{"preference": "1" | "2" | "tie", "reason": "..."}
"""


def compare_rendered_diagrams(
    original_path: str,
    candidate_path: str,
    source_text: str,
    *,
    model: BaseChatModel | None = None,
) -> dict[str, Any]:
    """Return an auditable preference; raise if comparison is unavailable."""
    paths = {"original": original_path, "candidate": candidate_path}
    hashes = {
        name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for name, path in paths.items()
    }
    if hashes["original"] == hashes["candidate"]:
        return {"winner": "tie", "reason": "The rendered files are identical.",
                "image_hashes": hashes, "display_order": []}
    # Keep the presentation order independent of which image is the revision.
    order = sorted(paths, key=lambda name: hashes[name])
    content: list[dict[str, Any]] = [
        {"type": "text", "text": "Source content:\n" + source_text[:12000]}
    ]
    for index, name in enumerate(order, start=1):
        content.extend([
            {"type": "text", "text": f"Image {index}:"},
            {"type": "image_url", "image_url": {
                "url": image_to_data_url(paths[name]), "detail": "high",
            }},
        ])
    if model is None:
        from .critic_agent import VerifierCriticAgent

        model = VerifierCriticAgent().model
    response = model.invoke([
        SystemMessage(content=COMPARISON_PROMPT), HumanMessage(content=content),
    ])
    raw = getattr(response, "content", None)
    if isinstance(raw, list):
        raw = "".join(str(part.get("text", "")) for part in raw if isinstance(part, dict))
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Diagram comparison returned no text")
    parsed = convert_json_output(raw)
    if not isinstance(parsed, dict) or parsed.get("preference") not in {"1", "2", "tie"}:
        raise ValueError("Diagram comparison returned an invalid preference")
    reason = parsed.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Diagram comparison omitted its visible evidence")
    preference = parsed["preference"]
    return {
        "winner": "tie" if preference == "tie" else order[int(preference) - 1],
        "reason": reason.strip(), "display_order": order,
        "image_hashes": hashes, "raw_response": raw,
    }
