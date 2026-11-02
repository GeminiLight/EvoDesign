# EvoDesign web quality loop

The streaming workspace uses design memory and automatic refinement for all account tiers. Excalidraw supports refinement; TLDraw still uses generation and verification, and the result panel explains that refinement is unavailable for that canvas.

The sequence and fallback rules below describe the current quality loop. See
[performance notes](performance.md) for measured first-load behavior.

## Run sequence

1. Initialize the account's design store, resolve diagram type, and retrieve relevant design strategies. Explicit user DNA remains the highest-priority design guidance. A selected diagram type skips the Router model; automatic selection still uses it.
2. Generate structure, styling, and layout; render an editable first draft.
3. Run objective geometry checks and the vision critic.
4. Refine when objective critical, major, or minor findings remain, the critic score is below 7, or an explicit user constraint is violated. Stop after two rounds by default. Regressed rounds are rolled back.
5. Recheck the final candidate. Web and CLI use the same policy. Keep the original if the refiner fails, leaves objective issues unresolved, fails verification, violates user constraints, increases objective severity, or lowers the visual score by more than 0.5. A zero-edit low-score attempt is unresolved. Informational findings alone do not trigger refinement. Applied-edit counts exclude rolled-back rounds.
6. Distill strategies only from surviving edits when both visual reviews succeeded and quality improved: fewer objective findings, corrected explicit constraints, or at least +0.5 visual score, without a visual decline. The accepted result must also meet the visual target (7/10). Queue learning after the diagram is delivered. Save these as private, scoped strategies, not universal principles.

The workspace reports retrieval count, accepted edits, saved lessons, model scores, and measured stage durations. Reports live in snapshot metrics and reappear when that generated snapshot is opened. Scores are model estimates, not benchmark results or proof of universal improvement. Clean first drafts can skip refinement; not every run yields a useful new lesson.

## User constraints and learning status

The original brief, additional requirements, explicit DNA, selected diagram type,
locked elements and optional icon policy travel to both the critic and refiner.
Partial icon coverage is intentional; a disabled icon option forbids adding icons.
Explicit user colors override default catalog palettes, including semantic color
suggestions. Any edit batch or derived geometry repair that changes a locked
node, its text or its icon is rolled back.

Snapshot reports distinguish `passed`, `needs_attention` and `unverified`; a
completed geometric repair is not a claim that every visual target was met.
Missing final visual evidence cannot replace a previously reviewed result.

Accepted learning jobs copy their report into the private store's `.learning`
directory before temporary generation files are removed. They run with bounded
concurrency (two per process), use a per-job file lock, and resume queued or
interrupted work on startup. No credentials are stored in job files. Failure is
reported as unavailable and never discards the diagram. The authenticated
`GET /api/v1/diagram/learning/{job_id}` endpoint exposes only that account's job;
the report polls it and refreshes it when a saved snapshot is reopened. Learning
is best-effort: model extraction can still return no useful lesson.

## Design stores

The bundled seed corpus contains 129 existing project strategies (`evo_diagram/design_memory/seeds/web_strategies.json`). Each account gets a separate store under a hashed user ID; guests can use seeded knowledge but do not write learned strategies. Store directories stay outside Git. Embedding model weights are shared in each server process while database contents remain separate. The first use can download/load the embedding model and index the seed; subsequent requests reuse the model and index.

## Configuration

See `backend/.env.example`. Defaults:

- `AUTO_REFINE_ENABLED=true`, `AUTO_REFINE_MAX_ITERATIONS=2` (1–3).
- `DESIGN_MEMORY_ENABLED=true`, `DESIGN_MEMORY_TOP_K=2` per layer (1–5).
- `DESIGN_MEMORY_LEARNING=true` for authenticated accounts.
- `DESIGN_MEMORY_MODEL=Qwen/Qwen3-Embedding-0.6B`.
- `DESIGN_MEMORY_PATH=data/web-design-memory`; relative memory paths resolve from the repository root.
- `RETAIN_GENERATION_ARTIFACTS=false`; enable locally to retain intermediate images and `generation_result.json` in each request's stream directory.

Model/provider definitions stay in `configs/models.yaml`; the Kimi configuration supports `reasoning_effort: low` and a 16,384-token output cap. Real latency depends strongly on the model and diagram complexity. SSE keepalive comments preserve the connection during long calls; the UI keeps its overall generation deadline.

The synchronous compatibility endpoint receives memory and refinement settings, but the progressive report and online strategy learning are implemented in the streaming workflow used by the workspace.

## Validation records

The dated [quality-loop and icon validation records](../archive/validation/release-notes.md#quality-and-icon-validation-2026-10-16) are kept with release history.
