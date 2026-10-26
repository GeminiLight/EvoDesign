# Contributing

Use Python 3.11+ and Node.js 22.12+. Follow the root README to install the Python package and both Node projects, then install the `dev` Python extra. Run `./scripts/check_quality.sh all` before a pull request.

Keep changes focused and explain the user-visible behavior, validation, model/provider settings when relevant, and any reproducibility limitations. Preserve editable canvas semantics across generation, refinement, local editing, save/reopen and export. Test icons both on and off when touching the rendering pipeline. Use the existing account-scoped memory APIs and do not put private preferences into shared seed data.

The project and algorithm are EvoDesign. Existing `evo_diagram` imports, legacy schema keys and artifact identifiers remain supported. Do not globally replace them merely for branding.

Never commit `.env`, keys, databases, runtime vector stores, user outputs or private service endpoints. Put sanitized examples under `examples/`, and document third-party attribution and data provenance. Paper metadata is maintained in `research/paper.json`; regenerate the site citation blocks with `node scripts/sync-research.mjs`.
