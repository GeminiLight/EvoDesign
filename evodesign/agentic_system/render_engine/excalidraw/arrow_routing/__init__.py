"""Connector routing for the Excalidraw arrow adder.

Modules, from primitives to passes:

- ``geometry``: path predicates and scores shared by every router.
- ``grid_router``: orthogonal visibility-grid search (draw.io style).
- ``detours``: per-edge route repairs and alternative port/face candidates.
- ``ports``: face selection and port/corridor ranks for all edges at once.
- ``passes``: scene-wide optimization after every edge has a first route.
- ``labels``: edge-label filtering, measurement and placement.

``arrow_adder`` composes them into the render-stage arrow pass.
"""
