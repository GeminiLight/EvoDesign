# Website and README image sources

## Studio home

The two repository READMEs use matching-language screenshots:

- `README.md` (English): `../screenshots/studio-home-en.jpg`.
- `README.zh-CN.md` (Simplified Chinese): `../screenshots/studio-home-zh-CN.jpg`.

Both were refreshed on 2026-10-29 from the current frontend code (commit `05f418f04619652ae3c393950774db7fad4af4e1`, including the homepage centering fix) running locally in browser mode, using the user's existing Google Chrome. The app's Preferences control selects Light and the corresponding language; labels are rendered by the application, not painted into the image. Both captures use the same 1880 × 873 region, excluding the browser-extension control at the far right edge. They show an empty browser workspace with Your model / 你的模型 selected; no model request or private project data is used. The website hero also uses the English capture.

The earlier `../screenshots/studio-home.png` and dark `workspace-preview.png` remain available for existing links. Keep the two language versions on the same UI release and update their captures together.

## Studio identity

`studio-logo.svg` is copied directly from `frontend/public/evodiagram.svg`. The website navigation and favicon use this same product mark. When the product identity changes, refresh this copy from the application source.

## Website verification

`../screenshots/website-desktop.jpg` and `../screenshots/website-mobile.jpg` record the 2026-10-29 website update in the same Google Chrome: the 1188 × 763 viewport used in the design comments and a 390 × 844 responsive viewport. They are review evidence, not assets displayed inside the website. A 320px layout and the intermediate 1024px layout were also checked. The current review captures also include `website-features.jpg`, `website-research.jpg` and `website-citation.jpg` for the three feature illustrations, NeurIPS manuscript figures and compact citation block.

## Method overview

`method-overview.png` is a 2448 × 1192 PNG rendered directly from the authors' current one-page vector figure on 2026-10-29. No labels or diagram content were changed.

- Author source in the local manuscript: `evo-diagram-paper/Eval Diagram Paper/evo_diagram/resources/evo-diagram.pdf` (not part of the public code release).
- Caption and placement: Figure 2 of the maintained manuscript; four panels cover agentic canvas generation, verification and refinement, experience exploration, and design knowledge promotion.
- Source render: PyMuPDF, scale 4, opaque RGB output.
- The current arXiv v2 HTML has an earlier three-panel figure. The README therefore labels this image as coming from the maintained manuscript source, rather than claiming it is an exact reproduction of the arXiv v2 figure.

The paper figure remains research material; the repository's MIT software license does not relicense it. See the repository's third-party notices and paper links.

When the interface or paper figure changes, update the README image and this source record together. Prefer actual interface captures and direct figure exports over generated mockups.

## CanvasBench overview

`canvasbench-overview.png` is a 2448 × 608 opaque PNG rendered directly at scale 4 from `evo-diagram-paper/Eval Diagram Paper/evo_diagram/resources/diagram-benchmark.pdf` on 2026-10-29. The current NeurIPS-template manuscript includes this exact file in `sections/benchmark.tex`; `sections/formulation.tex` includes the `evo-diagram.pdf` framework source used for `method-overview.png`. The website uses these maintained manuscript sources, rather than the older public arXiv v2 artwork. No figure content, labels or numerical values were changed. The source manuscript is not added to the public repository.

The same research-material licensing note as the method overview applies to this figure.
