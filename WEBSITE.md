# EvoDesign website maintenance

## Structure

- `docs/index.html`: page content, author order and affiliations, resource links, metadata.
- `docs/styles.css`: responsive blue, violet, and cyan visual system.
- `docs/app.js`: local canvas illustration and manuscript result data.
- `docs/assets/`: favicon, sharing image, and two qualitative manuscript figure crops.
- `README.md`: repository landing page and release status.

The static website uses relative asset URLs so it works under the `/EvoDesign/` GitHub Pages path. Google Fonts enhances the typography when available; system font fallbacks keep the page usable without it. No analytics or application backend is included.

## Publishing

GitHub Pages serves `main` → `/docs`. Pushing changes to `docs/` triggers GitHub's Pages build and deployment. The `.nojekyll` file disables Jekyll processing.

Expected URL: https://geminilight.github.io/EvoDesign/

Local preview:

```sh
python3 -m http.server 8000 --directory docs
```

## Add the updated paper

1. Add the final, correctly named manuscript as `docs/assets/EvoDesign.pdf`, or use the final public paper URL.
2. Replace the forthcoming paper entry in `docs/index.html` with a working link and update the hero paper link.
3. Update the README release status and add the verified BibTeX. Do not invent a venue, identifier, or publication date.
4. Keep the project, paper, algorithm, metadata, and sharing image named **EvoDesign**.

The supplied anonymous manuscript is not distributed by this repository. Authors and affiliations were transcribed in row-major order from the author image provided by the project owner. No equal-contribution or corresponding-author symbols were inferred. The contact email is the one supplied for Hui Xiong.

## Add the implementation

Place the research code in the repository alongside `docs/`. Update the README with tested setup and reproduction instructions, choose the appropriate code/data licenses, and replace the “Code coming soon” labels once the release is usable. The website illustration is independent from the research implementation.

## Results and figures

`resultData` in `docs/app.js` transcribes Table 1 of the supplied manuscript. Values are ordered as content fidelity, concept logic, semantic relevance, visual aesthetics, styling consistency, flow coherence, space balance, cognitive ease, comprehension accuracy, self-contained explanation. Dimension summaries use arithmetic means of 3, 4, and 3 metrics respectively. The GPT-4o-Image row is fixed across backbone selections. The original manuscript's other two pixel baselines are omitted from this compact comparison; no universal best-in-class claim is made.

The refinement images are cropped diagram panels from Figure 9, showing the initial solution and final refinement. They are qualitative examples, not quantitative evidence. No manuscript instructions or hidden PDF text are incorporated into website content.

## Check before publishing changes

- Verify desktop and mobile layouts and horizontal table scrolling.
- Exercise model selection, pointer and keyboard node movement, palette switching, reset, and SVG export.
- Check resource URLs, image loading, and browser errors.
- Keep unreleased resources visibly marked as forthcoming.
