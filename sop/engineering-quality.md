# Engineering quality

[Contributor guides](README.md) · [Contributing](../CONTRIBUTING.md) · [Backend API](backend-api-surface.md)

Use the smallest set of checks that covers the change, then expand when results
or scope justify it. The shared entry point is
[`scripts/check_quality.sh`](../scripts/check_quality.sh); CI runs the same gates
through [the quality workflow](../.github/workflows/quality.yml).

## Prerequisites

Install the Python `dev` extra and both Node projects as described in
[Contributing](../CONTRIBUTING.md#prepare-a-development-environment). Run commands
below from the repository root. The script prefers `.venv/bin/python`; set
`PYTHON_BIN` to select another interpreter. It checks whitespace with
`git diff --check` before each target.

The standard gates do not intentionally call paid models. Dependency installation
and some builds can require network access. Real-model generation and the real
embedding integration are separate from the standard gates.

## Choose checks by change

Run `./scripts/check_quality.sh TARGET` with the targets below. Multiple affected
areas mean multiple targets; `all` runs every target.

| Change | Target | What it covers |
| --- | --- | --- |
| Import boundaries, canvas facade, API contracts or scripts | `architecture` | Generated contract freshness, architecture, repository documentation and script checks |
| FastAPI routes, services, authentication, persistence or schemas | `backend` | The full backend test directory |
| Generation, layout, rendering, verification, shared memory or knowledge evolution | `engine` | Pipeline smoke tests and engine tests; excludes user-memory and real embedding integration |
| Evaluation, scoring or result reuse | `evaluation` | Evaluation contracts and failure behavior |
| Baseline entry points or artifacts | `baselines` | Comparison-method contracts and output layout |
| Preference extraction, user memory or its storage | `user-memory` | The dedicated personal-memory test directory |
| Workspace, frontend API adapters or interactions | `frontend` | Frontend contracts, ESLint, icon tests, editor tests and production build |
| Next.js rendering, layout or text measurement service | `renderer` | Tool-service contracts, TypeScript check when configured and production build |
| Broad changes or release preparation | `all` | Every gate above |

For example, after changing an API consumed by the workspace:

```sh
./.venv/bin/python scripts/generate_frontend_api_contract.py --write
./scripts/check_quality.sh architecture
./scripts/check_quality.sh backend
./scripts/check_quality.sh frontend
```

The generator updates both `frontend/src/contracts/backendApi.generated.ts`
and `frontend/src/contracts/streamEvents.ts`. Review and commit generated changes
with their source. Do not hand-edit those files to bypass a stale-contract failure.

For a documentation-only change, check links, commands and statements against
the implementation, and run `./scripts/check_quality.sh architecture` for the
existing documentation and contract checks. Full builds or live model calls are
only needed if the change depends on behavior those checks cannot establish.

## Check the user journey

For changes affecting generation or editing, use representative architecture,
sequence and complex-flow diagrams. Test relevant combinations with icons on
and off. Keep the same inputs and settings for before/after comparisons.

| Step | Verify |
| --- | --- |
| Generate | Requested content, connections, labels and explicit user constraints survive; status and cancellation behave sensibly |
| Refine | Quality issues improve without losing content, locked elements or chosen icon settings; inspect failure/fallback reporting |
| Edit | Local edits stay local; unrelated objects, bindings and user changes remain intact; check undo/redo |
| Save and reopen | Text, layout, styling, icons and project identity survive a reload |
| Export | The exported format opens and matches the intended canvas; inspect clipping, labels and icons |
| Personal memory | Rules stay in their account/project scope; enabled/disabled state and guest/sign-in behavior remain correct |
| UI and recovery | Check narrow and wide layouts, keyboard focus, empty/loading/error states, and recovery after a failed request |

Use disposable local projects for destructive or recovery checks. Do not turn
an existing user's project or memory library into a test fixture. Automated
contract checks do not replace visual inspection of the affected flow.

## Record model and performance evidence

Real-model runs are a separate, explicitly budgeted validation step. Start with
a few shareable inputs. Record:

- Commit, model/provider identifier, relevant decoding/configuration settings,
  renderer, and icon/refinement/memory options.
- Input and expected behavior, initial result, refined result, failures and
  any fallback. Keep redacted artifacts locally unless approved for publication.
- Total and per-stage elapsed time, retries, repeated runs, and whether caches
  or an existing memory store were reused. Separate cold setup/download time.
- Quality regressions as well as improvements. A faster result that loses
  content or editability is not a successful optimization.

Do not claim a benchmark reproduction from a small smoke test. Unit-test passes
also do not establish visual quality or live-model latency.

The real Chroma/embedding check is deliberately outside `all` and CI. It can
download an embedding model and use substantial local compute:

```sh
./.venv/bin/python -m pytest evo_diagram/tests/design_memory/test_real_chroma_cosine.py -q
```

## Before opening a pull request

- State the user-visible change and the affected subsystems.
- List commands actually run, their outcomes, and skipped checks with reasons.
- Include before/after screenshots for UI changes and conditions for model runs.
- Document new configuration in the relevant `.env.example` or configuration
  file; describe schema/compatibility changes and migrations when applicable.
- Review `git diff --check`, `git diff --stat` and the staged diff. Keep secrets,
  local data and unrelated files out of the commit.
- For contributor-documentation changes, compare the shared files in both
  repositories and verify their local links in each.

## Troubleshooting

| Symptom | Next step |
| --- | --- |
| Wrong Python or missing imports | Activate the installed environment, or set `PYTHON_BIN=/absolute/path/to/python`; install the `dev` extra |
| Node install or build failure | Check Node is 22.12+ and run `npm ci` in the affected Node project using its committed lockfile |
| Native `canvas` install fails on Linux | Install the Cairo, Pango, JPEG, GIF, SVG and `pkg-config` development packages listed in the renderer CI job, then retry |
| Generated frontend contract is stale | Run the contract generator with `--write`, review the diff, then rerun `architecture` |
| Renderer-import boundary fails | Use the `canvas_environment` facade; keep renderer implementation imports inside their owning layer |
| HTTP 422 | Inspect the validation location and request schema; do not retry an invalid body as a model failure |
| Missing model settings during application tests | Use the existing injected test settings/dependency overrides; do not add a production secret to the test suite |
| An optional external integration is skipped | Report the skip and dependency; do not count it as a passing live integration |

Do not weaken assertions, suppress build errors or invent successful model
results to make a check pass. Fix the failure or state the remaining limitation.
