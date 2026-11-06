// Python exception hierarchy used by the port (MIGRATION_PLAN.md §4).
//
// Ported code raises these instead of plain Error so that callers can catch
// by Python class (``except ValueError``) with ``instanceof``. The parity
// harness only checks *whether* a call raised, but keeping the classes makes
// ``try/except`` translations faithful.
//
// ``TypeError`` clashes with the JS global, so it is exported as
// ``PyTypeError`` (and aliased as ``TypeError`` for modules that prefer the
// Python name; importing it shadows the global in that module).

export class PyException extends Error {
  constructor(message = '') {
    super(message);
    this.name = new.target.name;
  }
}

export class ValueError extends PyException {}
export class PyTypeError extends PyException {}
export class KeyError extends PyException {}
export class IndexError extends PyException {}
export class AttributeError extends PyException {}
export class ZeroDivisionError extends PyException {}
export class OverflowError extends PyException {}
export class RuntimeError extends PyException {}
export class NotImplementedError extends RuntimeError {}
export class RecursionError extends RuntimeError {}
export class AssertionError extends PyException {}
export class StopIteration extends PyException {}
/** ``json.JSONDecodeError`` is a ``ValueError`` subclass in Python. */
export class JSONDecodeError extends ValueError {}

export { PyTypeError as TypeError };

/** ``assert cond, message`` */
export function pyAssert(condition: unknown, message = ''): asserts condition {
  if (!condition) throw new AssertionError(message);
}
