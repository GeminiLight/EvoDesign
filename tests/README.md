# Repository Test Suite

This directory is for tests that exercise repository-level boundaries rather
than a single `evo_diagram` package module.

Keep tests here when they cover:

- backend API, service, or database boundaries
- baseline entrypoints and output contracts
- the standalone `canvas_environment` facade and import boundary
- cross-stage pipeline smoke behavior
- repository architecture and import hygiene
- repository documentation source-of-truth checks for live entrypoints

Do not add package-local generation, refinement, render engine, verification, or
knowledge evolution unit tests here. Put those under `evo_diagram/tests` so
package-mode imports are exercised directly.

Run this suite with:

```bash
python -m pytest tests
```

Run only the baseline contract subset with:

```bash
./scripts/check_quality.sh baselines
```

This suite complements, but does not replace, `evo_diagram/tests`; algorithm
package changes should still run the relevant package-local tests there.
