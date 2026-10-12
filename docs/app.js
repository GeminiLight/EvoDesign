'use strict';

// Table 1 of the supplied manuscript. Metric order:
// Content fidelity, concept logic, semantic relevance; visual aesthetics,
// styling consistency, flow coherence, space balance; cognitive ease,
// comprehension accuracy, self-contained explanation.
const resultData = {
  pixel: [2.111,2.349,2.444,3.810,3.635,3.651,3.571,4.048,2.270,2.921],
  gpt: [
    [3.404,3.421,3.579,2.667,2.579,3.246,2.930,3.772,3.035,2.789],
    [2.000,2.476,1.921,2.778,2.825,2.683,2.540,2.349,2.508,2.492],
    [4.048,3.794,3.587,2.984,3.063,2.921,2.841,3.159,3.540,3.222],
    [3.884,3.566,3.612,2.463,2.891,2.512,2.064,2.806,2.965,2.486],
    [4.118,4.052,4.126,3.612,3.786,3.704,3.536,3.912,3.512,3.086]
  ],
  gemini: [
    [4.021,3.932,4.018,3.184,3.438,3.512,3.076,3.704,3.352,2.604],
    [2.842,3.102,2.784,3.042,3.168,3.044,2.861,2.934,2.886,2.612],
    [4.108,3.906,3.784,3.214,3.302,3.182,3.014,3.426,3.612,3.264],
    [3.812,3.741,3.829,2.752,3.116,2.866,2.351,3.168,3.034,2.604],
    [4.062,4.018,4.097,3.526,3.714,3.681,3.472,3.861,3.486,3.054]
  ],
  deepseek: [
    [3.884,3.792,3.946,3.012,3.214,3.281,2.846,3.486,3.186,2.482],
    [2.716,2.948,2.663,2.884,3.031,2.872,2.702,2.781,2.741,2.486],
    [4.006,3.832,3.712,3.072,3.188,3.064,2.902,3.281,3.496,3.146],
    [3.738,3.664,3.758,2.557,2.998,2.674,2.136,2.914,2.898,2.376],
    [3.936,3.887,4.012,3.317,3.562,3.421,3.213,3.674,3.342,2.891]
  ],
  flash: [
    [3.526,3.412,3.561,2.702,2.954,2.986,2.512,3.108,2.714,2.206],
    [2.346,2.624,2.281,2.641,2.812,2.563,2.418,2.512,2.438,2.214],
    [3.724,3.514,3.408,2.812,2.986,2.824,2.657,3.014,3.146,2.884],
    [3.438,3.274,3.371,2.276,2.742,2.412,1.886,2.586,2.482,2.008],
    [3.684,3.602,3.758,3.038,3.326,3.082,2.842,3.386,3.012,2.548]
  ]
};
const methodLabels = [
  ['GPT-4o-Image', 'Pixel-based'], ['LaTeX TikZ', 'Code-based'],
  ['DiagramAgent', 'Agentic'], ['SciSketch', 'Agentic'],
  ['Schema prompting', 'One-shot schema'], ['EvoDesign', 'Canvas-native']
];
const modelSelect = document.querySelector('#model-select');
const mean = a => a.reduce((sum, v) => sum + v, 0) / a.length;
function renderResults() {
  const rows = [resultData.pixel, ...resultData[modelSelect.value]];
  document.querySelector('#results-body').innerHTML = rows.map((values, i) => {
    const means = [mean(values.slice(0, 3)), mean(values.slice(3, 7)), mean(values.slice(7))];
    return `<tr${i === 5 ? ' class="ours"' : ''}><th scope="row">${methodLabels[i][0]}</th><td>${methodLabels[i][1]}</td>${means.map(v => `<td class="score-cell">${v.toFixed(3)}<span class="score-meter" aria-hidden="true"><i style="width:${v / 5 * 100}%"></i></span></td>`).join('')}</tr>`;
  }).join('');
  document.querySelector('#results-caption').textContent = `Mean score within each dimension · ${modelSelect.selectedOptions[0].textContent} backbone for non-pixel methods · higher is better`;
}
modelSelect.addEventListener('change', renderResults);
renderResults();

// A browser-local illustration, independent of the forthcoming research system.
const svg = document.querySelector('#demo-canvas');
const nodeLayer = document.querySelector('#demo-nodes');
const edgeLayer = document.querySelector('#demo-edges');
const status = document.querySelector('#canvas-status');
const defaultNodes = [
  {x:45,y:125,w:170,h:112,label:'Your intent',detail:'Content + requirements',tag:'THE STARTING POINT',icon:'input'},
  {x:282,y:125,w:155,h:112,label:'Structure',detail:'Entities & relationships',tag:'AGENT 01',icon:'structure'},
  {x:468,y:125,w:145,h:112,label:'Style',detail:'Visual language',tag:'AGENT 02',icon:'style'},
  {x:644,y:125,w:155,h:112,label:'Layout',detail:'Space & connections',tag:'AGENT 03',icon:'layout'},
  {x:853,y:125,w:177,h:112,label:'Verify & refine',detail:'Inspect. Repair. Preserve.',tag:'EDITABLE CANVAS',icon:'verify'}
];
const palettes = [
  [['#f6f5fb','#d7d2e9','#726687'],['#efeafa','#c7b9e6','#7760b0'],['#e8eefb','#bfcce8','#3e6194'],['#e4f2f4','#b1d6db','#316e76'],['#eeeafa','#c6b9e3','#7760ac']],
  [['#f1f5fa','#c8d7e5','#426079'],['#e3f1f4','#a9d3dc','#367c8b'],['#ecebfa','#c7c1e7','#7262ad'],['#e7eefb','#b6c9e7','#3f618e'],['#e9f1f7','#bad3df','#3c637c']]
];
let nodes = defaultNodes.map(n => ({...n}));
let paletteIndex = 0;
let drag = null;
const icons = {
 input:'<path d="M1 2h24M1 9h19M1 16h22"/>',
 structure:'<rect x="9" y="0" width="9" height="7" rx="1"/><rect x="0" y="17" width="9" height="7" rx="1"/><rect x="18" y="17" width="9" height="7" rx="1"/><path d="M13 7v5H4v5m9-5h9v5"/>',
 style:'<circle cx="5" cy="12" r="5"/><circle cx="17" cy="12" r="5"/><circle cx="29" cy="12" r="5"/>',
 layout:'<rect x="0" y="1" width="27" height="8" rx="1"/><rect x="0" y="14" width="11" height="10" rx="1"/><rect x="16" y="14" width="11" height="10" rx="1"/>',
 verify:'<circle cx="13" cy="12" r="12"/><path d="m7 12 4 4 8-9"/>'
};
function renderNodes() {
  nodeLayer.innerHTML = nodes.map((n, i) => {
    const [fill, stroke, ink] = palettes[paletteIndex][i];
    return `<g class="demo-node" data-node="${i}" transform="translate(${n.x},${n.y})" tabindex="0" role="button" aria-label="${n.label} diagram node. Use arrow keys to move."><rect class="node-box" width="${n.w}" height="${n.h}" rx="9" fill="${fill}" stroke="${stroke}"/><text x="15" y="18" font-family="system-ui,sans-serif" font-size="7" letter-spacing="1" fill="${ink}">${n.tag}</text><g transform="translate(16,32)" fill="none" stroke="${ink}" stroke-width="1.5">${icons[n.icon]}</g><text x="15" y="79" font-family="system-ui,sans-serif" font-size="15" font-weight="500" fill="#38384f">${n.label}</text><text x="15" y="96" font-family="system-ui,sans-serif" font-size="8" fill="#625f75">${n.detail}</text><g fill="${stroke}" transform="translate(${n.w-17},35)"><circle cy="0" r="1.3"/><circle cy="5" r="1.3"/><circle cy="10" r="1.3"/></g></g>`;
  }).join('');
  renderEdges();
}
function renderEdges() {
  edgeLayer.innerHTML = nodes.slice(0, -1).map((n, i) => {
    const next = nodes[i + 1];
    const x1 = n.x + n.w + 3, y1 = n.y + n.h / 2;
    const x2 = next.x - 5, y2 = next.y + next.h / 2;
    const bend = Math.max(18, Math.abs(x2 - x1) / 2);
    return `<path d="M${x1} ${y1} C${x1+bend} ${y1},${x2-bend} ${y2},${x2} ${y2}"/>`;
  }).join('');
  const source = nodes[4], target = nodes[1];
  svg.querySelector('#feedback-path').setAttribute('d',
    `M${source.x+source.w/2} ${source.y+source.h} V321 H${target.x+target.w/2} V${target.y+target.h+3}`);
}
function point(event) {
  const p = new DOMPoint(event.clientX, event.clientY);
  return p.matrixTransform(svg.getScreenCTM().inverse());
}
function moveNode(index, x, y) {
  const n = nodes[index];
  n.x = Math.max(10, Math.min(1070 - n.w, x));
  n.y = Math.max(80, Math.min(277 - n.h, y));
  nodeLayer.querySelector(`[data-node="${index}"]`).setAttribute('transform', `translate(${n.x},${n.y})`);
  renderEdges();
}
nodeLayer.addEventListener('pointerdown', event => {
  const el = event.target.closest('[data-node]');
  if (!el || event.button !== 0) return;
  const index = Number(el.dataset.node), p = point(event);
  drag = {index, dx:p.x-nodes[index].x, dy:p.y-nodes[index].y};
  el.setPointerCapture(event.pointerId);
  el.focus({preventScroll:true});
  event.preventDefault();
});
nodeLayer.addEventListener('pointermove', event => {
  if (!drag) return;
  const p = point(event);
  moveNode(drag.index, p.x-drag.dx, p.y-drag.dy);
});
function finishDrag() {
  if (drag) status.textContent = `${nodes[drag.index].label} moved · Connections stay attached`;
  drag = null;
}
nodeLayer.addEventListener('pointerup', finishDrag);
nodeLayer.addEventListener('pointercancel', finishDrag);
nodeLayer.addEventListener('lostpointercapture', finishDrag);
nodeLayer.addEventListener('keydown', event => {
  const keys = {ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
  const delta = keys[event.key], el = event.target.closest('[data-node]');
  if (!delta || !el) return;
  event.preventDefault();
  const i = Number(el.dataset.node), n = nodes[i], step = event.shiftKey ? 20 : 5;
  moveNode(i, n.x+delta[0]*step, n.y+delta[1]*step);
  status.textContent = `${n.label} moved · Use arrow keys to adjust`;
});
document.querySelector('#palette').addEventListener('click', () => {
  paletteIndex = (paletteIndex+1) % palettes.length;
  renderNodes();
  status.textContent = paletteIndex ? 'Palette: cool blue & cyan' : 'Palette: violet, blue & cyan';
});
document.querySelector('#reset').addEventListener('click', () => {
  nodes = defaultNodes.map(n => ({...n}));
  paletteIndex = 0;
  renderNodes();
  status.textContent = 'Original layout restored · Try dragging a node';
});
document.querySelector('#export').addEventListener('click', () => {
  const copy = svg.cloneNode(true);
  copy.setAttribute('xmlns','http://www.w3.org/2000/svg');
  copy.setAttribute('width','1080'); copy.setAttribute('height','370');
  copy.querySelectorAll('[tabindex]').forEach(el => {el.removeAttribute('tabindex');el.removeAttribute('role');});
  const bg = document.createElementNS('http://www.w3.org/2000/svg','rect');
  bg.setAttribute('width','1080');bg.setAttribute('height','370');bg.setAttribute('fill','#fdfdff');
  copy.insertBefore(bg,copy.querySelector('rect'));
  const blob = new Blob([new XMLSerializer().serializeToString(copy)],{type:'image/svg+xml;charset=utf-8'});
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url;link.download = 'EvoDesign-workflow-illustration.svg';document.body.appendChild(link);link.click();link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  status.textContent = 'Your diagram illustration was exported as SVG';
});
renderNodes();
