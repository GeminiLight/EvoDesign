# evo_diagram Package Tests

This directory is for package-local tests of the Python diagram engine. These
tests should stay close to the modules they protect and should keep package-mode
imports working for `evo_diagram` consumers.

Keep tests here when they cover:

- package configuration and model loading
- generation and layout helpers
- knowledge evolution config, schemas, scoring, and maintenance helpers
- render engine conversion, routing, fitting, and audit logic
- refinement fixers and state models
- verification checks and data models

Do not put backend, frontend, baseline, cross-service, or full-repository
architecture tests here. Those belong in the root `tests` suite or the relevant
frontend test setup.

Run the full package suite from the repository root with:

```bash
python -m pytest evo_diagram/tests
```

When changing `agentic_system`, `canvas_environment`, or import aliases, also
run the touched tests from inside the package directory so package-mode imports
are exercised directly:

```bash
cd evo_diagram
../.venv/bin/python -m pytest tests/<target>
```
