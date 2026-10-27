# Backend API

[Contributor guides](README.md) · [Contributing](../CONTRIBUTING.md) · [Engineering quality](engineering-quality.md)

This guide covers the FastAPI API used by the EvoDesign workspace. The default
local API is `http://localhost:3010`; after starting the backend, inspect
`/docs` or `/openapi.json` for request/response schemas. The Next.js renderer on
`:3000` is a separate internal service.

The API currently has **25 method/path pairs in seven groups** under `/api/v1`.
The executable source of truth is the [route contract test](../tests/backend/test_api_surface.py)
and [router registration](../backend/app/api/v1/router.py). Update this guide
alongside those contracts whenever the surface changes.

## Authentication and ownership

- **Public** routes do not require a bearer token. OAuth redirects still validate
  their configured provider and callback state.
- **User** routes require `Authorization: Bearer <access-token>` from login or
  registration. Services must enforce ownership of projects, snapshots and rules.
- **User or guest** generation/edit routes also accept the deployment's configured
  guest bearer token. A guest is not an authenticated account and cannot use
  server project or DNA management routes.
- **Job owner** means a signed-in account reading its own learning job. Although
  this route uses the shared user/guest dependency, guests receive 404, as do
  requests for unavailable jobs in the caller's scope.

Authentication is implemented in [`backend/app/api/deps.py`](../backend/app/api/deps.py).
Do not accept a body-supplied user ID as proof of identity. Guest browser storage
and signed-in server storage are distinct; see the workspace's existing sync
behavior before changing either.

## Endpoint inventory

Paths below include the `/api/v1` prefix. Responses describe successful behavior;
validation and dependency failures can return other statuses. OAuth uses actual
HTTP redirects, even though the route metadata's default status is 200.

| Method | Path | Access | Success response |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | Public | 200 · `HealthResponse` |
| POST | `/api/v1/auth/login` | Public | 200 · `AuthResponse` |
| POST | `/api/v1/auth/register` | Public | 201 · `AuthResponse` |
| GET | `/api/v1/auth/me` | User | 200 · `AuthResponse` |
| GET | `/api/v1/auth/google` | Public | OAuth redirect (307) |
| GET | `/api/v1/auth/google/callback` | Public | OAuth redirect (307) |
| GET | `/api/v1/auth/github` | Public | OAuth redirect (307) |
| GET | `/api/v1/auth/github/callback` | Public | OAuth redirect (307) |
| POST | `/api/v1/auth/exchange` | Public | 200 · `AuthResponse` from a valid one-time code |
| GET | `/api/v1/users/subscription` | User | 200 · `SubscriptionStatus` |
| PUT | `/api/v1/users/profile` | User | 200 · `UserResponse` |
| POST | `/api/v1/diagram/generate` | User or guest | 201 · `DiagramGenerateResponse` |
| POST | `/api/v1/diagram/generate/stream` | User or guest | 200 · server-sent events |
| GET | `/api/v1/diagram/learning/{job_id}` | Job owner | 200 · learning status JSON |
| POST | `/api/v1/diagram/edit-local` | User or guest | 200 · `DiagramLocalEditResponse` |
| PATCH | `/api/v1/schema/sync` | User | 200 · `SchemaSyncResponse` |
| GET | `/api/v1/projects` | User | 200 · `ProjectListResponse` |
| POST | `/api/v1/projects` | User | 201 · `ProjectCreateResponse` |
| GET | `/api/v1/projects/{project_id}/snapshots` | User | 200 · `ProjectSnapshotListResponse` |
| GET | `/api/v1/projects/{project_id}` | User | 200 · `ProjectDetailResponse` |
| PUT | `/api/v1/projects/{project_id}` | User | 200 · `ProjectUpdateResponse` |
| DELETE | `/api/v1/projects/{project_id}` | User | 204 · no response body |
| POST | `/api/v1/dna/analyze` | User | 200 · `DnaAnalyzeResponse` |
| GET | `/api/v1/dna/rules` | User | 200 · `DnaRulesPayload` |
| PUT | `/api/v1/dna/rules` | User | 200 · `DnaRulesPayload` |

Group counts: authentication 8, diagrams 4, projects 6, DNA 3, users 2,
schema 1, health 1. Outside `/api/v1`, the backend exposes `GET /health`,
`GET /docs`, `GET /docs/oauth2-redirect`, `GET /openapi.json` and `GET /redoc`.

Login, registration, generation, editing and DNA analysis have endpoint rate
limits. Their current values are checked in the route contract test; callers
should handle HTTP 429 without an unbounded retry loop.

## Contracts that are easy to miss

**Streaming.** Use the generated
[`streamEvents.ts`](../frontend/src/contracts/streamEvents.ts) contract and
[`event_payloads.py`](../backend/app/services/workflow_runtime/event_payloads.py)
definitions. HTTP 200 means the stream opened, not that generation or refinement
succeeded. Preserve progress, cancellation, completion and error semantics.
After streaming starts, failures must use the defined events rather than an
ordinary JSON response body. Avoid exposing provider errors or credentials.

**Verification and refinement.** Generation uses the workflow's verifier and
refiner configuration. The streaming workflow verifies a refined candidate
before replacing the accepted result. A failed final quality check must retain
the base result and surface the refinement failure. See
[the quality-loop guide](../wiki/web-quality-loop.md) and the backend workflow
tests for fallback and learning behavior. Do not equate a usable diagram with
a passed quality review.

**Personal design memory.** `GET /dna/rules` selects a global or project scope
through `project_id`. `PUT /dna/rules` replaces the entire scope supplied in its
payload; it is not an additive single-rule patch. Clients must preserve existing
rules and account for concurrent edits. `POST /dna/analyze` accepts a multipart
image upload and returns candidates; it does not save them automatically. PNG,
JPEG and WebP uploads are accepted with an 8 MiB limit.

**Validation and persistence.** Keep unknown request fields and unsupported
canvas settings subject to the declared Pydantic contract. Test rejection before
model calls or writes. Preserve project ownership, snapshot behavior, stable
element IDs and native canvas bindings through save/reopen and local edits.

## Change an API safely

1. Put the route in its owning module under `backend/app/api/v1/endpoints/` and
   register it in `router.py`. Keep business logic in services and payload models
   in schemas. Use the shared authentication dependencies and error mappings.
2. Update route contracts for the method, path, response model, authentication,
   status and any rate limit. Cover invalid bodies, missing authorization,
   cross-account access and expected dependency failures as appropriate.
3. Update the frontend adapter and UI states affected by the contract. For stream
   changes, update the shared event definitions before regenerating the types.
4. Run the generator, review its output and run the relevant gates:

   ```sh
   ./.venv/bin/python scripts/generate_frontend_api_contract.py --write
   ./scripts/check_quality.sh architecture
   ./scripts/check_quality.sh backend
   ./scripts/check_quality.sh frontend
   ```

5. Update this inventory and configuration docs. Explain compatibility and any
   migration in the PR. If database behavior changes, review runtime bootstrap
   in `backend/app/db/bootstrap.py`; archived Supabase SQL is historical material.

For a quick inventory-only check without a running server or model call:

```sh
./.venv/bin/python scripts/generate_frontend_api_contract.py --check
./.venv/bin/python -m pytest tests/backend/test_api_surface.py -q
```

Use the full backend gate before merging backend behavior changes. For app tests,
follow existing fixtures that construct `create_app(settings=..., load_env=False)`
and override dependencies; tests should not depend on a contributor's real secrets.
