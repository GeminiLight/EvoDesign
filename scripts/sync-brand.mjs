#!/usr/bin/env node
// Generate every identity surface from the approved C concept and outlined type.
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const brand = JSON.parse(await readFile(resolve(root, 'shared/brand.json'), 'utf8'));
const { colors, markPaths, wordmarkPaths } = brand;
const header = '<!-- Generated from shared/brand.json by scripts/sync-brand.mjs. -->\n';
const svg = (viewBox, content, extra = '') => `${header}<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}" ${extra}>\n${content}\n</svg>\n`;
const gradients = `<defs>
  <linearGradient id="violet" x1="0" y1="0" x2="260" y2="310" gradientUnits="userSpaceOnUse"><stop stop-color="${colors.violetStart}"/><stop offset="1" stop-color="${colors.violetEnd}"/></linearGradient>
  <linearGradient id="cyan" x1="360" y1="145" x2="170" y2="320" gradientUnits="userSpaceOnUse"><stop stop-color="${colors.cyanStart}"/><stop offset="1" stop-color="${colors.cyanEnd}"/></linearGradient>
</defs>`;
const mark = (mono) => markPaths.map((d, i) => `<path d="${d}" fill="${mono || `url(#${i ? 'cyan' : 'violet'})`}"/>`).join('\n');
const symbol = (mono) => `${mono ? '' : gradients}\n<g transform="translate(11 12)">${mark(mono)}</g>`;
const wordmark = (ink, mono) => {
  const dark = ink === colors.white;
  const evo = dark ? colors.wordmarkEvoDark : colors.wordmarkEvo;
  const design = dark ? colors.wordmarkDesignDark : colors.wordmarkDesign;
  return `<g>${wordmarkPaths.map((d, i) => `<path d="${d}" fill="${mono || (i < 3 ? evo : design)}"/>`).join('')}</g>`;
};
const lockup = (ink, mono) => `${mono ? '' : gradients}
<g transform="translate(0 1) scale(.165)">${mark(mono)}</g>
<g transform="translate(3.1125 0) scale(1.25)">${wordmark(ink, mono)}</g>`;
const icon = (dark) => `${gradients}
<rect width="512" height="512" rx="112" fill="${dark ? '#121526' : '#f7f8fc'}"/>
<g transform="translate(60 62) scale(1.04)">${mark()}</g>`;
const social = svg('0 0 1200 630', `${gradients}
<rect width="1200" height="630" fill="#f8f9fd"/>
<path d="M80 90H1120M80 540H1120" stroke="#e1e4f0"/>
<g transform="translate(172 202) scale(3.1)">${lockup(colors.ink).replace(gradients, '')}</g>
<text x="600" y="465" text-anchor="middle" font-family="Arial,sans-serif" font-size="29" fill="#65718b">Editable diagrams. Evolving expertise.</text>
<text x="80" y="585" font-family="Arial,sans-serif" font-size="17" fill="#68758d">evodesign.aurax.live</text>
<text x="1120" y="585" text-anchor="end" font-family="Arial,sans-serif" font-size="17" fill="#68758d">github.com/GeminiLight/EvoDesign</text>`, 'width="1200" height="630"');

const files = new Map([
  ['frontend/public/brand/evodesign-mark.svg', svg(brand.viewBox, symbol())],
  ['frontend/public/brand/evodesign-mark-mono.svg', svg(brand.viewBox, symbol(colors.ink))],
  ['frontend/public/brand/evodesign-mark-white.svg', svg(brand.viewBox, symbol(colors.white))],
  ['frontend/public/brand/evodesign-icon.svg', svg('0 0 512 512', icon(false))],
  ['frontend/public/brand/evodesign-icon-dark.svg', svg('0 0 512 512', icon(true))],
  ['frontend/public/brand/evodesign-lockup.svg', svg('0 0 276 64', lockup(colors.ink))],
  ['frontend/public/brand/evodesign-lockup-dark.svg', svg('0 0 276 64', lockup(colors.white))],
  ['frontend/public/brand/evodesign-wordmark.svg', svg('76 8 200 48', `<g transform="translate(3.1125 0) scale(1.25)">${wordmark(colors.ink)}</g>`)],
  ['frontend/public/brand/evodesign-wordmark-dark.svg', svg('76 8 200 48', `<g transform="translate(3.1125 0) scale(1.25)">${wordmark(colors.white)}</g>`)],
  ['frontend/public/brand/evodesign-lockup-mono.svg', svg('0 0 276 64', lockup(colors.ink, colors.ink))],
  ['frontend/public/brand/evodesign-lockup-white.svg', svg('0 0 276 64', lockup(colors.white, colors.white))],
  ['frontend/public/brand/evodesign-social.svg', social],
  // Keep old public URLs functional, but never keep old artwork behind them.
  ['frontend/public/evodiagram.svg', svg('0 0 512 512', icon(false))],
  ['frontend/public/evodiagram-dark.svg', svg('0 0 512 512', icon(true))],
  ['evodesign/agentic_system/tool_services/src/app/icon.svg', svg(brand.viewBox, symbol())],
]);

// The dev repository has no paper website; avoid creating a second one there.
try {
  await readFile(resolve(root, 'docs/index.html'));
  files.set('docs/assets/studio-logo.svg', svg(brand.viewBox, symbol()));
  files.set('docs/assets/favicon.svg', svg(brand.viewBox, symbol()));
  files.set('docs/assets/evodesign-lockup.svg', svg('0 0 276 64', lockup(colors.ink)));
  files.set('docs/assets/social-preview.svg', social);
} catch (error) {
  if (error.code !== 'ENOENT') throw error;
}

for (const [file, contents] of files) {
  await mkdir(dirname(resolve(root, file)), { recursive: true });
  await writeFile(resolve(root, file), contents);
}
console.log(`Updated ${files.size} brand assets from the selected C concept.`);

// Raster exports use the renderer's existing Sharp dependency; no extra package.
if (process.argv.includes('--raster')) {
  const require = createRequire(resolve(root, 'evodesign/agentic_system/tool_services/package.json'));
  const sharp = require('sharp');
  const raster = async (source, width) => sharp(Buffer.from(source)).resize(width).png().toBuffer();
  const iconSvg = files.get('frontend/public/brand/evodesign-icon.svg');
  const outputs = new Map([
    ['frontend/public/brand/evodesign-social.png', await raster(social, 1200)],
    ['frontend/public/brand/apple-touch-icon.png', await raster(iconSvg, 180)],
    ['frontend/public/brand/evodesign-icon-512.png', await raster(iconSvg, 512)],
  ]);
  const sizes = [16, 32, 48];
  const images = await Promise.all(sizes.map(size => raster(svg(brand.viewBox, symbol()), size)));
  const directory = Buffer.alloc(6 + 16 * sizes.length);
  directory.writeUInt16LE(1, 2);
  directory.writeUInt16LE(sizes.length, 4);
  let offset = directory.length;
  for (let i = 0; i < sizes.length; i++) {
    const index = 6 + i * 16;
    directory[index] = directory[index + 1] = sizes[i];
    directory.writeUInt16LE(1, index + 4);
    directory.writeUInt16LE(32, index + 6);
    directory.writeUInt32LE(images[i].length, index + 8);
    directory.writeUInt32LE(offset, index + 12);
    offset += images[i].length;
  }
  const favicon = Buffer.concat([directory, ...images]);
  outputs.set('frontend/public/favicon.ico', favicon);
  outputs.set('evodesign/agentic_system/tool_services/src/app/favicon.ico', favicon);
  if (files.has('docs/assets/studio-logo.svg')) {
    outputs.set('docs/assets/social-preview.png', outputs.get('frontend/public/brand/evodesign-social.png'));
    outputs.set('docs/assets/apple-touch-icon.png', outputs.get('frontend/public/brand/apple-touch-icon.png'));
    outputs.set('docs/assets/favicon.ico', favicon);
  }
  for (const [file, contents] of outputs) {
    await mkdir(dirname(resolve(root, file)), { recursive: true });
    await writeFile(resolve(root, file), contents);
  }
  console.log(`Exported ${outputs.size} PNG/ICO assets.`);
}
