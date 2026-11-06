# Migration audit evidence

The reports describe the frozen local audit before the pull request was prepared. The two P1 findings and the other recorded differences remain open; passing regression suites do not supersede these findings.

Small result summaries, findings, module coverage, focused reproductions and the scripts are versioned. Large generated vectors and full captures (`coverage-inventory.json`, `probes.json`, `probe-results.json`, `mutants-python.json`, `boundary-input.json`, `boundary-python.json`, `boundary-ts.json`), probe logs and the browser bundle remain local and are ignored. Paths to those files in the historical reports name regeneration outputs, rather than committed fixtures. Run the commands in each domain report to regenerate them with Node >=22.12 and the Python environment; broad replays also require the locally generated engine fixtures.

Start with [the audit report](../ALGORITHM_VERIFICATION_REPORT.md) and [findings.json](findings.json). Focused P1 evidence is in [prototype-ts.json](VA02-generation/prototype-ts.json) and [budget-real-chromium.json](VA06-crosscheck/budget-real-chromium.json).
