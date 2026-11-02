# Local website fonts

The website uses two same-origin WOFF2 faces. Syne carries the display typography;
DM Sans keeps paragraphs and controls readable. The SVG logo and wordmark contain
outlines and do not request either font. No Google Fonts stylesheet is loaded.

| Role | Family / weights | Published file | Bytes |
| --- | --- | --- | ---: |
| Body and controls | DM Sans, variable 400–700 | `dm-sans-latin-wght-400-700.woff2` | 23,264 |
| Display headings and statistics | Syne, static 600 | `syne-latin-600.woff2` | 12,296 |
| **Total** | | | **35,560** |

Both faces have Latin coverage, early anonymous preloads, and `font-display: swap`.
System fonts cover Chinese and other scripts; the page does not download a CJK font.
The font-face rules and unicode ranges are in `docs/styles.css`. The complete
stylesheet is generated inline by `scripts/sync-research.mjs`.

## Sources and modifications — 2 November 2026

- **DM Sans v17:** [Google Fonts Latin binary](https://fonts.gstatic.com/s/dmsans/v17/rP2Yp2ywxg089UriI5-g4vlH9VoD8Cmcqbu0-K6z9mXg.woff2),
  retrieved on 30 October 2026. Source SHA-256:
  `468d56b6b25b05b70190b6c233d773f6f1770e8579827ce022a57f03fa8002fb`.
  Its original weight axis spans 100–1000; the published derivative limits it to
  400–700, matching the site's CSS. Original Latin glyph coverage and shaping
  features are retained, including intermediate weights such as 450 and 550.
- **Syne:** [Google Fonts source](https://github.com/google/fonts/tree/main/ofl/syne),
  `Syne[wght].ttf`, retrieved on 2 November 2026. Source SHA-256:
  `ce5ac77142a65cab2248a1a2ebb740b1d4d9c20b52488877d3ff664d1356104a`.
  Instantiated at weight 600, then subset to the Latin unicode range declared in
  CSS and compressed to WOFF2. FontTools' standard layout-feature set retains
  kerning and common ligatures; optional stylistic alternates are not required.

These are modified derivatives, not unmodified upstream binaries. Use FontTools'
`varLib.instancer` to restrict the DM Sans axis and pin Syne at 600. Save and reopen
the instantiated Syne before `subset.Subsetter` runs, so its variation tables are
materialized. Subset by the full CSS unicode range, rather than today's page text,
so future Latin headings remain supported. Save with `flavor = 'woff2'` and Brotli
available. Font tools are an offline maintenance step, not an application or
deployment dependency.

The retired Manrope face and the original DM Sans binary remain in Git history at
`999b73c`; neither is requested by the current page. The previous combined font
payload was 61,416 bytes. The current payload is 25,856 bytes smaller (42.1%).

SIL Open Font License 1.1 notices are included in `OFL-DM-Sans.txt` and
`OFL-Syne.txt`. Keep these notices when updating or redistributing the fonts.
