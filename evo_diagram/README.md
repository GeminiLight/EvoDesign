# EvoDesign engine

The core implementation behind the EvoDesign web workspace and research pipeline. Start with the [repository quick start](../README.md#run-locally), [configuration](../docs/configuration.md) and [reproducibility guide](../docs/reproducibility.md).

- `agentic_system/`: structure, styling, layout, verification and refinement workflows; includes the renderer tool service.
- `canvas_environment/`: canvas conversion, rendering and diagnostics.
- `design_memory/`: reusable design expertise, retrieval and evolution.
- `user_memory/`: preference extraction from edits and persistent memory.
- `config/`: role/model routing and runtime settings.
- `tests/`: offline regression tests and optional embedding integration.

The import path `evo_diagram` and existing artifact identifiers remain stable for compatibility. The project and algorithm are named **EvoDesign**. A source checkout is the supported installation for the full toolchain.

```sh
python -m evo_diagram.agentic_system.main --example 1 --dataset-path examples/diagrams/quickstart.json
```

Run the renderer first. Supply your own model configuration in the root `.env`. Icons are opt-in with `--use-icons`. Run `--help` to inspect the current CLI rather than relying on older experiment notes. Personal-memory integration and portability are described in [the memory guide](../docs/design-memory.md).
