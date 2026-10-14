# EvoDesign website maintenance

## Structure

- `docs/index.html`: page content, author order and affiliations, resource links, metadata.
- `docs/styles.css`: base responsive layout.
- `docs/polish.css`: refined blue, violet, and cyan presentation, responsive controls, and motion styles.
- `docs/app.js`: local canvas illustration and manuscript result data.
- `docs/motion.js`: guided flow, progressive entrance effects, counters, figure dialog, navigation state, and motion preferences.
- `docs/assets/`: favicon, sharing image, and two qualitative manuscript figure crops.
- `README.md`: repository landing page and release status.

The static website uses relative asset URLs so it works under the `/EvoDesign/` GitHub Pages path. Stylesheet and script URLs include a content-hash `v` query to avoid stale browser caches; refresh that value when those files change. Google Fonts enhances the typography when available; system font fallbacks keep the page usable without it. No analytics or application backend is included.

## Publishing

GitHub Pages serves `main` → `/docs`. Pushing changes to `docs/` triggers GitHub's Pages build and deployment. The `.nojekyll` file disables Jekyll processing.

Public URL: https://tianfuwang.tech/EvoDesign/

GitHub Pages inherits the account’s existing `tianfuwang.tech` domain. The default `geminilight.github.io/EvoDesign/` address redirects there. No repository-level custom domain or DNS change is required.

Local preview:

```sh
python3 -m http.server 8000 --directory docs
```

## Paper updates

The hero Paper link, research-paper resource, and README point to https://arxiv.org/abs/2604.09568. Keep this unversioned URL so future arXiv revisions appear at the same address.

If the public paper URL changes, update both website links and the README together. Add verified BibTeX when needed; do not invent a venue, identifier, or publication date. Keep the project, paper, algorithm, metadata, and sharing image named **EvoDesign**.

The supplied anonymous manuscript is not distributed by this repository. Authors and affiliations were transcribed in row-major order from the author image provided by the project owner. No equal-contribution or corresponding-author symbols were inferred. The contact email is the one supplied for Hui Xiong.

## Add the implementation

Place the research code in the repository alongside `docs/`. Update the README with tested setup and reproduction instructions, choose the appropriate code/data licenses, and replace the “Code coming soon” labels once the release is usable. The website illustration is independent from the research implementation.

## Results and figures

`resultData` in `docs/app.js` transcribes Table 1 of the supplied manuscript. Values are ordered as content fidelity, concept logic, semantic relevance, visual aesthetics, styling consistency, flow coherence, space balance, cognitive ease, comprehension accuracy, self-contained explanation. Dimension summaries use arithmetic means of 3, 4, and 3 metrics respectively. The GPT-4o-Image row is fixed across backbone selections. The original manuscript's other two pixel baselines are omitted from this compact comparison; no universal best-in-class claim is made.

The refinement images are cropped diagram panels from Figure 9, showing the initial solution and final refinement. They are qualitative examples, not quantitative evidence. No manuscript instructions or hidden PDF text are incorporated into website content.

## Motion and interaction

The canvas walkthrough highlights each stage and traces its connections. It plays once on desktop when the canvas enters view; on narrow screens, visitors start it themselves. Selecting a step scrolls the canvas horizontally to the relevant node. Dragging a node interrupts playback.

The Motion control pauses presentation effects and remembers the choice locally. The page also respects the system’s reduced-motion preference, provides manual step exploration, stops transient animation when the tab is hidden, and leaves content visible when JavaScript is unavailable. Native figure dialogs support Escape and return focus to their trigger.

## Check before publishing changes

- Verify desktop and mobile layouts and horizontal table scrolling.
- Exercise flow playback/pause, step selection, model selection, pointer and keyboard node movement, palette switching, reset, and SVG export.
- Check reduced motion, persisted motion preferences, figure-dialog focus and Escape, and narrow-screen canvas navigation.
- Check resource URLs, image loading, and browser errors.
- Keep unreleased resources visibly marked as forthcoming.

## Scholarly metadata and citation

`research/paper.json` holds the verified paper title, author order, affiliations, arXiv identifier, DOI, year, description, and website abstract. The publication year is separate from the website modification date. No conference proceedings details or exact publication day are inferred.

After editing metadata or the metric arrays in `docs/app.js`, run:

```sh
node scripts/sync-research.mjs
```

This updates the scholarly meta tags and JSON-LD, the default results in raw HTML, BibTeX/RIS downloads, GitHub `CITATION.cff`, README citation, the all-metrics CSV, sitemap, and CSS/JS content hashes. The generated files are committed; deployment still has no build step. After changing author names, also update the visible author block and README author line. Change `pageModified` and the footer date only when website content actually changes.

The citation block supports clipboard copy, a readable fallback, and downloads. The default GPT-5.5 results remain available without JavaScript; other backbone settings are also available in the CSV. The CSV transcribes the supplied manuscript and is not the CanvasBench dataset.

`docs/sitemap.xml` lists the canonical project URL. Only the domain-root `https://tianfuwang.tech/robots.txt` controls crawlers; a project-level `docs/robots.txt` would not. The domain-root file lives in the separate `GeminiLight/geminilight.github.io` repository.

The author will provide the renamed public PDF later. Do not add `citation_pdf_url` pointing to the anonymous draft or an external PDF: Google Scholar expects a same-directory full-text file for that tag. For now, full-text links lead to the unversioned arXiv record. See [SEO and research-discovery notes](SEO_GEO.md) for indexing checks and the source-consistency follow-up.

## Additional interaction checks

- The mobile Contents menu supports Escape, focus return, and direct section links.
- BibTeX copy confirms success, or selects the text when clipboard access is unavailable.
- Questions and citation disclosure work without JavaScript.
- Source HTML contains six default result rows and all fifteen citation authors.
- Downloaded BibTeX, RIS, and CSV agree with visible metadata and reported numbers.
