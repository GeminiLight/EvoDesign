# First-load performance — 30 October 2026

## Changes

- Host the existing DM Sans and Manrope Latin variable fonts locally, with early preloads and `font-display: swap`. The page no longer requests a Google Fonts stylesheet or font origin.
- Generate the complete inline stylesheet from the two editable CSS sources. This removes the two additional stylesheet requests while preserving their cascade order. The gzip-compressed HTML is 30.5 KB; its styles are ready before the body is parsed.
- Show responsive WebP previews. The hero's 50,876-byte JPEG is replaced with 7,022-, 12,750- or 23,164-byte previews, selected by viewport and pixel density.
- Load the two research figures lazily as responsive, lossless WebP previews. Their full-size WebP files are pixel-identical to the original PNGs. Clicking either figure still opens its original PNG.
- Keep the initial hero text visible instead of hiding it for an entrance animation. Below-fold motion and reduced-motion support remain available.
- Add a CI budget check for external rendering dependencies, font bytes, script bytes, compressed document size and responsive previews.

## Controlled browser comparison

The baseline is commit `f00acfd`. Three paired runs used the existing Google Chrome profile at 1512 × 683, device pixel ratio 2. All six documents started visible and stayed visible during collection. Test resources used `Cache-Control: no-store`.

To reproduce a slow font service consistently, the baseline's font stylesheet was served through a local endpoint with a fixed three-second delay. It referenced the same font binaries as the optimized page. The optimized page did not request that endpoint. Other resources used the local HTTP server. A temporary PerformanceObserver collected paint, layout and navigation timings; the observer and test endpoint are absent from the deployed page.

| Metric | Baseline, median | Optimized, median |
| --- | ---: | ---: |
| First Contentful Paint | 4,484 ms | 936 ms |
| Largest Contentful Paint | 4,484 ms | 1,204 ms |
| DOM ready | 4,375 ms | 1,029 ms |

| Run | Baseline FCP | Optimized FCP | Baseline LCP | Optimized LCP |
| --- | ---: | ---: | ---: | ---: |
| 1 | 3,372 ms | 320 ms | 3,372 ms | 352 ms |
| 2 | 5,096 ms | 936 ms | 5,096 ms | 1,204 ms |
| 3 | 4,484 ms | 1,432 ms | 4,484 ms | 1,524 ms |

Layout shift was at most 0.0014 across these runs. The optimized page's initial resource list contained only local fonts, scripts, the logo and a 23,164-byte hero preview; no external rendering requests or standalone stylesheet requests appeared.

These measurements describe the controlled local experiment. Production timings depend on visitor connectivity, browser load and document delivery. No production field measurements or DevTools trace were collected. Separate command-line probes on the current network recorded the original Google Fonts stylesheet taking 0.84–1.73 seconds per request across three samples.

## Repeatable checks

```sh
node scripts/sync-research.mjs
python3 scripts/check_site_performance.py
SITE_URL=https://tianfu.wang/EvoDesign/ SITE_DIR=docs python3 scripts/verify-domain.py
node --check docs/motion.js
```

To regenerate image previews after replacing screenshots or paper figures, run `python3 scripts/optimize_site_images.py` with Pillow installed. Preview the page over HTTP so the local font resources use the same loading behavior as the deployed site.
