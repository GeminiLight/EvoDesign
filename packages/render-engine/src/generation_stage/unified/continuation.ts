// Ported from evodesign/agentic_system/generation_stage/unified/continuation.py — keep in sync.
// server-only (writes continuation evidence with node:fs; LangChain.js messages)
//
// Resume interrupted native scenes at complete JSON value boundaries.
//
// String positions are Python indices (code points): the scene text may hold
// CJK text or emoji, and the prefix lengths/sha256 are recorded in artifacts.

import { mkdirSync, writeFileSync } from '../../py/fs.ts';
import { join } from '../../py/path.ts';
import { AIMessage, HumanMessage } from '@langchain/core/messages';
import { LLMResponseError, _is_retryable_exception, _sleep } from '../../core/base_agent.ts';
import { get_text_from_response } from '../../utils/llm_output.ts';
import { sha256Hex } from '../../py/hash.ts';
import { PyJSONDecodeError, pyJsonLoadsExact, pyJsonRawDecode } from '../../py/json_decoder.ts';
import { pyJsonDumps } from '../../py/json.ts';
import { getLogger } from '../../py/logging.ts';
import { cpLen, cpSlice, isPyWhitespace } from '../../py/str.ts';
import { isDict, isStr } from '../../py/truthy.ts';
import { NativeStreamJournal, _error_label } from './transport_journal.ts';

const logger = getLogger('evodesign.agentic_system.generation_stage.unified.continuation');

/** Keep complete elements/fields verbatim; discard only the unfinished tail. */
export function complete_scene_prefix(text: string): string {
  const chars = [...text];
  const at = (offset: number): string => chars[offset] ?? '';
  const prefix = (end: number): string => chars.slice(0, end).join('');
  let index = 0;
  let checkpoint = 0;
  let array_checkpoint = 0;
  let has_elements = false;

  const whitespace = (offset: number): number => {
    while (offset < chars.length && isPyWhitespace(chars[offset])) {
      offset += 1;
    }
    return offset;
  };

  index = whitespace(index);
  if (at(index) !== '{') {
    return '';
  }
  index += 1;
  try {
    while (true) {
      let key: unknown;
      [key, index] = pyJsonRawDecode(text, whitespace(index));
      if (!isStr(key)) {
        break;
      }
      index = whitespace(index);
      if (at(index) !== ':') {
        break;
      }
      index = whitespace(index + 1);
      if (key === 'elements' && at(index) === '[') {
        array_checkpoint = index + 1;
        index = whitespace(index + 1);
        while (at(index) !== ']') {
          let element: unknown;
          [element, index] = pyJsonRawDecode(text, index);
          if (!isDict(element)) {
            return prefix(checkpoint);
          }
          has_elements = true;
          checkpoint = index;
          index = whitespace(index);
          if (at(index) !== ',') {
            break;
          }
          index = whitespace(index + 1);
        }
        if (at(index) !== ']') {
          break;
        }
        index += 1;
        has_elements = true;
      } else {
        [, index] = pyJsonRawDecode(text, index);
      }
      if (has_elements) {
        checkpoint = index;
      }
      index = whitespace(index);
      if (at(index) !== ',') {
        break;
      }
      index += 1;
    }
  } catch (error) {
    if (!(error instanceof PyJSONDecodeError)) throw error;
  }
  if (checkpoint) {
    return prefix(checkpoint);
  }
  return prefix(array_checkpoint);
}

/** ``json.loads(text)`` succeeds. */
function _parses(text: string): boolean {
  try {
    pyJsonLoadsExact(text);
  } catch (error) {
    if (error instanceof PyJSONDecodeError) return false;
    throw error;
  }
  return true;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type PromptDict = { messages: any[]; [key: string]: unknown };

/** Use the existing call budget for retries or productive suffix requests. */
export async function invoke_native_scene(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  agent: any,
  input_prompt: PromptDict,
  journal: NativeStreamJournal,
  max_attempts = 5,
  max_continuations = 2,
): Promise<unknown> {
  let prompt = input_prompt;
  let prefix = '';
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const continuations: Record<string, any>[] = [];
  for (let attempt = 1; attempt <= max_attempts; attempt += 1) {
    journal.last_output = '';
    let result: unknown;
    try {
      result = await agent.invoke(prompt);
      if (result === null || result === undefined || (isDict(result) && 'error' in result)) {
        throw new LLMResponseError('Native generation returned no usable response');
      }
    } catch (exc) {
      if (!_is_retryable_exception(exc)) {
        throw exc;
      }
      const partial = prefix + journal.last_output;
      let checkpoint: string;
      if (journal.last_output) {
        if (_parses(partial)) {
          // A broken final event must not discard an already complete
          // scene. The caller still runs strict schema/semantic checks.
          return { messages: [new AIMessage({ content: partial })] };
        }
        checkpoint = complete_scene_prefix(partial);
      } else {
        checkpoint = '';
      }
      if (attempt === max_attempts) {
        throw exc;
      }
      if (cpLen(checkpoint) > cpLen(prefix)) {
        if (continuations.length >= max_continuations) {
          throw exc;
        }
        prefix = checkpoint;
        let boundary: string;
        if (_parses(prefix + ']}')) {
          boundary = (
            'The elements array is STILL OPEN. Continue with comma + next '
            + 'element object (or the first object if the array is empty). '
            + 'When every element is present, close ] before writing any '
            + 'top-level files/appState/_meta field.'
          );
        } else {
          boundary = (
            'The elements array is closed; the outer scene object is still '
            + 'open. Continue only with the missing top-level field(s).'
          );
        }
        const discarded_tail = cpSlice(cpSlice(partial, cpLen(prefix)), 0, 1200);
        prompt = {
          ...input_prompt,
          messages: [
            ...input_prompt.messages,
            new AIMessage({ content: prefix }),
            new HumanMessage({ content: (
              'The provider stream was interrupted. The assistant prefix above '
              + 'ends at a complete JSON value boundary; its unfinished tail was '
              + 'discarded. Continue EXACTLY after its last character. Return only '
              + 'the missing JSON suffix, starting with the next required JSON '
              + 'token (comma, element object, or closing delimiter). Do not repeat '
              + 'the top-level object, earlier '
              + 'elements, or earlier fields. Preserve all completed IDs, geometry, '
              + 'styles, and source facts. Finish every remaining element and the '
              + 'complete semantic sidecar/id_map using those existing element IDs. '
              + 'No markdown fences or prose. The concatenated JSON will undergo '
              + 'the original strict scene and semantic validation.\n\n'
              + boundary + '\n\n'
              + 'The interrupted response had begun the following discarded '
              + 'fragment. It is NOT included in the preserved prefix. Regenerate '
              + 'that unfinished value in full before proceeding to later values; '
              + 'do not skip a shape or label because only its opening was received.\n'
              + discarded_tail
            ) }),
          ],
        };
        const entry = {
          after_attempt: attempt,
          transport_attempt: journal.attempts.length,
          prefix_characters: cpLen(prefix),
          prefix_sha256: sha256Hex(prefix),
          error: _error_label(exc),
        };
        continuations.push(entry);
        journal.continuations.push(entry);
        if (journal.directory !== null) {
          mkdirSync(journal.directory, { recursive: true });
          writeFileSync(
            join(journal.directory, `continuation_${String(journal.continuations.length).padStart(2, '0')}_prefix.txt`),
            prefix,
            'utf-8',
          );
          writeFileSync(
            join(journal.directory, 'continuations.json'),
            pyJsonDumps(journal.continuations, { ensureAscii: false, indent: 2 }),
            'utf-8',
          );
        }
        logger.info('[NativeContinuation] Preserved %d characters; requesting suffix %d/%d',
          cpLen(prefix), continuations.length, max_continuations);
        continue;
      }
      logger.warning('[NativeContinuation] Transient failure without a new checkpoint (%d/%d): %s',
        attempt, max_attempts, _error_label(exc).split(':')[0]);
      await _sleep(Math.min(30, 4 * 2 ** (attempt - 1)));
      continue;
    }
    if (prefix) {
      return { messages: [new AIMessage({ content: prefix + get_text_from_response(result) })] };
    }
    return result;
  }
  throw new LLMResponseError('Native generation exhausted its attempt budget');
}
