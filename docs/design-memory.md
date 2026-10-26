# Personal design memory

EvoDesign includes both reusable design expertise and personal preferences. They are separate stores:

| Component | Contents | Location / entry point |
| --- | --- | --- |
| Shared expertise | 126 bundled seed strategies; retrieved and optionally updated during refinement | `evo_diagram/design_memory/`, `backend/app/services/design_memory_service.py` |
| Personal DNA | Structure, style and layout rules; enable/disable, pin, edit, global and project scope | Web **Your DNA**, `backend/app/services/dna_rule_service.py` |
| Learning from edits | Before/after canvas comparison, preference extraction and vector storage | `evo_diagram/user_memory/`, its `data_example/`, CLI `--learn-from-edit` / `--enable-user-memory` |

User constraints and active personal rules participate in the web generation quality loop. The general research edit-learning pipeline is also included; do not assume every canvas keystroke automatically trains persistent memory. The web DNA page supports explicitly reviewing and managing the rules.

## A portable example

[`blue-violet.json`](../examples/design-memory/blue-violet.json) contains eight curated rules adapted from the application’s demonstration profile: naming, hierarchy, connections, notes, geometry, stroke weight and blue-violet color. Two are deliberately disabled. These are examples, not universal defaults, and are **not automatically installed into new accounts**. The public example contains no account IDs, email, projects, images, tokens, or vector databases.

Validate without a server or API key:

```sh
python scripts/design_memory.py validate examples/design-memory/blue-violet.json
```

For a signed-in local account, supply its access token through the environment (never commit it), then:

```sh
python scripts/design_memory.py export my-design-memory.json
python scripts/design_memory.py import examples/design-memory/blue-violet.json
```

These commands read `EVO_API_TOKEN`; obtain it from your own local login response. `--api https://your-instance.example` selects another installation; `--project-id ID` selects a project you own. Remote connections require HTTPS. Import adds missing rules and preserves existing ones. Avoid concurrent edits while importing because the current API saves an entire scope. Export refuses to overwrite an existing backup. Back up first and review imported rule text before enabling it.

The portable format intentionally excludes owner IDs, project IDs, rule IDs, usage counters and timestamps. Import generates fresh rule IDs in the destination account. It does not migrate accounts or credentials.

## Guest versus signed-in storage

Guest rules and projects live in browser storage. Signing in uses account-scoped backend storage and the app's guest import flow. The API utility above works with signed-in accounts, not with a guest bearer token. Exporting a server library does not export unsynced guest browser data.

Runtime SQLite files, Chroma/vector stores and generated images are ignored by Git. Back them up privately. The seeded shared expertise and the portable sample are the only prefilled memory data in the release. The first semantic-memory run may download the configured embedding model; this one-time setup should be reported separately from model-generation latency.
