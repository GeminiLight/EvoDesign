// No-op stand-in for Python ``logging`` (MIGRATION_PLAN.md §4).
//
// ``logger = logging.getLogger(__name__)`` becomes
// ``const logger = getLogger('<python module>')``. Every call is ignored;
// logging never influences rendering output in the Python engine.

export interface PyLogger {
  readonly name: string;
  debug(...args: unknown[]): void;
  info(...args: unknown[]): void;
  warning(...args: unknown[]): void;
  warn(...args: unknown[]): void;
  error(...args: unknown[]): void;
  exception(...args: unknown[]): void;
  critical(...args: unknown[]): void;
  log(level: number, ...args: unknown[]): void;
  isEnabledFor(level: number): boolean;
}

const noop = (): void => {};
const loggers = new Map<string, PyLogger>();

export function getLogger(name = 'root'): PyLogger {
  let logger = loggers.get(name);
  if (!logger) {
    logger = {
      name,
      debug: noop,
      info: noop,
      warning: noop,
      warn: noop,
      error: noop,
      exception: noop,
      critical: noop,
      log: noop,
      isEnabledFor: () => false,
    };
    loggers.set(name, logger);
  }
  return logger;
}

export const DEBUG = 10;
export const INFO = 20;
export const WARNING = 30;
export const ERROR = 40;
export const CRITICAL = 50;
