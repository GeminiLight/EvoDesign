# Reproducing and extending EvoDesign

This release contains the maintained implementation: structure, style and layout agents; quality evaluation and refinement; optional icons; edit operations; shared expertise; and personal memory. It includes baseline adapters, evaluation modules, dataset construction utilities and offline regression tests. Training and test data are not included in this code release.

The manuscript's result tables on the project website remain **manuscript-reported results**. This code snapshot includes subsequent engineering changes. A full regeneration of all manuscript scores has not been performed for this release, and the default endpoint/model is deliberately user-configured.

## Record a run

1. Record the commit and the hashes of your own input files.
2. Configure generation models and an independent evaluation judge as described in [configuration](configuration.md).
3. Keep the same backbone and decoding parameters across methods when comparing them. Some image/baseline providers require their own credentials and dependencies.
4. Start the rendering service; run one sample before a batch.
5. Preserve generated artifacts, evaluation run signatures, failures, retry counts, token use and timing. Report embedding downloads and service startup separately from warmed generation latency.

```sh
python -m evo_diagram.agentic_system.main --example 1 --dataset-path examples/diagrams/quickstart.json
python -m evo_diagram.agentic_system.main --example 1 --dataset-path examples/diagrams/quickstart.json --use-icons
```

See `--help` for refinement, ablations (`--variant`), user memory and edit-learning inputs. `scripts/run_evodiagram.sh`, `scripts/run_baselines.sh`, `scripts/run_evaluation.sh` and `scripts/run_pipeline.sh` provide batch entry points; inspect their usage and set the dataset, sample range, model aliases and method list explicitly before starting a paid batch.

## Dataset availability

Training and test data are deferred to a separate release. Supply your own dataset JSON when running batch evaluation. `examples/diagrams/quickstart.json` is an authored, one-task usage example, not a CanvasBench subset or benchmark. Existing experiment scripts retain the conventional `dataset/test/data.json` path; pass an explicit dataset path or place your own data there. Do not interpret the quick-start example as a research evaluation.

## Validation

`./scripts/check_quality.sh all` runs architecture, API/backend, engine, evaluation, baseline, user-memory, frontend and renderer checks. Most tests are offline and do not spend model credits. The real Chroma embedding test is explicitly excluded from the engine gate because it downloads a model; run it separately when validating the embedding environment.

A passing offline suite verifies software contracts, not visual quality across all models. Evaluate layout, label collisions, refinement, edits and exports on the actual provider and model used for a study.
