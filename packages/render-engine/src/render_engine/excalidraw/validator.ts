// Ported from evodesign/agentic_system/render_engine/excalidraw/validator.py — keep in sync.
//
// Excalidraw manifest compliance checker.

import { pyGet, pyGetItem } from '../../py/dict.ts';
import { pyIn } from '../../py/eq.ts';
import { pySorted } from '../../py/sort.ts';
import { pyStr } from '../../py/str.ts';
import { isDict, isList, pyLen, truthy } from '../../py/truthy.ts';

type Dict = Record<string, unknown>;

export const REQUIRED_ELEMENT_FIELDS: ReadonlySet<string> = new Set(['id', 'type', 'x', 'y', 'width', 'height', 'seed', 'version', 'isDeleted']);

export const VALID_ELEMENT_TYPES: ReadonlySet<string> = new Set([
  'rectangle', 'ellipse', 'diamond', 'triangle', 'line', 'arrow',
  'text', 'image', 'freedraw', 'frame',
]);

export function _require_fields(label: string, payload: Dict, required: Iterable<string>): string[] {
  const missing = pySorted([...required]).filter((field) => !pyIn(field, payload));
  return missing.map((field) => `${label} missing field: ${field}`);
}

/** Validate a single Excalidraw element. */
export function _validate_element(elem: Dict, index: number, all_ids: Set<unknown>): [string[], string[]] {
  let errors: string[] = [];
  const warnings: string[] = [];
  let label = `elements[${index}]`;

  if (!isDict(elem)) {
    errors.push(`${label} must be an object`);
    return [errors, warnings];
  }

  const eid = pyGet(elem, 'id', `<missing-id-${index}>`);
  label = `elements[${index}] (id=${pyStr(eid)})`;

  // Required fields
  errors = errors.concat(_require_fields(label, elem, REQUIRED_ELEMENT_FIELDS));

  // Type validation
  const elem_type = pyGet(elem, 'type');
  if (truthy(elem_type) && !pyIn(elem_type, VALID_ELEMENT_TYPES)) {
    warnings.push(`${label} uses non-standard type: ${pyStr(elem_type)}`);
  }

  // Arrow-specific validation
  if (elem_type === 'arrow') {
    const points = pyGet(elem, 'points');
    if (!isList(points) || pyLen(points) < 2) {
      errors.push(`${label} arrow must have points array with at least 2 points`);
    }

    for (const binding_key of ['startBinding', 'endBinding']) {
      const binding = pyGet(elem, binding_key);
      if (truthy(binding) && isDict(binding)) {
        const ref_id = pyGet(binding, 'elementId');
        if (truthy(ref_id) && !pyIn(ref_id, all_ids)) {
          errors.push(`${label} ${binding_key} references missing elementId: ${pyStr(ref_id)}`);
        }
      }
    }
  }

  // Text-specific validation
  if (elem_type === 'text') {
    const container_id = pyGet(elem, 'containerId');
    if (truthy(container_id) && !pyIn(container_id, all_ids)) {
      errors.push(`${label} containerId references missing element: ${pyStr(container_id)}`);
    }
  }

  // Image-specific validation
  if (elem_type === 'image') {
    if (!pyIn('fileId', elem)) {
      warnings.push(`${label} image element missing fileId`);
    }
  }

  return [errors, warnings];
}

/** Check bidirectional consistency of boundElements. */
export function _validate_bound_elements_consistency(elements: Dict[]): string[] {
  const warnings: string[] = [];

  // Build map: element_id -> set of bound element IDs
  const bound_map = new Map<unknown, Set<unknown>>();
  for (const elem of elements) {
    const eid = pyGet(elem, 'id', '');
    const bound_elems = pyGet(elem, 'boundElements');
    if (isList(bound_elems)) {
      bound_map.set(eid, new Set(bound_elems.filter((b) => isDict(b)).map((b) => pyGet(b, 'id', ''))));
    } else {
      bound_map.set(eid, new Set());
    }
  }

  // Check text containerId <-> boundElements consistency
  for (const elem of elements) {
    if (pyGet(elem, 'type') === 'text') {
      const container_id = pyGet(elem, 'containerId');
      const text_id = pyGet(elem, 'id', '');
      if (truthy(container_id) && pyIn(container_id, bound_map)) {
        if (!pyIn(text_id, bound_map.get(container_id))) {
          warnings.push(
            `text element ${pyStr(text_id)} has containerId=${pyStr(container_id)} `
            + "but container's boundElements does not reference it",
          );
        }
      }
    }
  }

  return warnings;
}

/**
 * Validate an Excalidraw manifest JSON for structural compliance.
 * Returns a report dict with is_valid, error_count, warning_count, errors,
 * warnings and counts.
 */
export function validate_excalidraw_manifest(manifest_data: Dict): Dict {
  let errors: string[] = [];
  let warnings: string[] = [];

  if (!isDict(manifest_data)) {
    return {
      is_valid: false,
      error_count: 1,
      warning_count: 0,
      errors: ['Manifest root must be a JSON object.'],
      warnings: [],
      counts: {},
    };
  }

  // Top-level structure
  const elements = pyGet(manifest_data, 'elements');
  const files = pyGet(manifest_data, 'files');

  if (!isList(elements)) {
    errors.push("Manifest missing or invalid 'elements' (must be a list)");
  }
  if (files !== null && !isDict(files)) {
    warnings.push("'files' should be a dict if present");
  }

  if (!isList(elements)) {
    return {
      is_valid: false,
      error_count: errors.length,
      warning_count: warnings.length,
      errors,
      warnings,
      counts: {},
    };
  }

  // Collect all IDs for reference checks
  const all_ids = new Set<unknown>();
  for (const elem of elements) {
    if (isDict(elem) && pyIn('id', elem)) {
      const eid = pyGetItem(elem, 'id');
      if (pyIn(eid, all_ids)) {
        errors.push(`Duplicate element ID: ${pyStr(eid)}`);
      }
      all_ids.add(eid);
    }
  }

  // Validate each element
  const counts: Record<string, number> = {
    total_elements: elements.length,
    shapes: 0,
    arrows: 0,
    texts: 0,
    images: 0,
    other: 0,
  };

  elements.forEach((elem, i) => {
    const [elem_errors, elem_warnings] = _validate_element(elem as Dict, i, all_ids);
    errors = errors.concat(elem_errors);
    warnings = warnings.concat(elem_warnings);

    const elem_type = isDict(elem) ? pyGet(elem, 'type', '') : '';
    if (elem_type === 'arrow') {
      counts.arrows += 1;
    } else if (elem_type === 'text') {
      counts.texts += 1;
    } else if (elem_type === 'image') {
      counts.images += 1;
    } else if (['rectangle', 'ellipse', 'diamond', 'triangle', 'frame'].includes(elem_type as string)) {
      counts.shapes += 1;
    } else {
      counts.other += 1;
    }
  });

  // Check boundElements consistency
  warnings = warnings.concat(_validate_bound_elements_consistency(elements as Dict[]));

  // Validate files references from image elements
  if (isDict(files)) {
    for (const elem of elements) {
      if (isDict(elem) && pyGet(elem, 'type') === 'image') {
        const file_id = pyGet(elem, 'fileId');
        if (truthy(file_id) && !pyIn(file_id, files)) {
          warnings.push(`Image element ${pyStr(pyGet(elem, 'id'))} references missing fileId: ${pyStr(file_id)}`);
        }
      }
    }
  }

  return {
    is_valid: errors.length === 0,
    error_count: errors.length,
    warning_count: warnings.length,
    errors,
    warnings,
    counts,
  };
}
