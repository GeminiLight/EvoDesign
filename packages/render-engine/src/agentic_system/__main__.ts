// Ported from evodesign/agentic_system/__main__.py — keep in sync.
// server-only (CLI entry)
//
// Entry point for running Text2Diagram workflow.
//
// Usage:
//     npx tsx src/agentic_system/__main__.ts --example 1
//     npx tsx src/agentic_system/__main__.ts --start 1 --end 10

import { fileURLToPath } from 'node:url';
import { SystemExit, main } from './main.ts';

export { main };

// ``if __name__ == "__main__": sys.exit(main())``
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main().then(
    (code) => process.exit(code),
    (error) => {
      if (error instanceof SystemExit) process.exit(error.code);
      throw error;
    },
  );
}
