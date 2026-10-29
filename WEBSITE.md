# EvoDesign website maintenance

## Structure

- `docs/index.html`: page content, author order and affiliations, resource links, metadata.
- `docs/styles.css`: base responsive layout.
- `docs/polish.css`: refined blue, violet, and cyan presentation, responsive controls, and motion styles.
- `docs/app.js`: local canvas illustration and manuscript result data.
- `docs/motion.js`: guided flow, progressive entrance effects, counters, figure dialog, navigation state, and motion preferences.
- `docs/assets/`: product logo, sharing image, manuscript method figure, and qualitative figure crops.
- `docs/screenshots/`: real Studio captures; the English website previews are generated from the English README capture.
- `docs/assets/previews/`: responsive website WebP images; originals remain available for the README and full-resolution views.
- `docs/performance.md`: first-load changes, controlled measurement results and checks.
- `README.md`: repository landing page and release status.

The static website uses relative asset URLs so it works under the `/EvoDesign/` GitHub Pages path. The two editable CSS sources are combined into a generated inline style block by `scripts/sync-research.mjs`, so first paint does not wait for additional stylesheet requests. Script URLs include a content-hash `v` query. DM Sans and Manrope are served locally from `docs/assets/fonts/`; the page preloads both variable fonts and uses `font-display: swap`. No analytics or application backend is included.

## Publishing

GitHub Pages serves `main` → `/docs`. Pushing changes to `docs/` triggers GitHub's Pages build and deployment. The `.nojekyll` file disables Jekyll processing.

Public URL: https://tianfu.wang/EvoDesign/

The primary product destination is https://evodesign.vercel.app/. The navigation, hero, clickable Studio preview, browser getting-started section, questions and resources all link directly there. Keep the online entry visible on small screens. The shared demo needs no installation, API key or EvoDesign account; custom models remain optional. The local setup link is a separate route for the full research pipeline, visual verification and expertise evolution. Keep this distinction when editing feature copy.

The hero uses responsive WebP versions of a real English Studio screenshot. Update both language captures together after interface changes and record their source in `docs/assets/README.md`. No additional application requests or model calls are made by the project website.

GitHub Pages inherits the account’s existing `tianfu.wang` domain. The default `geminilight.github.io/EvoDesign/` address redirects there. No repository-level custom domain or DNS change is required.

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

The framework and CanvasBench construction figures are direct exports from the current manuscript using the NeurIPS template. Both are visible above the expandable research details and open a wide native dialog, with an original-resolution link and keyboard focus restoration. Source details are recorded in `docs/assets/README.md`.

The refinement images are cropped diagram panels from Figure 9, showing the initial solution and final refinement. They are qualitative examples, not quantitative evidence. No manuscript instructions or hidden PDF text are incorporated into website content.

## Motion and interaction

The canvas walkthrough highlights each stage and traces its connections. It plays once on desktop when the canvas enters view; on narrow screens, visitors start it themselves. Selecting a step scrolls the canvas horizontally to the relevant node. Dragging a node interrupts playback.

The navigation links directly to Paper. Decorative entrance effects finish after four seconds. The page respects the system’s reduced-motion preference, provides manual step exploration, stops transient animation when the tab is hidden, and leaves content visible when JavaScript is unavailable. Native figure dialogs support Escape and return focus to their trigger.

## Check before publishing changes

- Verify desktop and mobile layouts and horizontal table scrolling.
- Exercise flow playback/pause, step selection, model selection, pointer and keyboard node movement, palette switching, reset, and SVG export.
- Check reduced motion, figure-dialog focus and Escape, and narrow-screen canvas navigation.
- Check resource URLs, image loading, and browser errors.
- Keep unreleased resources visibly marked as forthcoming.

## Scholarly metadata and citation

`research/paper.json` holds the verified paper title, author order, affiliations, arXiv identifier, DOI, year, description, and website abstract. The publication year is separate from the website modification date. No conference proceedings details or exact publication day are inferred.

After editing metadata or the metric arrays in `docs/app.js`, run:

```sh
node scripts/sync-research.mjs
```

This updates the generated inline stylesheet, scholarly meta tags and JSON-LD, the default results in raw HTML, BibTeX/RIS downloads, GitHub `CITATION.cff`, README citation, the all-metrics CSV, sitemap, and script content hashes. The generated files are committed; deployment still has no build step. After changing author names, also update the visible author block and README author line. Change `pageModified` and the footer date only when website content actually changes.

The citation block always shows compact BibTeX in ten lines, with the complete author list on one horizontally scrollable line and a small copy button inside the block. Clipboard copying falls back to the browser copy command or selected text when necessary. BibTeX/RIS files remain available at their existing URLs. The default GPT-5.5 results remain available without JavaScript; other backbone settings are also available in the CSV. The CSV transcribes the supplied manuscript and is not the CanvasBench dataset.

`docs/sitemap.xml` lists the canonical project URL. Only the domain-root `https://tianfu.wang/robots.txt` controls crawlers; a project-level `docs/robots.txt` would not. The domain-root file lives in the separate `GeminiLight/geminilight.github.io` repository.

The author will provide the renamed public PDF later. Do not add `citation_pdf_url` pointing to the anonymous draft or an external PDF: Google Scholar expects a same-directory full-text file for that tag. For now, full-text links lead to the unversioned arXiv record. See [SEO and research-discovery notes](SEO_GEO.md) for indexing checks and the source-consistency follow-up.

## Additional interaction checks

- The mobile Menu supports Escape, focus return, and direct section links.
- BibTeX copy confirms success, or selects the text when clipboard access is unavailable.
- Questions and citation disclosure work without JavaScript.
- Source HTML contains six default result rows and all fifteen citation authors.
- Downloaded BibTeX, RIS, and CSV agree with visible metadata and reported numbers.

## First-load resource budgets

Run `python3 scripts/check_site_performance.py` after website changes. The site-domain workflow runs the same guard in CI. It rejects external rendering dependencies, standalone stylesheet requests, missing responsive image variants and over-budget resources. See `docs/performance.md` for the measured baseline and budget context.

Keep the original screenshots and paper PNGs intact. Regenerate WebP previews with `python3 scripts/optimize_site_images.py` (Pillow required), then run the metadata/style sync. Figure-dialog originals must use the figure link destination, not the smaller preview source.
