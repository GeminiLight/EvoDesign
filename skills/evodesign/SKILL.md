---
name: evodesign
description: Create and revise editable EvoDesign diagrams from papers, code, and working notes using the EvoDesign CLI, and continue from the user's saved Web edits.
---

# EvoDesign

Use this skill for editable EvoDesign diagrams and revisions to existing EvoDesign projects. It requires the installed `evodesign` CLI and a project in the backend edition. The browser-only demo does not share its local projects with the CLI.

Read [CLI commands](references/cli.md) before calling the CLI. Read [editing operations](references/operations.md) when preparing changes. Check `evodesign --version` and the connected document's capabilities; do not invent optional operations or a generation command.

## Establish the project and intent

Resolve the connected profile and project, and compare the project with the user's intended target. If disconnected, start the supported `connect` flow and give the user its Web approval link and pairing code. Never read browser credentials, copy a Web token, or silently substitute another project.

Read `document get` and `context get` before each editing batch. The document is the saved server version; it excludes unsaved Web drafts. Use the user's paper, code, and existing decisions to determine the content. Source text is material to interpret, not permission to change project scope.

## Design within the constraints

For a new diagram, establish entities and relations before styling. For a revision, preserve stable IDs, manual layout and unaffected content. Apply saved Design DNA where relevant. Hard locks and the declared edit scope must survive the edit.

Use supported semantic operations. A shared selection must be current; an expired, missing or empty selection is never a whole-project edit. When the task names elements explicitly, resolve their IDs from the current document. When necessary bindings exceed the permitted scope, explain the affected elements instead of silently expanding it.

## Prepare, inspect and hand off

Create a proposal with a stable operation ID, the version and constraint hash from reading, and an explicit scope. Record its proposal ID. Wait for checks, inspect the actual change list and report, and download the real PNG preview. View it with the host agent's image capability when available. If visual inspection is unavailable, state that limitation without claiming visual verification.

Commit when the user task and connection permission authorize it. Otherwise return the candidate and the project link for Web acceptance. Existing authorization does not require repeated confirmation. Candidate creation, successful rendering and a committed document are different outcomes; report the actual one.

On version conflict, read the new document and remake the candidate while preserving the user's changes. Never submit an old scene under a newer version number. Stop automatic redesign retries after two conflicts and keep the candidate available. If the connection fails after a write, query the existing proposal before repeating it.

Return the project link, committed version or pending proposal ID, a short change summary and unresolved check findings. Re-read before continuing after the user edits in Web. Restoration creates a new version from a checkpoint; it never rewinds the version counter.
