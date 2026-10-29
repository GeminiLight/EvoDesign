# Local website fonts

The website uses the same Latin variable-font binaries previously provided by its Google Fonts stylesheet, now hosted alongside the page. Retrieved on 2026-10-30:

| Family | File | Upstream binary |
| --- | --- | --- |
| DM Sans, v17 | `dm-sans-v17-latin.woff2` | https://fonts.gstatic.com/s/dmsans/v17/rP2Yp2ywxg089UriI5-g4vlH9VoD8Cmcqbu0-K6z9mXg.woff2 |
| Manrope, v23 | `manrope-v23-latin.woff2` | https://fonts.gstatic.com/s/manrope/v23/xn7gYHE41ni1AdIRggexSvfedN4.woff2 |

Both are unmodified upstream files. They preserve the existing typography, including intermediate weights. The font faces and Latin unicode ranges are defined in `docs/styles.css`; system fonts cover other characters. Both fonts are preloaded, with `font-display: swap` keeping text visible during loading.

The source stylesheet was the existing Google Fonts CSS2 request for DM Sans weights 400, 450, 500, 550, 600, 650 and 700, and Manrope weights 400, 500, 600, 650, 700, 750 and 800. Its Latin faces use a single variable binary per family.

SIL Open Font License 1.1 notices are included verbatim in `OFL-DM-Sans.txt` and `OFL-Manrope.txt`, from the corresponding `ofl/dmsans` and `ofl/manrope` directories in https://github.com/google/fonts. Keep these notices when updating or redistributing the fonts.
