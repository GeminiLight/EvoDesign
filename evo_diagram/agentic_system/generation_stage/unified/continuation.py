"""Resume interrupted native scenes at complete JSON value boundaries."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from evo_diagram.core.base_agent import LLMResponseError, _is_retryable_exception
from evo_diagram.utils.llm_output import get_text_from_response
from .transport_journal import NativeStreamJournal

logger = logging.getLogger(__name__)


def complete_scene_prefix(text: str) -> str:
    """Keep complete elements/fields verbatim; discard only the unfinished tail."""
    decoder = json.JSONDecoder()
    index, checkpoint, array_checkpoint = 0, 0, 0
    has_elements = False

    def whitespace(offset: int) -> int:
        while offset < len(text) and text[offset].isspace():
            offset += 1
        return offset

    index = whitespace(index)
    if text[index:index + 1] != "{":
        return ""
    index += 1
    try:
        while True:
            key, index = decoder.raw_decode(text, whitespace(index))
            if not isinstance(key, str):
                break
            index = whitespace(index)
            if text[index:index + 1] != ":":
                break
            index = whitespace(index + 1)
            if key == "elements" and text[index:index + 1] == "[":
                array_checkpoint = index + 1
                index = whitespace(index + 1)
                while text[index:index + 1] != "]":
                    element, index = decoder.raw_decode(text, index)
                    if not isinstance(element, dict):
                        return text[:checkpoint]
                    has_elements = True
                    checkpoint = index
                    index = whitespace(index)
                    if text[index:index + 1] != ",":
                        break
                    index = whitespace(index + 1)
                if text[index:index + 1] != "]":
                    break
                index += 1
                has_elements = True
            else:
                _, index = decoder.raw_decode(text, index)
            if has_elements:
                checkpoint = index
            index = whitespace(index)
            if text[index:index + 1] != ",":
                break
            index += 1
    except json.JSONDecodeError:
        pass
    if checkpoint:
        return text[:checkpoint]
    return text[:array_checkpoint]


def invoke_native_scene(
    agent: Any,
    input_prompt: dict[str, Any],
    journal: NativeStreamJournal,
    *,
    max_attempts: int = 5,
    max_continuations: int = 2,
) -> Any:
    """Use the existing call budget for retries or productive suffix requests."""
    prompt = input_prompt
    prefix = ""
    continuations: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        journal.last_output = ""
        try:
            result = agent.invoke(prompt)
            if result is None or (isinstance(result, dict) and "error" in result):
                raise LLMResponseError("Native generation returned no usable response")
        except Exception as exc:
            if not _is_retryable_exception(exc):
                raise
            partial = prefix + journal.last_output
            if journal.last_output:
                try:
                    json.loads(partial)
                except json.JSONDecodeError:
                    checkpoint = complete_scene_prefix(partial)
                else:
                    # A broken final event must not discard an already complete
                    # scene. The caller still runs strict schema/semantic checks.
                    return {"messages": [AIMessage(content=partial)]}
            else:
                checkpoint = ""
            if attempt == max_attempts:
                raise
            if len(checkpoint) > len(prefix):
                if len(continuations) >= max_continuations:
                    raise
                prefix = checkpoint
                try:
                    json.loads(prefix + "]}")
                    boundary = (
                        "The elements array is STILL OPEN. Continue with comma + next "
                        "element object (or the first object if the array is empty). "
                        "When every element is present, close ] before writing any "
                        "top-level files/appState/_meta field."
                    )
                except json.JSONDecodeError:
                    boundary = (
                        "The elements array is closed; the outer scene object is still "
                        "open. Continue only with the missing top-level field(s)."
                    )
                discarded_tail = partial[len(prefix):][:1200]
                prompt = {
                    **input_prompt,
                    "messages": [
                        *input_prompt["messages"],
                        AIMessage(content=prefix),
                        HumanMessage(content=(
                            "The provider stream was interrupted. The assistant prefix above "
                            "ends at a complete JSON value boundary; its unfinished tail was "
                            "discarded. Continue EXACTLY after its last character. Return only "
                            "the missing JSON suffix, starting with the next required JSON "
                            "token (comma, element object, or closing delimiter). Do not repeat "
                            "the top-level object, earlier "
                            "elements, or earlier fields. Preserve all completed IDs, geometry, "
                            "styles, and source facts. Finish every remaining element and the "
                            "complete semantic sidecar/id_map using those existing element IDs. "
                            "No markdown fences or prose. The concatenated JSON will undergo "
                            "the original strict scene and semantic validation.\n\n"
                            + boundary + "\n\n"
                            "The interrupted response had begun the following discarded "
                            "fragment. It is NOT included in the preserved prefix. Regenerate "
                            "that unfinished value in full before proceeding to later values; "
                            "do not skip a shape or label because only its opening was received.\n"
                            + discarded_tail
                        )),
                    ],
                }
                entry = {
                    "after_attempt": attempt,
                    "transport_attempt": len(journal.attempts),
                    "prefix_characters": len(prefix),
                    "prefix_sha256": hashlib.sha256(prefix.encode()).hexdigest(),
                    "error": f"{type(exc).__name__}: {exc}",
                }
                continuations.append(entry)
                journal.continuations.append(entry)
                if journal.directory is not None:
                    journal.directory.mkdir(parents=True, exist_ok=True)
                    (journal.directory / f"continuation_{len(journal.continuations):02d}_prefix.txt").write_text(prefix, encoding="utf-8")
                    (journal.directory / "continuations.json").write_text(
                        json.dumps(journal.continuations, ensure_ascii=False, indent=2), encoding="utf-8",
                    )
                logger.info("[NativeContinuation] Preserved %d characters; requesting suffix %d/%d",
                            len(prefix), len(continuations), max_continuations)
                continue
            logger.warning("[NativeContinuation] Transient failure without a new checkpoint (%d/%d): %s",
                           attempt, max_attempts, type(exc).__name__)
            time.sleep(min(30, 4 * 2 ** (attempt - 1)))
            continue
        if prefix:
            return {"messages": [AIMessage(content=prefix + get_text_from_response(result))]}
        return result
    raise LLMResponseError("Native generation exhausted its attempt budget")
