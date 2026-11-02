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
- `docs/development/performance.md`: first-load changes, controlled measurement results and checks.
- `README.md`: repository landing page and release status.

The static website uses relative asset URLs so it works under the `/EvoDesign/` GitHub Pages path. The two editable CSS sources are combined into a generated inline style block by `scripts/sync-research.mjs`, so first paint does not wait for additional stylesheet requests. Script URLs include a content-hash `v` query. DM Sans (body, variable weights 400–700) and Syne (display, weight 600) are served locally as Latin WOFF2 subsets from `docs/assets/fonts/`. The page preloads these two files and uses `font-display: swap`; their combined payload is 35,560 bytes. The outlined SVG wordmark requires no font request. Font sources, modifications and licenses are recorded in the fonts directory. No analytics or application backend is included.

## Publishing

GitHub Pages serves `main` → `/docs`. Pushing changes to `docs/` triggers GitHub's Pages build and deployment. The `.nojekyll` file disables Jekyll processing.

Public URL: https://tianfu.wang/EvoDesign/

The primary product destination is https://evodesign.aurax.live/. The navigation, hero, clickable Studio preview, browser getting-started section, questions and resources all link directly there. Keep the online entry visible on small screens. The shared demo needs no installation, API key or EvoDesign account; custom models remain optional. The local setup link is a separate route for the full research pipeline, visual verification and expertise evolution. Keep this distinction when editing feature copy.

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

The author will provide the renamed public PDF later. Do not add `citation_pdf_url` pointing to the anonymous draft or an external PDF: Google Scholar expects a same-directory full-text file for that tag. For now, full-text links lead to the unversioned arXiv record. See [SEO and research-discovery notes](website.md) for indexing checks and the source-consistency follow-up.

## Additional interaction checks

- The mobile Menu supports Escape, focus return, and direct section links.
- BibTeX copy confirms success, or selects the text when clipboard access is unavailable.
- Questions and citation disclosure work without JavaScript.
- Source HTML contains six default result rows and all fifteen citation authors.
- Downloaded BibTeX, RIS, and CSV agree with visible metadata and reported numbers.

## First-load resource budgets

Run `python3 scripts/check_site_performance.py` after website changes. The site-domain workflow runs the same guard in CI. It rejects external rendering dependencies, standalone stylesheet requests, missing responsive image variants and over-budget resources. See `docs/development/performance.md` for the measured baseline and budget context.

Keep the original screenshots and paper PNGs intact. Regenerate WebP previews with `python3 scripts/optimize_site_images.py` (Pillow required), then run the metadata/style sync. Figure-dialog originals must use the figure link destination, not the smaller preview source.

<details>
<summary>Search discovery audit — 2026-10-15 (historical)</summary>

This audit records its original date. It is reference material, not the current task list; use the maintenance and publishing instructions above for current work.

### EvoDesign: search and research discovery

Updated: 15 October 2026. Scope: the project page, repository metadata, and the project sitemap entry in the existing domain-root robots file.

#### Target

Canonical description, shared by the website, structured data, and README:

> EvoDesign is an agentic framework for editable diagram generation that coordinates structure, style, and layout agents and evolves reusable design expertise.

Primary intents: EvoDesign paper and citation; editable diagram generation; canvas-native diagram generation; multi-agent diagram generation; design expertise evolution; CanvasBench benchmark and evaluation; comparisons with pixel/code/agentic diagram methods; implementation availability.

The relevant surfaces are Google/Bing Search, Google Scholar, ChatGPT search, Perplexity, and other answer engines that retrieve scholarly sources. A citation in an AI answer is a separate metric from a citation in a research paper. Neither is guaranteed by these changes.

#### Eligibility and fixes

| Area | Before | Implemented |
| --- | --- | --- |
| Crawling | Canonical page returned HTTP 200; root robots allowed all agents | Existing access policy preserved; project sitemap added |
| Paper identity | General social tags, no scholarly metadata | Full paper title, 15 authors, year, DOI, arXiv ID; connected WebPage and ScholarlyArticle JSON-LD |
| Research text | Overview, method and benchmark present | Full manuscript abstract with updated project name; clear research questions and qualifications |
| Results | Table body empty until JavaScript ran | Six default rows in delivered HTML; all four backbone settings downloadable as CSV |
| Citation | Paper link only | Copyable BibTeX, BibTeX/RIS downloads, GitHub CITATION.cff and README citation |
| Sitemap | No project sitemap | One canonical project URL, with a real content-modification date |
| Sharing | Partial Open Graph metadata | Matching title/description, image alternative text and dimensions, Twitter card metadata |
| Research UX | Partial mobile navigation | All-section mobile directory, persistent Cite entry, native disclosures, copy feedback/fallback |

The effective root robots file was fetched on 14 October 2026 UTC. Googlebot, Bingbot, OAI-SearchBot, PerplexityBot, Claude-SearchBot, Applebot, and on-demand fetchers are allowed by the existing wildcard rule. A robots permission or a request with a bot user agent does not prove that a verified crawler will pass every CDN check. Search index coverage still needs first-party webmaster evidence.

The local generic SEO audit misidentified the inline SVG title as the page title and flagged empty decorative image alt text. These are audit-parser false positives: head/title and intentionally decorative images were inspected separately. No keywords meta tag, FAQ rich-result claim, or AI-specific ranking claim is used. The existing full-resolution diagram dialog sets its image alternative text when opened.

#### Source consistency to finish with the paper update

- The [arXiv record](https://arxiv.org/abs/2604.09568) has the EvoDesign title and the supplied 15-author order, but its abstract still uses the previous project name and links to the previous repository. Those fields should be updated by the paper owner in the next arXiv revision; the website cannot change them. Search results already reproduce this older abstract.
- The author’s [publications page](https://tianfu.wang/publications/) contains an EvoDesign entry, but its displayed author list differs from the supplied author image/arXiv record. Do not silently merge the lists. Align the publication entry with the finalized author list during the paper update.
- Keep all Paper links unversioned. Update the arXiv code link to `https://github.com/GeminiLight/EvoDesign` and add the project-page link to the paper’s public record when editing it.
- Once the renamed public PDF is supplied, host it beside this abstract page and add a same-directory `citation_pdf_url`. The anonymous draft has not been republished. Until then, arXiv remains the public full-text source; project-page Scholar inclusion is not asserted.

#### Baseline and measurement

A discovery spot-check on 14 October found the author’s homepage/publication entry and third-party arXiv mirrors for EvoDesign/CanvasBench. It did not provide authoritative Google/Bing URL-inspection evidence for this project URL. No search ranking, indexed-page count, AI share-of-voice, field Core Web Vitals, or citation lift has been measured or claimed.

First manual follow-up: **22 October 2026**, after deployment. This is a suggested measurement date, not an automatic reminder or background task.

1. Submit `https://tianfu.wang/EvoDesign/sitemap.xml` in the existing Google Search Console and Bing Webmaster Tools properties; inspect the canonical URL. Their account state and access were not supplied in this task. Root robots discovery is configured independently.
2. Record query impressions/clicks, selected canonical, indexed state, and arXiv/title search coverage. Use the same intervals for subsequent comparisons; do not interpret one search result page as index coverage.
3. Run the adjacent [prompt panel](../../research/discovery-prompts.txt) on ChatGPT search and Perplexity: three paraphrases per intent, three runs each. Record whether the project is named, which exact URL is cited, and competing sources. Do not derive an AI visibility percentage from the spot-check above.
4. Recheck monthly and after a paper/code/data release. Compare changes that persist across paraphrases and runs. Academic citation counts should be tracked separately using the paper’s stable identifier in Scholar/Semantic Scholar; changes cannot be causally attributed to this website alone.

#### Earned discovery, tied to real releases

| Intent | Source or placement | Concrete next step | Owner / timing |
| --- | --- | --- | --- |
| Find the paper | arXiv, author/lab publication pages | Unify title, abstract name, authors, code URL and project link | Paper owner, next revision |
| Reproduce editable diagram generation | GitHub research implementation | Publish tested setup, reproducible evaluation and links back to the paper | Maintainers, code release |
| Compare diagram methods | Surveys/collections that already discuss diagram agents, such as the author’s Agentic Artifact Creation survey | Add an accurately scoped entry when the taxonomy fits, disclosing authorship | Authors, next relevant update |
| Reuse CanvasBench | An actual public dataset record, e.g. Hugging Face Datasets, with a data card | Publish splits, license, evaluation protocol and citation only when release is ready | Dataset maintainers, dataset release |

No external messages, pitches, reviews, or dataset records were posted. These placements depend on genuine releases and editorial relevance.

#### Primary guidance

- [Google: AI features and your website](https://developers.google.com/search/docs/appearance/ai-features): search eligibility and readable, useful content remain the foundation; there is no special AI schema that guarantees selection.
- [Google Scholar inclusion guidelines](https://scholar.google.com/intl/en/scholar/inclusion.html): bibliographic tags, the full author-written abstract, and properly connected full text help parsers identify a paper. Inclusion is still not guaranteed.
- [Google: build and submit a sitemap](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap): list canonical URLs and use accurate last-modified dates; a sitemap is a discovery signal.

</details>
