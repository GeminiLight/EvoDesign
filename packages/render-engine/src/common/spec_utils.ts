// Ported from evodesign/agentic_system/common/spec_utils.py — keep in sync.
//
// Specification formatting and unwrapping utilities for inter-agent communication.

import { ValueError } from '../py/errors.ts';
import { pyIn } from '../py/eq.ts';
import { pyJsonDumps } from '../py/json.ts';
import { pySorted } from '../py/sort.ts';
import { pyRepr, pyStr } from '../py/str.ts';
import { isDict, pyOr, pyTypeName, truthy } from '../py/truthy.ts';

/** Format a specification dict into human-readable prompt text. */
export function format_specification_for_prompt(spec_name: string, spec_data: Record<string, unknown>): string {
  if (!truthy(spec_data)) {
    return '';
  }
  const lines = [`--- ${spec_name} ---`];
  for (const [dim_key, dim_value] of Object.entries(spec_data)) {
    if (isDict(dim_value)) {
      lines.push(`- [${dim_key}]:`);
      for (const [sub_key, sub_value] of Object.entries(dim_value)) {
        if (typeof sub_value === 'string') {
          lines.push(`    ${sub_key}: ${sub_value}`);
        } else {
          lines.push(`    ${sub_key}: ${pyJsonDumps(sub_value, { ensureAscii: false })}`);
        }
      }
    } else if (Array.isArray(dim_value)) {
      // Array format (e.g., topological_invariants)
      lines.push(`- [${dim_key}]:`);
      for (const item of dim_value) {
        if (typeof item === 'string') {
          lines.push(`    - ${item}`);
        } else if (isDict(item)) {
          const parts = Object.entries(item).map(([k, v]) => `${k}: ${pyStr(v)}`);
          lines.push(`    - ${parts.join(', ')}`);
        } else {
          lines.push(`    - ${pyStr(item)}`);
        }
      }
    } else {
      lines.push(`- [${dim_key}] ${pyStr(dim_value)}`);
    }
  }
  return lines.join('\n');
}

/** Build the assistant message content for conversation_history. */
export function build_assistant_content(
  spec_name: string,
  specification: Record<string, unknown> | null,
  instantiation: unknown,
): string {
  void spec_name;
  return pyJsonDumps({ specification: pyOr(specification, {}), instantiation },
    { ensureAscii: false, separators: [',', ':'] });
}

/** Pass validated artifacts, not obsolete tasks or failed repair attempts. */
export function build_stage_messages(
  system_prompt: string,
  task: string,
  upstream: [string, Record<string, unknown> | null, unknown][],
): Record<string, string>[] {
  const messages: Record<string, string>[] = [{ role: 'system', content: system_prompt }];
  for (const [stage_name, specification, instantiation] of upstream) {
    messages.push(
      { role: 'user', content: `Validated ${stage_name} result (upstream context):` },
      { role: 'assistant', content: build_assistant_content(stage_name, specification, instantiation) },
    );
  }
  messages.push({ role: 'user', content: task });
  return messages;
}

/** Unwrap agent LLM output into (specification, instantiation). */
export function unwrap_agent_output(
  raw_output: unknown,
  stage_name = 'Agent',
): [Record<string, unknown>, unknown] {
  if (!isDict(raw_output)) {
    throw new ValueError(
      `${stage_name} output must be a JSON object with top-level `
      + `'specification' and 'instantiation'; got ${pyTypeName(raw_output)}.`,
    );
  }

  const missing_keys = ['specification', 'instantiation'].filter((key) => !pyIn(key, raw_output));
  if (missing_keys.length) {
    const missing = missing_keys.map((key) => pyRepr(key)).join(', ');
    throw new ValueError(
      `${stage_name} output missing top-level key(s): ${missing}. `
      + "Expected {'specification': {...}, 'instantiation': ...}.",
    );
  }

  const specification = raw_output.specification;
  if (!isDict(specification)) {
    throw new ValueError(
      `${stage_name} specification must be a JSON object; `
      + `got ${pyTypeName(specification)}.`,
    );
  }

  return [specification, raw_output.instantiation];
}

/** Return the canonical Structure instantiation dict. */
export function unwrap_structure_instantiation(raw_structure: unknown): Record<string, unknown> {
  if (!isDict(raw_structure)) {
    return {};
  }

  let current: Record<string, unknown> = raw_structure;
  const seen = new Set<object>();
  while (isDict(current)) {
    if (seen.has(current)) {
      return current;
    }
    seen.add(current);

    let advanced = false;
    for (const wrapper_key of ['structure_instantiation', 'instantiation']) {
      const nested: unknown = Object.prototype.hasOwnProperty.call(current, wrapper_key) ? current[wrapper_key] : null;
      if (isDict(nested)) {
        current = nested;
        advanced = true;
        break;
      }
    }
    if (!advanced) {
      return current;
    }
  }

  return {};
}

/** Canonical wrapper for one generation-stage LLM output. */
export class StageOutput {
  readonly specification: Record<string, unknown>;
  readonly instantiation: unknown;

  constructor(specification: Record<string, unknown>, instantiation: unknown) {
    this.specification = specification;
    this.instantiation = instantiation;
    Object.freeze(this);
  }
}

/** Parse one canonical generation-stage LLM output. */
export function parse_stage_output(
  raw_output: unknown,
  stage_name: string,
  require_instantiation_dict = false,
  require_flat_id_map = false,
  reject_error_key = false,
): StageOutput {
  const [specification, instantiation] = unwrap_agent_output(raw_output, stage_name);

  if (require_instantiation_dict) {
    const has_error_key = isDict(instantiation) && pyIn('error', instantiation);
    if (!isDict(instantiation) || (reject_error_key && has_error_key)) {
      throw new ValueError(
        `${stage_name} output is not a valid dict: `
        + `${pyTypeName(instantiation)}`,
      );
    }
    if (require_flat_id_map) {
      _reject_categorized_instantiation(instantiation, stage_name);
    }
  }

  return new StageOutput(specification, instantiation);
}

/** Reject Styling/Layout outputs grouped under nodes/edges/groups. */
export function _reject_categorized_instantiation(
  instantiation: Record<string, unknown>,
  stage_name: string,
): void {
  const category_keys = pySorted(
    ['nodes', 'edges', 'groups'].filter((key) =>
      isDict(Object.prototype.hasOwnProperty.call(instantiation, key) ? instantiation[key] : null)),
  );
  if (category_keys.length) {
    const categories = category_keys.map((key) => pyRepr(key)).join(', ');
    throw new ValueError(
      `${stage_name} instantiation must be a flat id-keyed map; `
      + `do not nest entries under ${categories}.`,
    );
  }
}
