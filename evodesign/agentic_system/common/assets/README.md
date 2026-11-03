# Bundled node icons

`material_icons.json` contains 74 curated, filled SVGs from
`@material-design-icons/svg` **0.14.15**, matching the generation prompt's
semantic icon list plus the `label` fallback. The original designs are
[Google Material Icons](https://github.com/google/material-design-icons),
licensed under Apache-2.0; the package's license is preserved in
`MATERIAL_ICONS_LICENSE.txt`.

The Python renderer and the web editor consume this same small catalog. Icons
are tinted to the host's exact stroke color and embedded in the scene file.
Generation needs no remote icon requests and no manual asset download for the
Excalidraw web path. The existing optional full-library setup remains available
for legacy integrations and TLDraw.

Do not add untrusted or externally referenced SVGs to this catalog. Keep the
source version and license alongside any future asset updates.
