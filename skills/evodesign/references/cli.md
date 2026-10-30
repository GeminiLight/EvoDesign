# CLI contract

All commands accept `--profile NAME` and `--json`. In JSON mode stdout is one protocol-v1 envelope: `{ok, protocol_version, data}` or `{ok:false, protocol_version:1, error}`. Diagnostics and pairing instructions go to stderr. Never print or inspect the credentials file.

```text
evodesign --version
evodesign connect --server http://localhost:3010 --profile paper
evodesign connection status --profile paper --json
evodesign project get --profile paper --json
evodesign project open --profile paper
evodesign document get --profile paper --json
evodesign document preview --profile paper --output saved.png --json
evodesign context get --profile paper --json
evodesign proposal create --profile paper --file ops.json --operation-id UNIQUE_ID --json
evodesign proposal get PROPOSAL_ID --profile paper --json
evodesign proposal wait PROPOSAL_ID --profile paper --timeout 90 --json
evodesign proposal preview PROPOSAL_ID --profile paper --output preview.png --json
evodesign proposal commit PROPOSAL_ID --profile paper --json
evodesign proposal reject PROPOSAL_ID --profile paper --json
evodesign history list --profile paper --limit 20 --json
evodesign history restore SNAPSHOT_ID --profile paper --base-version CURRENT_VERSION --operation-id UNIQUE_ID --json
evodesign disconnect --profile paper
```

Replace capitalized values with values returned by commands. `connect` opens the system browser and waits for the user to select a project and approve the connection; `--no-browser` prints the link instead. Use a backend origin, not a browser-only Studio URL. Remote backends require HTTPS; loopback HTTP is supported.

`document get` returns `data.project_id`, `version`, `schema`, `nodes`, `constraints`, `capabilities`, and `web_url`. The full scene is available for understanding, but editing uses semantic operations. `context get` returns the current constraint hash and, when shared, a selection with a context version and explicit expiry/status.

`proposal create` returns an ID and status, not a committed drawing. `proposal get`/`wait` runs or resumes bounded preview checking when needed. `ready` means structural validation and rendering succeeded; inspect `report.issues` and `warnings`. The server does not perform a visual model review for Agent proposals. Download the PNG before deciding whether it is good enough.

`commit` returns `committed_version` and `committed_snapshot_id`. It checks the proposal's original base version. If it times out, query this proposal: a committed result is authoritative even if the response was lost. Repeating commit for the same proposal is idempotent.

Exit codes: 2 invalid CLI input; 3 missing/expired credentials; 4 permission or missing project; 5 version/context/state conflict; 6 invalid/unsupported edit; 7 preview/check failure; 8 network/server/wait timeout. Preserve error fields such as `current_version` and `proposal_id`.

Use a new operation ID only for a new request. Reuse it for an uncertain create retry with exactly the same input. A 409 is not permission to drop the expected version. A wait timeout does not mean the candidate failed.

History distinguishes working snapshots from checkpoints using `is_checkpoint`. `history restore` prepares a candidate; wait, inspect and commit it through the same workflow. Whole-checkpoint restoration cannot override hard-locked elements.
