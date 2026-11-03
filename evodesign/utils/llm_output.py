"""
LLM Output Processing Utilities

Shared utilities for processing LLM outputs across the project.
"""

import re
import json
from typing import Any

# The whole (stripped) response is one ```json / ``` fenced block.
_SOLE_FENCE = re.compile(r"```(?:json|JSON)?[ \t]*\n([\s\S]*?)\n?[ \t]*```")


def _split_json_strings(text: str) -> list[tuple[bool, str]]:
    """Split *text* into ``(is_string, chunk)`` runs.

    String runs include their quotes; an unterminated string runs to the end.
    """
    parts: list[tuple[bool, str]] = []
    idx = 0
    length = len(text)
    while idx < length:
        quote = text.find('"', idx)
        if quote < 0:
            parts.append((False, text[idx:]))
            break
        if quote > idx:
            parts.append((False, text[idx:quote]))
        pos = quote + 1
        while pos < length:
            char = text[pos]
            if char == "\\":
                pos += 2
                continue
            if char == '"':
                break
            pos += 1
        end = min(pos + 1, length)
        parts.append((True, text[quote:end]))
        idx = end
    return parts


# A value can end with one of these characters right before a missing comma.
_VALUE_END_CHARS = set("}]0123456789'")


def fix_json_string(json_str: str) -> str:
    """
    Attempt to fix common JSON formatting issues.

    Repairs (trailing commas, duplicate commas, a missing comma before the
    next ``"key":``) are applied only to structural text: string literals are
    copied verbatim, so a label such as ``"a, }"`` is never rewritten.

    Args:
        json_str: Potentially malformed JSON string

    Returns:
        Fixed JSON string
    """
    parts = _split_json_strings(json_str)

    # Structural cleanup inside non-string runs.
    cleaned: list[tuple[bool, str]] = []
    for is_string, chunk in parts:
        if not is_string:
            previous = None
            while previous != chunk:
                previous = chunk
                chunk = re.sub(r',(\s*),', r',\1', chunk)
            chunk = re.sub(r',(\s*)(?=[}\]])', r'\1', chunk)
        cleaned.append((is_string, chunk))

    # Missing comma before a key: <value> <ws> "key" <ws> :
    out: list[str] = []
    for index, (is_string, chunk) in enumerate(cleaned):
        if is_string and index > 0:
            following = cleaned[index + 1][1] if index + 1 < len(cleaned) else ""
            is_key = not cleaned[index + 1][0] if index + 1 < len(cleaned) else False
            is_key = is_key and following.lstrip().startswith(":")
            if is_key:
                gap_is_string, gap = cleaned[index - 1]
                if gap_is_string:
                    # "value""key": with nothing in between.
                    out.append(",")
                elif not gap.strip() and index >= 2 and cleaned[index - 2][0]:
                    # "value" <ws> "key":
                    out[-1] = "," + gap
                else:
                    stripped = gap.rstrip()
                    if stripped and stripped[-1] in _VALUE_END_CHARS and gap != stripped:
                        out[-1] = stripped + "," + gap[len(stripped):]
        out.append(chunk)
    return "".join(out)


def _extract_balanced_json_substring(text: str, start_idx: int) -> str | None:
    opening = text[start_idx]
    matching = {"{": "}", "[": "]"}
    if opening not in matching:
        return None

    stack = [matching[opening]]
    in_string = False
    escape_next = False

    for idx in range(start_idx + 1, len(text)):
        char = text[idx]

        if in_string:
            if escape_next:
                escape_next = False
            elif char == "\\":
                escape_next = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char in matching:
            stack.append(matching[char])
        elif char in ("}", "]"):
            if not stack or char != stack[-1]:
                return None
            stack.pop()
            if not stack:
                return text[start_idx:idx + 1]

    return None


def _loads_json_from_start(text: str, start_idx: int) -> Any:
    return _loads_json_span(text, start_idx)[0]


def _loads_json_span(text: str, start_idx: int) -> tuple[Any, int]:
    """Parse the JSON value at *start_idx*; return ``(value, end_idx)``."""
    decoder = json.JSONDecoder(strict=False)
    try:
        return decoder.raw_decode(text, start_idx)
    except json.JSONDecodeError as raw_error:
        json_str = _extract_balanced_json_substring(text, start_idx)
        if json_str is None:
            raise raw_error

        fixed_json = fix_json_string(json_str)
        return json.loads(fixed_json, strict=False), start_idx + len(json_str)


def _loads_embedded_json(output: str) -> Any:
    """Return the first *outermost* parsable JSON value embedded in prose.

    When a candidate fails to parse but is balanced, values nested inside it
    are only a fallback: a later top-level value is preferred over, e.g., the
    first inner ``{...}`` of a broken wrapper object.
    """
    first_error: json.JSONDecodeError | None = None
    nested_fallback: tuple[bool, Any] = (False, None)
    skip_until = -1

    for match in re.finditer(r"[\[{]", output):
        start = match.start()
        nested = start < skip_until
        if nested and nested_fallback[0]:
            continue
        try:
            value, end = _loads_json_span(output, start)
        except json.JSONDecodeError as exc:
            if first_error is None:
                first_error = exc
            if not nested:
                balanced = _extract_balanced_json_substring(output, start)
                if balanced is not None:
                    skip_until = start + len(balanced)
            continue
        if not nested:
            return value
        nested_fallback = (True, value)

    if nested_fallback[0]:
        return nested_fallback[1]

    if first_error is not None:
        raise first_error

    raise json.JSONDecodeError("No JSON object or array start found", output, 0)


def convert_json_output(output: str, *, strict_response: bool = False) -> Any:
    """
    Convert raw JSON output from the LLM into structured format.

    Args:
        output: The JSON output from the LLM
        strict_response: When true, require the whole response to be exactly one
            JSON value after optional reasoning tags are removed.

    Returns:
        Structured JSON output
    """
    output = output.strip()

    # Strip reasoning wrappers that some providers prepend before the actual JSON.
    if "<think>" in output or "<thought>" in output:
        _, output = extract_think_and_result(output)
        output = output.strip()

    if strict_response:
        # A response that is exactly one fenced block carries the same single
        # JSON value; unwrap it instead of paying for a full regeneration.
        fenced = _SOLE_FENCE.fullmatch(output)
        if fenced:
            output = fenced.group(1).strip()
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise json.JSONDecodeError(
                "Expected response to be exactly one JSON value; "
                f"{exc.msg}",
                output,
                exc.pos,
            ) from exc

    # Try 0: Extract JSON from ```json ... ``` code block first
    json_block_match = re.search(r'```json\s*([\s\S]*?)\s*```', output)
    if json_block_match:
        json_str = json_block_match.group(1).strip()
        try:
            return json.loads(json_str, strict=False)
        except json.JSONDecodeError:
            # Try fixing common issues
            try:
                fixed_json = fix_json_string(json_str)
                return json.loads(fixed_json, strict=False)
            except json.JSONDecodeError:
                pass  # Fall through to other methods

    # Try 0.5: Extract JSON from XML-like wrapper tags
    xml_block_matches = re.findall(r"<([A-Za-z_][\w:.-]*)>\s*([\s\S]*?)\s*</\1>", output)
    for _, inner_content in xml_block_matches:
        candidate = inner_content.strip()
        if not candidate:
            continue
        if not (
            candidate.startswith("{")
            or candidate.startswith("[")
            or candidate.startswith("```json")
            or candidate.startswith("```")
            or "{" in candidate
            or "[" in candidate
        ):
            continue
        try:
            return convert_json_output(candidate)
        except json.JSONDecodeError:
            continue

    # Remove markdown code blocks (for backward compatibility)
    if output.startswith("```json"):
        output = output[7:].strip()
    if output.startswith("```"):
        output = output[3:].strip()
    if output.endswith("```"):
        output = output[:-3].strip()
    if output.endswith("```json"):
        output = output[:-7].strip()

    # Try 1: Direct parsing
    try:
        return json.loads(output, strict=False)
    except json.JSONDecodeError as e1:
        try:
            return _loads_embedded_json(output)
        except json.JSONDecodeError:
            raise json.JSONDecodeError(
                f"No valid JSON found in response: {e1}",
                output,
                0
            )


def get_text_from_response(response) -> str:
    """
    Extract text content from LLM response object.

    Args:
        response: LLM response object

    Returns:
        Text content string
    """
    if hasattr(response, 'content'):
        # Handle list of content blocks (e.g. for Anthropic or reasoning models)
        if isinstance(response.content, list):
            text_parts = []
            for block in response.content:
                if isinstance(block, dict):
                    if block.get('type') == 'text':
                        text_parts.append(block.get('text', ''))
                    elif block.get('type') == 'thought':
                        # We might want to keep thought tags if they're not excluded later
                        text_parts.append(f"<thought>{block.get('thought', '')}</thought>")
                elif hasattr(block, 'text'):
                    text_parts.append(block.text)
            return "\n".join(text_parts)
        return response.content

    if isinstance(response, dict):
        if 'messages' in response:
            # Recurse so list-of-content-blocks in the last message get
            # flattened by the branch above, not returned raw.
            return get_text_from_response(response['messages'][-1])
        if 'choices' in response and len(response['choices']) > 0:
            choice = response['choices'][0]
            if 'message' in choice:
                msg = choice['message']
                content = msg.get('content', '')
                # Some providers put reasoning in reasoning_content
                reasoning = msg.get('reasoning_content') or msg.get('reasoning')
                if reasoning:
                    # If content is empty but reasoning has actual content,
                    # use reasoning as the response (some providers use this pattern)
                    if not content and reasoning.strip():
                        content = reasoning
                    else:
                        content = f"<thought>{reasoning}</thought>\n{content}"
                return content
            if 'text' in choice:
                return choice['text']

    return str(response)


def extract_think_and_result(info: str) -> tuple[str, str]:
    """
    Extract think and result content from the response info.

    Args:
        info: Response text containing think tags

    Returns:
        Tuple of (think_content, result_content)
    """
    # Match <think>...</think> or <thought>...</thought> tags (used by reasoning models)
    think_match = re.search(r"<(?:think|thought)>(.*?)</(?:think|thought)>", info, re.DOTALL)
    think_content = think_match.group(1).strip() if think_match else ''
    result_content = re.sub(r"<(?:think|thought)>.*?</(?:think|thought)>", "", info, flags=re.DOTALL).strip()
    return think_content, result_content


def preprocess_response(
    response: Any,
    only_text: bool = True,
    exclude_think: bool = False,
    json_output: bool = False,
    strict_json_output: bool = False,
) -> Any:
    """
    Preprocess LLM response to extract and format content.

    Args:
        response: Raw LLM response
        only_text: Extract only text content
        exclude_think: Remove think blocks
        json_output: Parse as JSON
        strict_json_output: Require the entire response to be exactly JSON

    Returns:
        Processed response content
    """
    if only_text or exclude_think or json_output:
        response = get_text_from_response(response)

    if exclude_think:
        think_content, result_content = extract_think_and_result(response)
        response = result_content

    if json_output:
        try:
            response = convert_json_output(
                response,
                strict_response=strict_json_output,
            )
        except json.JSONDecodeError as e:
            response = {
                "error": "Invalid JSON output",
                "raw_content": response,
                "parse_error": str(e)
            }
            raise e

    return response


# For backward compatibility
__all__ = [
    "fix_json_string",
    "convert_json_output",
    "get_text_from_response",
    "extract_think_and_result",
    "preprocess_response",
]
