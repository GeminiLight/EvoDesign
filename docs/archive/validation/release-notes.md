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

## Quality and icon validation 2026-10-16

These reports preserve their original measurements and scope. They are historical records, not fresh verification of the current release.

### Quality-loop report
One authenticated web run with Kimi k3 generated an eight-node research-review flowchart with two feedback loops. It retrieved two seed strategies, applied seven edits in one refinement round, and improved the model's visual score from 7.5 to 8.5. Objective findings fell from one minor issue to zero. The system saved one private strategy; a subsequent related query retrieved it first in 1.616 seconds.

Measured pipeline time was 20m 56s: memory preparation/retrieval 40s, generation 4m 12s, initial render 42s, first review 4m 8s, refinement 6m 36s, final review 4m 17s, and learning 20s. Model calls remain the main latency source. This single-case validation does not establish general performance gains.

*The original screenshot is not included in this source distribution.*

Optional, portable node icons are documented in [node-icons.md](../../development/node-icons.md).

See the architecture, sequence and complex-flow matrix (original report not included in this distribution)
for icon on/off checks and a deliberate sequence fault-recovery test.

## Unified policy validation (2026-10-16)

The follow-up comparison (original report not included in this distribution)
uses the same perturbed scene for old/new refinement and a fresh authenticated
workspace run. Both refined results removed four major defects and scored 9.0;
the new result was delivered before its real-model learning job finished.

*The original screenshot is not included in this source distribution.*

### Node-icon report
- A web request with icons enabled used two design-memory entries and produced
  eight nodes with four icons. Engine time: 271.366 seconds; critic: 9.0/10;
  objective findings: zero. Automatic refinement correctly skipped this clean
  result.
- A separate, deliberately displaced copy exercised the actual model refiner
  and final critic: 100.11 seconds, one iteration, four applied edits, serious
  findings 4 → 0. Scores 5.5 → 6.5; this is a fault-recovery check, not evidence
  that the perturbed copy should replace the clean 9.0 result.
- The renderer now preserves original horizontal spacing when text/icon growth
  separates nodes, leaving room for connector labels. Re-rendering the same
  model layout passed all objective checks; a fresh critic scored it 8.7/10.
- Native browser checks covered drag, resize, recolor, icon replacement,
  duplication with new host ownership, removal and one-step undo, embedded
  PNG/SVG export and reopening the editable scene. Local artifacts are kept
  outside the repository and are not published with the source.
