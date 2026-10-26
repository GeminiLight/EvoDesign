# Repository Guidelines

## Project Structure & Module Organization
`evo_diagram/` contains the core diagram engine. Use `agentic_system/` for structure, styling, layout, render, and refiner workflows; `evaluation/` and `scripts/` for analysis utilities; `resources/` for assets; and `dataset/test/data.json` as the default sample dataset.

`backend/app/` is the FastAPI service, organized by `api/`, `services/`, `models/`, `schemas/`, and `db/`. Runtime schema bootstrap is owned by `backend/app/db/bootstrap.py`; historical Supabase SQL lives under `backend/docs/archive/supabase/`.

`frontend/src/` is the Vite + React client. Keep route-level views in `pages/`, reusable UI in `components/`, API adapters in `services/`, hooks in `hooks/`, and shared types in `types/`. `evo_diagram/agentic_system/tool_services/` is a separate Next.js renderer and measurement service.

## Build, Test, and Development Commands
Use `./scripts/start_service.sh` from the repo root to launch the full stack: backend on `:3010`, renderer on `:3000`, and frontend on `:5175`.

- `cd frontend && npm run dev` starts the UI locally.
- `cd frontend && npm run build && npm run lint` builds the app and runs ESLint.
- `cd evo_diagram/agentic_system/tool_services && npm run dev` starts the renderer service.
- `cd backend && python -m uvicorn app.main:app --reload --port 3010` runs the API.
- `python -m evo_diagram.agentic_system.main --example 1 --dataset-path dataset/test/data.json` runs the diagram pipeline on sample data.

## Coding Style & Naming Conventions
Python uses 4-space indentation, `snake_case` for modules and functions, and type hints on public interfaces. Follow the existing import grouping and keep docstrings brief and purposeful.

TypeScript and React use 2-space indentation, semicolons, single quotes, `PascalCase` for components, `camelCase` for utilities, and `useX` for hooks. Follow `frontend/eslint.config.js`. No repo-wide formatter is configured, so keep changes consistent with nearby code.

## Testing Guidelines
CI enforces backend, engine, architecture, evaluation, baseline, frontend and renderer checks through `scripts/check_quality.sh`. Engine tests are discovered by directory; the real embedding integration is a separate local check. Add `test_*.py` files beside the module you change or under a dedicated `tests/` package. For evaluation smoke checks, run `python evaluation/analysis/test_data_availability.py --input-json ... --diagram-dir ...`.

Frontend changes should pass `npm run lint`, `npm run test:icons`, `npm run test:editor` and `npm run build`; include manual verification for major UI flows.

## Commit & Pull Request Guidelines
Recent commits favor short, imperative subjects. Prefixes such as `feat:`, `fix:`, `refactor:`, and `chore:` are common; avoid vague messages like `update`.

PRs should name the subsystem touched, summarize schema or env changes, list the commands you ran, and include screenshots for frontend changes. If a change adds new environment variables, document them in `.env.example` and call them out in the PR description.
