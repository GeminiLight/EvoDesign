# Configuration

## Package name migration

The Python engine now lives in `evodesign/` and imports use `evodesign.*`.
Update imports from `evo_diagram.*`, use `python -m evodesign.agentic_system.main`,
and replace `scripts/run_evodiagram.sh` with `scripts/run_evodesign.sh`.
After updating a checkout, reinstall it with `python -m pip install -e ".[backend,test]"`
and restart running services. The standalone `evodesign` command remains owned by
the lightweight `evodesign-cli` package; it does not require the engine.

New research outputs and method labels use `evodesign`. Historical `evodiagram`
method IDs and experiment/results paths remain readable, including score reports
and `--skip-existing`, so upgrading does not require regenerating past runs.

Compatibility identifiers are intentionally stable: browser `evodiagram_*`
project/DNA/draft keys, `smartdiagram_*` language/theme keys, the OAuth state cookie,
and the default SQLite filename/PostgreSQL database name. Existing `.env` files and user data are
not rewritten; new installations can set `DB_NAME=evodesign` explicitly. Old
public icon URLs remain aliases for the current artwork. Archived records and
third-party notices retain their original names. There is no second legacy Python
package or implicit `sys.modules` alias; external Python callers must update imports.

Run `python scripts/setup_local.py` once. It creates root `.env` and `frontend/.env` with unique secrets and matching local guest tokens, without overwriting an existing configuration. Fill `LLM_MODEL_NAME`, `LLM_ENDPOINT_URL` and `LLM_API_KEY` in the root `.env` with your provider's values. Use a vision-capable model and an OpenAI-compatible chat-completions base URL, normally ending in `/v1`.

The root `.env` is shared by the CLI and backend. Model roles for the research CLI are in `configs/settings.yaml`; providers and model aliases are in `configs/models.yaml`. `configured-model` resolves the three `LLM_*` values. No developer proxy or working API key is shipped. The backend also supports separate `REFINER_LLM_*` overrides; otherwise it reuses the generation configuration.

The default temperature is 1 in both `.env.example` (web) and `configs/models.yaml` (CLI). If your model needs a different value, change both. Optional reasoning settings should be enabled only if the selected model supports them. `backend/.env` is an optional service override; it is not required for the quick start.

## Runtime features

- Excalidraw is the default canvas. The optional TLDraw adapter is an advanced setting and carries its own upstream license; see [third-party notices](../../licenses/README.md).
- New Excalidraw diagrams in the web workspace default to icons enabled. A manual toggle is remembered for future creations; saved scenes and recovered drafts preserve their own choices. The research CLI retains its explicit `--use-icons` / `--no-icons` flags and experiment presets. The curated Excalidraw catalog (74 filled Material icons plus 59 `outline_*` Lucide icons) is bundled and needs no remote icon service. For the broader legacy TLDraw icon assets, run `python evodesign/scripts/setup_icons.py --version 0.14.15`.
- Small Excalidraw architecture diagrams without named groups, labeled relations or self-loops can use uniform title/sublabel cards and shared-trunk routing. The tool executes the layout agent's `tier_plan`, preserves supplied palette colors and intentional partial icon coverage, and keeps native text/connector bindings for editing. The icon toggle remains available. Unsupported graphs and junctions that would imply extra dependencies retain their complete free-form layout. Explicit DNA and locked elements bypass automatic visual treatments. `EVODESIGN_ARCH_DESIGN_SYSTEM=0` disables architecture cards. TLDraw scenes are not affected. These Python render treatments do not run in the static browser edition.
- Web refinement and design memory are enabled by default. Their settings are documented in `.env.example` and `backend/.env.example`.
- The initial embedding download is separate from steady-state generation time.
- Root `configs/` overrides packaged defaults. Both are shipped with matching public defaults.

## Local and hosted operation

`scripts/start_service.sh` binds the development servers to loopback. The API uses port 3010, renderer 3000 and frontend 5175. Stop them with `scripts/stop_service.sh`. Logs are local under `scripts/logs/`.

The local guest token is visible to the browser and is not a security boundary. Before offering a shared internet service, disable guest generation, configure authenticated access, HTTPS, trusted frontend origins, rate limits and your own quota policy. OAuth and billing integrations are optional; the local workflow does not require them. Do not put provider keys in any `VITE_*` variable, which becomes public browser code.

## Research evaluation

The default `eval` role shares the generation model for a basic smoke run. For reported experiments, use the independent `judge-vlm` alias with `JUDGE_MODEL_NAME`, `JUDGE_ENDPOINT_URL`, `JUDGE_API_KEY` and set `roles.eval: judge-vlm`. Record prompts, exact models, decoding parameters, dataset hashes, seeds where supported, and the release commit. Never treat convenience defaults as the manuscript's original experiment configuration.

## Static browser edition

The [browser edition](browser-edition.md) supports a shared GLM-5.3-Flash demo and direct calls to user-configured providers. The Vercel demo uses the small `api/model.mjs` function, without the Python backend. Set `DEMO_GLM_API_KEY`, `DEMO_REDIS_URL` and `DEMO_REDIS_TOKEN` as server-only Vercel secrets. Optional daily reserved-token, concurrency and per-visitor request limits are documented in the browser guide and `.env.example`. The counter namespace is independent of other applications. A static deployment without these values retains custom-model mode. Build with `npm --prefix frontend run build:browser`; ordinary builds keep the full backend mode. Never use `VITE_*` for a secret.
