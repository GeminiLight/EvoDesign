# EvoDesign: search and research discovery

Updated: 15 October 2026. Scope: the project page, repository metadata, and the project sitemap entry in the existing domain-root robots file.

## Target

Canonical description, shared by the website, structured data, and README:

> EvoDesign is an agentic framework for editable diagram generation that coordinates structure, style, and layout agents and evolves reusable design expertise.

Primary intents: EvoDesign paper and citation; editable diagram generation; canvas-native diagram generation; multi-agent diagram generation; design expertise evolution; CanvasBench benchmark and evaluation; comparisons with pixel/code/agentic diagram methods; implementation availability.

The relevant surfaces are Google/Bing Search, Google Scholar, ChatGPT search, Perplexity, and other answer engines that retrieve scholarly sources. A citation in an AI answer is a separate metric from a citation in a research paper. Neither is guaranteed by these changes.

## Eligibility and fixes

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

## Source consistency to finish with the paper update

- The [arXiv record](https://arxiv.org/abs/2604.09568) has the EvoDesign title and the supplied 15-author order, but its abstract still uses the previous project name and links to the previous repository. Those fields should be updated by the paper owner in the next arXiv revision; the website cannot change them. Search results already reproduce this older abstract.
- The author’s [publications page](https://tianfuwang.tech/publications/) contains an EvoDesign entry, but its displayed author list differs from the supplied author image/arXiv record. Do not silently merge the lists. Align the publication entry with the finalized author list during the paper update.
- Keep all Paper links unversioned. Update the arXiv code link to `https://github.com/GeminiLight/EvoDesign` and add the project-page link to the paper’s public record when editing it.
- Once the renamed public PDF is supplied, host it beside this abstract page and add a same-directory `citation_pdf_url`. The anonymous draft has not been republished. Until then, arXiv remains the public full-text source; project-page Scholar inclusion is not asserted.

## Baseline and measurement

A discovery spot-check on 14 October found the author’s homepage/publication entry and third-party arXiv mirrors for EvoDesign/CanvasBench. It did not provide authoritative Google/Bing URL-inspection evidence for this project URL. No search ranking, indexed-page count, AI share-of-voice, field Core Web Vitals, or citation lift has been measured or claimed.

First manual follow-up: **22 October 2026**, after deployment. This is a suggested measurement date, not an automatic reminder or background task.

1. Submit `https://tianfuwang.tech/EvoDesign/sitemap.xml` in the existing Google Search Console and Bing Webmaster Tools properties; inspect the canonical URL. Their account state and access were not supplied in this task. Root robots discovery is configured independently.
2. Record query impressions/clicks, selected canonical, indexed state, and arXiv/title search coverage. Use the same intervals for subsequent comparisons; do not interpret one search result page as index coverage.
3. Run the adjacent [prompt panel](research/discovery-prompts.txt) on ChatGPT search and Perplexity: three paraphrases per intent, three runs each. Record whether the project is named, which exact URL is cited, and competing sources. Do not derive an AI visibility percentage from the spot-check above.
4. Recheck monthly and after a paper/code/data release. Compare changes that persist across paraphrases and runs. Academic citation counts should be tracked separately using the paper’s stable identifier in Scholar/Semantic Scholar; changes cannot be causally attributed to this website alone.

## Earned discovery, tied to real releases

| Intent | Source or placement | Concrete next step | Owner / timing |
| --- | --- | --- | --- |
| Find the paper | arXiv, author/lab publication pages | Unify title, abstract name, authors, code URL and project link | Paper owner, next revision |
| Reproduce editable diagram generation | GitHub research implementation | Publish tested setup, reproducible evaluation and links back to the paper | Maintainers, code release |
| Compare diagram methods | Surveys/collections that already discuss diagram agents, such as the author’s Agentic Artifact Creation survey | Add an accurately scoped entry when the taxonomy fits, disclosing authorship | Authors, next relevant update |
| Reuse CanvasBench | An actual public dataset record, e.g. Hugging Face Datasets, with a data card | Publish splits, license, evaluation protocol and citation only when release is ready | Dataset maintainers, dataset release |

No external messages, pitches, reviews, or dataset records were posted. These placements depend on genuine releases and editorial relevance.

## Primary guidance

- [Google: AI features and your website](https://developers.google.com/search/docs/appearance/ai-features): search eligibility and readable, useful content remain the foundation; there is no special AI schema that guarantees selection.
- [Google Scholar inclusion guidelines](https://scholar.google.com/intl/en/scholar/inclusion.html): bibliographic tags, the full author-written abstract, and properly connected full text help parsers identify a paper. Inclusion is still not guaranteed.
- [Google: build and submit a sitemap](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap): list canonical URLs and use accurate last-modified dates; a sitemap is a discovery signal.
