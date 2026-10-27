# Contributing to EvoDesign

Help make diagrams easier to create, refine and keep editing. Contributions can
improve the workspace, diagram quality, accessibility, documentation, tests or
research tools. Bug reports and discussions in English or Chinese are welcome.

| I want to… | Start here |
| --- | --- |
| Run the product | [Repository README](README.md) and [configuration](docs/configuration.md) |
| Make a first change | Environment and contribution workflow below |
| Choose the right checks | [Engineering quality guide](sop/engineering-quality.md) |
| Change or consume an API | [Backend API guide](sop/backend-api-surface.md) |
| Understand the system | [Architecture](wiki/02-system-architecture.md) and [web quality loop](wiki/web-quality-loop.md) |

## Prepare a development environment

Use Python 3.11+ and Node.js 22.12+. Clone your fork or an authorized development
checkout, then run these commands from its root. Reuse an existing environment
if one is already configured.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
npm ci --prefix frontend
npm ci --prefix evo_diagram/agentic_system/tool_services
```

These shell examples use Bash or Zsh; Windows users can use WSL. Installing
dependencies needs network access. If native `canvas` installation fails on
Linux, see the renderer prerequisites in the [quality guide](sop/engineering-quality.md#troubleshooting).

Follow this checkout's README and `.env.example` for runtime configuration.
Local model credentials are needed for generation, not for the standard test
gates. Keep an existing `.env` and local databases intact. With configuration
complete, `./scripts/start_service.sh` starts the API on `:3010`, renderer on
`:3000` and workspace on `:5175`.

## Make a focused change

1. Describe the problem and expected behavior. For a large feature or contract
   change, open an issue before investing in a broad implementation.
2. Create a branch from the current `main`; `fix/editor-save-state` is an example.
3. Make the smallest complete change, including relevant documentation and
   regression coverage. Keep unrelated formatting and dependency updates separate.
4. Run the checks for the areas you changed. Record manual verification and any
   checks you could not run; do not report unexecuted checks as passing.
5. Open a pull request using the repository template. Explain what users gain,
   how to reproduce the original problem, and how the result was verified.

## Where changes belong

| Area | Location |
| --- | --- |
| Workspace pages, controls and editor interactions | `frontend/src/pages/`, `frontend/src/components/`, `frontend/src/hooks/` |
| Browser API adapters and generated contracts | `frontend/src/services/`, `frontend/src/contracts/` |
| HTTP routes and business logic | `backend/app/api/`, `backend/app/services/` |
| Runtime database schema bootstrap | `backend/app/db/bootstrap.py` |
| Structure, styling, layout, verification and refinement | `evo_diagram/agentic_system/` |
| Canvas conversion, rendering and measurement | `evo_diagram/canvas_environment/`, `evo_diagram/agentic_system/render_engine/`, `evo_diagram/agentic_system/tool_services/` |
| Shared expertise, personal preferences and knowledge evolution | `evo_diagram/design_memory/`, `evo_diagram/user_memory/`, `evo_diagram/knowledge_evolution/` |
| Evaluation and comparison methods | `evaluation/`, `baselines/` |

Keep Python indentation at four spaces, use `snake_case`, and add type hints to
public interfaces. Match the React code's two-space indentation, semicolons and
single quotes; use `PascalCase` for components and `useX` for hooks. Follow the
existing module boundaries and ESLint rules rather than reformatting whole files.

The product, paper and algorithm are **EvoDesign**. Keep compatible `evo_diagram`
imports, schema keys and artifact identifiers; a branding change is not a reason
to break saved diagrams or downstream imports. Historical Supabase SQL under
`backend/docs/archive/supabase/` is reference material, not the active schema source.

## Verify the result

The [quality guide](sop/engineering-quality.md) maps changes to test commands.
Start with the affected areas. Use `./scripts/check_quality.sh all` for changes
spanning the stack or release preparation. Documentation-only changes need link,
command and factual checks; they do not require a paid generation run.

For editor or pipeline changes, preserve the complete user flow: generation →
refinement → local edit → save → reopen → export. Check icons on and off when
affected, respect locked elements and explicit user constraints, and include
desktop/mobile screenshots for visible UI changes. Test relevant error and
recovery states as well as the successful path.

Model tests can cost money. Use a small explicit sample set, your own configured
provider, and a recorded budget. Report model identifier, settings, input,
commit, quality findings and elapsed time. Separate first-run model downloads
from generation time. Unit tests and demonstration examples do not establish
paper benchmark results; use an independent judge for research comparisons.
Training and test datasets are released separately from the public code.

## Share useful, safe evidence

For a bug report, include expected versus actual behavior, reproduction steps,
commit, browser/OS and a minimal input you can share. For generation issues,
include the model identifier, icon/refinement settings and redacted stage timings
or reports. A small editable diagram is often more useful than a screenshot alone.

Keep `.env`, tokens, databases, runtime vector stores, private prompts, personal
preferences and private service endpoints out of commits and issue attachments.
Use account-scoped memory APIs; do not promote a user's private rules into shared
seed knowledge. Add sanitized examples with clear provenance and preserve
third-party license notices, including those for canvas libraries and fonts.
Report suspected credential exposure or authorization flaws privately to the
maintainers rather than attaching sensitive evidence to a public issue.

For the public website, paper metadata lives in `research/paper.json`. In a
checkout containing the website sources, run `node scripts/sync-research.mjs`
after changing it. Keep product instructions practical and research claims tied
to their evidence.

## Keep contributor documentation aligned

Maintainers keep `CONTRIBUTING.md`, the three guides under `sop/`, and
`.github/PULL_REQUEST_TEMPLATE.md` identical across the public and development
repositories. Apply documentation updates to both, validate links and commands
in each checkout, and compare the final files before merging. Repository READMEs
may differ, but both should link to this contribution entry point.
