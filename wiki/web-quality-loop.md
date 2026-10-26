# EvoDesign web quality loop

The streaming workspace uses design memory and automatic refinement for all account tiers. Excalidraw supports refinement; TLDraw still uses generation and verification, and the result panel explains that refinement is unavailable for that canvas.

See [review/refinement latency](quality-loop-latency.md) for parallel preparation, render reuse, readable review images, and real-model timing comparisons.

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

The bundled seed corpus contains 126 existing project strategies (`evo_diagram/design_memory/seeds/web_strategies.json`). Each account gets a separate store under a hashed user ID; guests can use seeded knowledge but do not write learned strategies. Store directories stay outside Git. Embedding model weights are shared in each server process while database contents remain separate. The first use can download/load the embedding model and index the seed; subsequent requests reuse the model and index.

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

## Real-model validation (2026-10-16)

One authenticated web run with Kimi k3 generated an eight-node research-review flowchart with two feedback loops. It retrieved two seed strategies, applied seven edits in one refinement round, and improved the model's visual score from 7.5 to 8.5. Objective findings fell from one minor issue to zero. The system saved one private strategy; a subsequent related query retrieved it first in 1.616 seconds.

Measured pipeline time was 20m 56s: memory preparation/retrieval 40s, generation 4m 12s, initial render 42s, first review 4m 8s, refinement 6m 36s, final review 4m 17s, and learning 20s. Model calls remain the main latency source. This single-case validation does not establish general performance gains.

![Workspace quality report and refined diagram](assets/web-quality-loop.png)

Optional, portable node icons are documented in [node-icons.md](node-icons.md).

See the [architecture, sequence and complex-flow matrix](diagram-matrix-validation.md)
for icon on/off checks and a deliberate sequence fault-recovery test.

## Unified policy validation (2026-10-16)

The [follow-up comparison](quality-loop-latency.md#shared-policy-and-scheduling-follow-up-2026-10-16)
uses the same perturbed scene for old/new refinement and a fresh authenticated
workspace run. Both refined results removed four major defects and scored 9.0;
the new result was delivered before its real-model learning job finished.

![Fresh blue, cyan and violet flowchart with four optional icons](assets/unified-quality-flowchart.png)
