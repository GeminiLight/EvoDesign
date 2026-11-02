# EvoDesign identity

The blue-violet folded plane and cyan foreground are the **C / Thought takes
shape** concept selected on 2 November 2026. Preserve this geometry and its open
negative space across applications.

- `evodesign-mark.svg`: transparent symbol; browser favicon and small placements.
- `evodesign-icon.svg`, `evodesign-icon-dark.svg`: padded application icons.
- `evodesign-lockup.svg`, `evodesign-lockup-dark.svg`: symbol and outlined wordmark.
- `*-mono.svg`, `*-white.svg`: single-color variants for print or reversed use.
- `evodesign-social.png`: 1200 × 630 sharing image.
- `apple-touch-icon.png`: 180 × 180 home-screen icon.
- `evodesign-icon-512.png`: 512 × 512 application icon.

Geometry, colors and outlined glyphs live in `shared/brand.json`. Run
`node scripts/sync-brand.mjs` from the repository root to regenerate SVGs and
their legacy URL aliases. After installing the renderer dependencies, run
`node scripts/sync-brand.mjs --raster` to regenerate PNG/ICO exports as well.
The script uses the renderer's existing Sharp package. Commit the source and
generated files together; the app needs no image-rendering dependency at runtime.

The wordmark uses Syne Bold 700 glyph outlines under SIL OFL 1.1. Keep
`Syne-OFL.txt` with the assets. Evo uses blue-violet and Design uses teal;
the dark-theme lockup uses lighter matching colors. HarfBuzz kerning is
preserved in the outlined glyphs. Font source: https://github.com/google/fonts/tree/main/ofl/syne . Vector wordmarks do not load a font or depend
on the viewer's installed fonts. Dark assets follow the application's explicit
theme, including when it differs from the operating-system preference.

Old screenshot and experiment images are historical records; they are not logo
sources. Do not edit research figures to insert product branding.
