# Initial code release

EvoDesign now includes the editable web workspace, backend, agentic generation/refinement engine, renderer, optional icons, shared expertise and personal design memory in one public repository. Training and test data are deferred; the one-task example is authored for trying the software.

New personal-memory libraries start empty; demonstration rules and made-up usage history are no longer automatically assigned to new users. Existing saved preferences remain intact.

The README and website lead with the product workflow and local setup. The paper, authors, method, reported results and citation remain available as research context. Personal rules can be exported without account identifiers and additively imported through the included utility.

Public configuration requires the user's own model endpoint. Local setup generates unique secrets without overwriting existing files. Optional provider and renderer dependencies retain their upstream terms. The maintained implementation is not presented as an exact rerun of the manuscript experiments.

## Validation on 2026-10-27

- Installed into a fresh Python 3.11 environment and separate frontend/renderer dependency directories.
- Passed architecture, backend, engine, evaluation, baseline, user-memory, frontend and renderer quality gates; one baseline integration test requires an optional external tool and is skipped.
- Passed frontend lint, icon/editor checks, production build, and renderer type/build checks.
- Verified CLI help, production text measurement and layout endpoints, and both canvas renderer routes.
- Verified an actual local account's eight-rule import, export and second import: the second import adds no duplicates; exports contain no account/project/rule identifiers.
- Checked the product website in desktop and 390px mobile Chrome, canonical metadata and generated citations.

No new paid-model generation benchmark was run for this packaging release. Offline checks and the local service checks above do not establish model-specific visual quality or latency.

## Dependency maintenance

Next.js was updated to the 15.5.28 maintenance release. Lockfiles include compatibility updates and targeted overrides for vulnerable transitive packages. Production dependency audits reported no high or critical advisories on the validation date. Upstream dependency trees still contain moderate and low advisories; this is a local development release, not a claim of a vulnerability-free hosted service. Consult `npm audit` for current details before deployment.
