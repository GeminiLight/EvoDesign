// Run after changing research/paper.json or the manuscript data in docs/app.js.
// Generated files are committed; GitHub Pages needs no build step.
import fs from 'node:fs';
import vm from 'node:vm';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const write = (file, text) => fs.writeFileSync(path.join(root, file), text);
const paper = JSON.parse(read('research/paper.json'));
const escape = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const productTitle = 'EvoDesign — Turn ideas into editable diagrams';
const productDescription = 'Create editable diagrams in your browser with the shared demo or your own model. Explore the open-source research pipeline and personal design memory.';
const fullName = author => `${author.given} ${author.family}`;
const bibtex = `@misc{wang2026evodesign,
  title = {${paper.title.replace('EvoDesign', '{EvoDesign}')}},
  author = {${paper.authors.map(a => `${a.family}, ${a.given}`).join(' and\n            ')}},
  year = {${paper.year}},
  eprint = {${paper.arxiv}},
  archivePrefix = {arXiv},
  primaryClass = {${paper.primaryClass}},
  doi = {${paper.doi}},
  url = {${paper.paperUrl}}
}`;
write('docs/citation.bib', bibtex + '\n');
write('docs/citation.ris', ['TY  - UNPB', `TI  - ${paper.title}`, ...paper.authors.map(a => `AU  - ${a.family}, ${a.given}`), `PY  - ${paper.year}`, `DO  - ${paper.doi}`, `UR  - ${paper.paperUrl}`, `N1  - arXiv:${paper.arxiv}`, 'ER  - ', ''].join('\n'));

const cffAuthors = indent => paper.authors.map(a => `${indent}- family-names: "${a.family}"\n${indent}  given-names: "${a.given}"`).join('\n');
write('CITATION.cff', `cff-version: 1.2.0
message: "If you use EvoDesign or CanvasBench in your research, please cite the paper below."
title: "${paper.title}"
type: software
authors:
${cffAuthors('  ')}
url: "${paper.url}"
repository-code: "${paper.repository}"
preferred-citation:
  type: article
  title: "${paper.title}"
  authors:
${cffAuthors('    ')}
  year: ${paper.year}
  journal: "arXiv"
  doi: "${paper.doi}"
  url: "${paper.paperUrl}"
  notes: "arXiv:${paper.arxiv}; source code available in the project repository."
`);

const article = {
  '@type': 'ScholarlyArticle', '@id': `${paper.url}#paper`,
  headline: paper.title, name: paper.title, description: paper.description,
  abstract: paper.abstract, inLanguage: 'en', url: paper.paperUrl,
  sameAs: [`https://doi.org/${paper.doi}`],
  identifier: [{ '@type': 'PropertyValue', propertyID: 'arXiv', value: paper.arxiv }, { '@type': 'PropertyValue', propertyID: 'DOI', value: paper.doi }],
  author: paper.authors.map(a => ({ '@type': 'Person', name: fullName(a), affiliation: a.affiliations.map(n => ({ '@type': 'Organization', name: paper.affiliations[n - 1] })) })),
  mainEntityOfPage: { '@id': paper.url },
  keywords: ['editable diagram generation', 'multi-agent systems', 'design expertise evolution', 'CanvasBench', 'canvas-based diagramming'],
};
const structured = { '@context': 'https://schema.org', '@graph': [
  { '@type': 'WebPage', '@id': paper.url, url: paper.url, name: productTitle, description: productDescription, inLanguage: 'en', dateModified: paper.pageModified, mainEntity: { '@id': `${paper.url}#software` }, about: { '@id': `${paper.url}#paper` }, relatedLink: [paper.paperUrl, paper.repository], primaryImageOfPage: { '@type': 'ImageObject', url: `${paper.url}assets/social-preview.png`, width: 1200, height: 630 } }, { '@type': 'SoftwareSourceCode', '@id': `${paper.url}#software`, name: 'EvoDesign', description: productDescription, codeRepository: paper.repository, url: paper.url, programmingLanguage: ['Python', 'TypeScript'], runtimePlatform: 'Python 3.11+ and Node.js 22.12+', license: `${paper.repository}/blob/main/LICENSE`, citation: { '@id': `${paper.url}#paper` } }, article
] };
const meta = (name, content, property = false) => `<meta ${property ? 'property' : 'name'}="${name}" content="${escape(content)}">`;
const tags = [
  meta('description', productDescription), `<link rel="canonical" href="${paper.url}">`,
  `<link rel="sitemap" type="application/xml" href="${paper.url}sitemap.xml">`,
  meta('robots', 'index, follow, max-image-preview:large'),
  meta('og:type', 'website', true), meta('og:title', productTitle, true),
  meta('og:description', productDescription, true), meta('og:url', paper.url, true),
  meta('og:site_name', 'EvoDesign', true), meta('og:locale', 'en_US', true),
  meta('og:image', `${paper.url}assets/social-preview.png`, true),
  meta('og:image:width', '1200', true), meta('og:image:height', '630', true),
  meta('og:image:alt', 'EvoDesign — editable diagrams, evolving design expertise.', true),
  meta('twitter:card', 'summary_large_image'), meta('twitter:title', productTitle),
  meta('twitter:description', productDescription), meta('twitter:image', `${paper.url}assets/social-preview.png`),
  meta('twitter:image:alt', 'EvoDesign — editable diagrams, evolving design expertise.'),
  meta('citation_title', paper.title), ...paper.authors.map(a => meta('citation_author', fullName(a))),
  meta('citation_publication_date', String(paper.year)), meta('citation_doi', paper.doi),
  meta('citation_arxiv_id', paper.arxiv), meta('citation_abstract_html_url', paper.url),
  // Scholar requires a same-directory PDF for citation_pdf_url. The author will
  // supply the renamed camera-ready PDF later; do not publish the anonymous draft.
  `<script type="application/ld+json">\n${JSON.stringify(structured, null, 2).replaceAll('<', '\\u003c')}\n</script>`
];
let html = read('docs/index.html');
function replaceBlock(label, content) {
  const pattern = new RegExp(`(<!-- ${label}:START -->)[\\s\\S]*?(<!-- ${label}:END -->)`);
  if (!pattern.test(html)) throw new Error(`Missing ${label} markers`);
  html = html.replace(pattern, (_, start, end) => `${start}\n${content}\n${end}`);
}
replaceBlock('RESEARCH-METADATA', tags.join('\n  '));
replaceBlock('ABSTRACT', `<p>${escape(paper.abstract)}</p>`);
replaceBlock('BIBTEX', escape(bibtex.replaceAll(' and\n            ', ' and ')));
// The page is a small static document: inline its styles to avoid two cold-load
// round trips. Keep the editable CSS sources and their original cascade order.
const siteStyles = ['styles.css', 'polish.css'].map(file => read(`docs/${file}`)).join('\n');
if (/<\/style/i.test(siteStyles)) throw new Error('Unexpected closing style tag in site CSS');
replaceBlock('SITE-STYLES', `<style>\n${siteStyles}\n</style>`);

// Reuse the exact authored metric arrays, without running any DOM code.
const dataCode = read('docs/app.js').split('const modelSelect =')[0];
const { resultData, methodLabels } = vm.runInNewContext(`${dataCode}; ({resultData, methodLabels});`);
const mean = numbers => numbers.reduce((a, b) => a + b, 0) / numbers.length;
const means = row => [mean(row.slice(0, 3)), mean(row.slice(3, 7)), mean(row.slice(7))];
replaceBlock('RESULTS', [resultData.pixel, ...resultData.gpt].map((row, i) => `<tr${i === 5 ? ' class="ours"' : ''}><th scope="row">${escape(methodLabels[i][0])}</th><td>${escape(methodLabels[i][1])}</td>${means(row).map(v => `<td class="score-cell">${v.toFixed(3)}<span class="score-meter" aria-hidden="true"><i style="width:${v / 5 * 100}%"></i></span></td>`).join('')}</tr>`).join('\n'));
for (const file of ['app.js', 'motion.js']) {
  const hash = createHash('sha256').update(read(`docs/${file}`)).digest('hex').slice(0, 10);
  html = html.replace(new RegExp(`${file.replace('.', '\\.')}\\?v=[a-f0-9]+`, 'g'), `${file}?v=${hash}`);
}
write('docs/index.html', html);
write('docs/sitemap.xml', `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>${paper.url}</loc><lastmod>${paper.pageModified}</lastmod></url>
</urlset>
`);
const csv = [['backbone', 'method', 'representation', 'content_fidelity', 'concept_logic', 'semantic_relevance', 'visual_aesthetics', 'styling_consistency', 'flow_coherence', 'space_balance', 'cognitive_ease', 'comprehension_accuracy', 'self_contained_explanation', 'content_mean', 'visual_mean', 'cognitive_mean', 'source']];
for (const [key, label] of Object.entries({ gpt: 'GPT-5.5', gemini: 'Gemini-3.1-Pro', deepseek: 'DeepSeek-V4-Pro', flash: 'DeepSeek-V4-Flash' })) {
  [resultData.pixel, ...resultData[key]].forEach((values, i) => csv.push([i === 0 ? 'GPT-4o-Image (fixed pixel baseline)' : label, ...methodLabels[i], ...values.map(v => v.toFixed(3)), ...means(values).map(v => v.toFixed(3)), 'Supplied manuscript Table 1']));
}
write('docs/results.csv', csv.map(row => row.join(',')).join('\n') + '\n');
for (const file of ['README.md', 'README.zh-CN.md']) {
  let readme = read(file);
  if (readme.includes('<!-- CITATION:START -->')) readme = readme.replace(/<!-- CITATION:START -->[\s\S]*?<!-- CITATION:END -->/, `<!-- CITATION:START -->\n\n\`\`\`bibtex\n${bibtex}\n\`\`\`\n\n<!-- CITATION:END -->`);
  write(file, readme);
}
console.log('Synced scholarly metadata, static results, BibTeX, RIS, CFF, CSV, sitemap, and asset hashes.');
