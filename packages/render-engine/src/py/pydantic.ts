// Minimal pydantic v2 ``BaseModel`` emulation for ported state/schema models
// (PHASE2_PLAN.md §2 rule 5). Added by WP13.
//
// A model is a TS class with a static ``model_fields`` table. Instances carry
// exactly the fields as own enumerable properties (so test/harness toPlain()
// and snapshots see the same keys as Python's ``model_dump()``).
//
//   export class MyState extends BaseModel {
//     static override model_fields = {
//       ...WorkflowStateBase.model_fields,
//       nodes: field({ type: 'list', default_factory: () => [] }),
//     };
//     declare nodes: unknown[];          // ``declare``: no class-field emit,
//   }                                    // which would clobber the base constructor
//
// Behaviour copied from pydantic (default config):
//   * unknown keyword arguments are ignored (extra='ignore');
//   * defaults: ``default`` is used as is (pydantic does not copy defaults of
//     immutable types; mutable defaults must use ``default_factory``);
//   * ``list``/``dict`` typed fields are shallow-copied on validation, like
//     pydantic rebuilding the container; ``any`` fields keep the reference;
//   * ``mode='before'`` field validators run before the type check;
//   * assignment is not validated (validate_assignment=False).
// Validation errors raise ``ValidationError`` with pydantic's first-line
// format ("N validation error(s) for Model"); the per-error lines are
// simplified.

import { ValueError } from './errors.ts';
import { pyDeepcopy } from './float_marks.ts';
import { PY_FLOAT_MARKS } from './json_decoder.ts';

export type FieldType =
  | 'any'
  | 'str' | 'optional_str'
  | 'bool' | 'optional_bool'
  | 'int' | 'optional_int'
  | 'float' | 'optional_float'
  | 'list' | 'optional_list'
  | 'dict' | 'optional_dict'
  | 'list_of_dict';

export interface FieldSpec {
  type?: FieldType;
  default?: unknown;
  default_factory?: () => unknown;
  /** ``@field_validator(name, mode='before')`` */
  before?: (value: unknown) => unknown;
  /** ``@field_validator(name)`` (mode='after') */
  after?: (value: unknown) => unknown;
  description?: string;
  /** Required field (no default). */
  required?: boolean;
  /**
   * Python annotation is ``float`` / ``Optional[float]``: pydantic coerces a
   * validated number to ``float``, so the stored value is marked as a Python
   * float (``PY_FLOAT_MARKS``; ``json.dumps`` prints ``7.0``). Defaults are not
   * validated and keep their literal type. Added by WP24 (ISSUES.md WP24-1).
   */
  py_float?: boolean;
}

export function field(spec: FieldSpec): FieldSpec {
  return spec;
}

export class ValidationError extends ValueError {
  constructor(readonly model: string, readonly errors: { loc: string; msg: string }[]) {
    super(`${errors.length} validation error${errors.length === 1 ? '' : 's'} for ${model}\n${errors.map((e) => `${e.loc}\n  ${e.msg}`).join('\n')}`);
    this.name = 'ValidationError';
  }
}

const isPlainObject = (value: unknown): value is Record<string, unknown> => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
};

function checkType(type: FieldType, value: unknown): { ok: true; value: unknown } | { ok: false; msg: string } {
  const optional = type.startsWith('optional_');
  if (optional && value === null) return { ok: true, value };
  const base = optional ? type.slice('optional_'.length) : type;
  switch (base) {
    case 'any':
      return { ok: true, value };
    case 'str':
      return typeof value === 'string' ? { ok: true, value } : { ok: false, msg: 'Input should be a valid string' };
    case 'bool':
      if (typeof value === 'boolean') return { ok: true, value };
      if (value === 0 || value === 1) return { ok: true, value: value === 1 };
      if (typeof value === 'string' && ['0', '1', 'true', 'false', 'yes', 'no', 'on', 'off', 't', 'f', 'y', 'n'].includes(value.toLowerCase())) {
        return { ok: true, value: ['1', 'true', 'yes', 'on', 't', 'y'].includes(value.toLowerCase()) };
      }
      return { ok: false, msg: 'Input should be a valid boolean' };
    case 'int':
      if (typeof value === 'number' && Number.isInteger(value)) return { ok: true, value };
      if (typeof value === 'boolean') return { ok: true, value: value ? 1 : 0 };
      if (typeof value === 'string' && /^\s*[-+]?\d+\s*$/.test(value)) return { ok: true, value: Number(value) };
      return { ok: false, msg: 'Input should be a valid integer' };
    case 'float':
      if (typeof value === 'number') return { ok: true, value };
      if (typeof value === 'boolean') return { ok: true, value: value ? 1 : 0 };
      if (typeof value === 'string' && value.trim() && !Number.isNaN(Number(value))) return { ok: true, value: Number(value) };
      return { ok: false, msg: 'Input should be a valid number' };
    case 'list':
      if (Array.isArray(value)) return { ok: true, value: [...value] };
      if (value instanceof Set) return { ok: true, value: [...value] };
      return { ok: false, msg: 'Input should be a valid list' };
    case 'dict':
      if (isPlainObject(value)) return { ok: true, value: { ...value } };
      if (value instanceof Map) return { ok: true, value: new Map(value) };
      return { ok: false, msg: 'Input should be a valid dictionary' };
    case 'list_of_dict':
      if (!Array.isArray(value)) return { ok: false, msg: 'Input should be a valid list' };
      for (const item of value) if (!isPlainObject(item)) return { ok: false, msg: 'Input should be a valid dictionary' };
      return { ok: true, value: value.map((item) => ({ ...(item as Record<string, unknown>) })) };
    default:
      return { ok: true, value };
  }
}

type ModelClass = { model_fields: Record<string, FieldSpec>; name: string };

export class BaseModel {
  /** Python ``module.Class`` of the model (snapshot graph labels, messages). */
  static pythonName = '';
  static model_fields: Record<string, FieldSpec> = {};

  constructor(data: Record<string, unknown> = {}) {
    const cls = this.constructor as unknown as ModelClass;
    const errors: { loc: string; msg: string }[] = [];
    const source = data ?? {};
    for (const [name, spec] of Object.entries(cls.model_fields)) {
      let value: unknown;
      const provided = Object.prototype.hasOwnProperty.call(source, name) && (source as Record<string, unknown>)[name] !== undefined;
      if (provided) {
        value = (source as Record<string, unknown>)[name];
        try {
          if (spec.before) value = spec.before(value);
          if (spec.type) {
            const checked = checkType(spec.type, value);
            if (!checked.ok) {
              errors.push({ loc: name, msg: checked.msg });
              continue;
            }
            value = checked.value;
          }
          if (spec.after) value = spec.after(value);
        } catch (error) {
          if (error instanceof ValidationError) throw error;
          errors.push({ loc: name, msg: `Value error, ${(error as Error).message}` });
          continue;
        }
      } else if (spec.default_factory) {
        value = spec.default_factory();
      } else if ('default' in spec) {
        value = spec.default;
      } else {
        errors.push({ loc: name, msg: 'Field required' });
        continue;
      }
      Object.defineProperty(this, name, { value, writable: true, enumerable: true, configurable: true });
      if (spec.py_float && provided && typeof value === 'number') markPyFloat(this, name);
    }
    if (errors.length) throw new ValidationError(cls.name, errors);
  }

  /** ``Model.model_validate(obj)`` */
  static model_validate<T extends BaseModel>(this: new (data: Record<string, unknown>) => T, obj: unknown): T {
    if (obj instanceof this) return obj;
    if (obj instanceof BaseModel) return new this(obj.model_dump());
    if (!isPlainObject(obj)) {
      throw new ValidationError((this as unknown as ModelClass).name, [{ loc: '', msg: 'Input should be a valid dictionary or instance' }]);
    }
    return new this(obj);
  }

  /** ``model_dump()``: field values, nested models dumped recursively. */
  model_dump(): Record<string, unknown> {
    const cls = this.constructor as unknown as ModelClass;
    const out: Record<string, unknown> = {};
    for (const name of Object.keys(cls.model_fields)) out[name] = dumpValue((this as Record<string, unknown>)[name]);
    return keepFloatMarks(this, out);
  }

  /** ``model_copy(update=..., deep=...)`` (no validation, like pydantic). */
  model_copy(update: Record<string, unknown> | null = null, deep = false): this {
    const copy = Object.create(Object.getPrototypeOf(this)) as this;
    for (const [key, value] of Object.entries(this)) {
      Object.defineProperty(copy, key, { value: deep ? pyDeepcopy(value) : value, writable: true, enumerable: true, configurable: true });
    }
    keepFloatMarks(this, copy);
    for (const [key, value] of Object.entries(update ?? {})) {
      Object.defineProperty(copy, key, { value, writable: true, enumerable: true, configurable: true });
      PY_FLOAT_MARKS.get(copy)?.delete(key); // update values are not validated: keep their own type
    }
    return copy;
  }

  /** Field names of this model class (``type(self).model_fields``). */
  static field_names(): string[] {
    return Object.keys(this.model_fields);
  }
}

function dumpValue(value: unknown): unknown {
  if (value instanceof BaseModel) return value.model_dump();
  if (Array.isArray(value)) return keepFloatMarks(value, value.map(dumpValue));
  if (isPlainObject(value)) return keepFloatMarks(value, Object.fromEntries(Object.entries(value).map(([k, v]) => [k, dumpValue(v)])));
  return value;
}

function markPyFloat(target: object, key: string): void {
  let marks = PY_FLOAT_MARKS.get(target);
  if (!marks) {
    marks = new Set();
    PY_FLOAT_MARKS.set(target, marks);
  }
  marks.add(key);
}

/** Rebuilt containers keep the integral-float marks of the source (values unchanged; see ISSUES.md WP22-1). */
function keepFloatMarks<T extends object>(source: object, copy: T): T {
  const marks = PY_FLOAT_MARKS.get(source);
  if (marks) PY_FLOAT_MARKS.set(copy, new Set(marks));
  return copy;
}
