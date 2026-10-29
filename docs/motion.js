'use strict';

// Presentation effects are progressive enhancements: the page stays readable
// without this file, without JavaScript, or with reduced motion enabled.
(() => {
  const root = document.documentElement;
  const systemMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const animations = new Set();
  const counters = new Set();
  let enabled = !systemMotion.matches;

  function animate(element, frames, options) {
    if (!enabled || document.hidden || !element.animate) return;
    const animation = element.animate(frames, options);
    animations.add(animation);
    animation.onfinish = animation.oncancel = () => animations.delete(animation);
    return animation;
  }

  const stages = [
    ['Start with an idea.', 'Source content and your requirements set the intent for the diagram.'],
    ['Make the meaning explicit.', 'The structure agent identifies entities, relationships, groups, and hierarchy.'],
    ['Give the diagram a visual language.', 'The style agent coordinates shapes, colors, and emphasis across the canvas.'],
    ['Give every element its place.', 'The layout agent estimates sizes, arranges groups, and routes connections.'],
    ['Refine the canvas. Retain the experience.', 'Diagnostic feedback guides local repairs and supplies evidence for future design expertise.']
  ];
  const stageButtons = [...document.querySelectorAll('[data-stage]')];
  const flowButton = document.querySelector('#play-flow');
  const flowCanvas = document.querySelector('#demo-canvas');
  const particles = document.querySelector('#flow-particles');
  const canvasViewport = document.querySelector('.canvas-area');
  let currentStage = 0;
  let flowPlaying = false;
  let flowTimer = 0;
  let particleFrame = 0;
  let hasInteracted = false;
  let autoPlayed = false;

  function highlightStage() {
    document.querySelectorAll('.demo-node').forEach((node, index) => {
      node.classList.toggle('is-stage', index === currentStage);
    });
    document.querySelectorAll('#demo-edges path').forEach((edge, index) => {
      edge.classList.toggle('is-traced', index < currentStage);
    });
    stageButtons.forEach((button, index) => button.setAttribute('aria-pressed', String(index === currentStage)));
  }

  function selectStage(index, { follow = false, announce = false } = {}) {
    currentStage = index;
    highlightStage();
    document.querySelector('#stage-title').textContent = stages[index][0];
    document.querySelector('#stage-description').textContent = stages[index][1];
    animate(document.querySelector('.flow-description'),
      [{ opacity: .2, transform: 'translateY(4px)' }, { opacity: 1, transform: 'translateY(0)' }],
      { duration: 300, easing: 'cubic-bezier(.22,1,.36,1)' });
    if (follow && canvasViewport.scrollWidth > canvasViewport.clientWidth) {
      const node = document.querySelector(`[data-node="${index}"]`).getBoundingClientRect();
      const viewport = canvasViewport.getBoundingClientRect();
      canvasViewport.scrollTo({
        left: canvasViewport.scrollLeft + node.left - viewport.left + node.width / 2 - viewport.width / 2,
        behavior: enabled ? 'smooth' : 'instant'
      });
    }
    if (announce) document.querySelector('#canvas-status').textContent = stages[index][0];
  }

  function stopFlow() {
    clearTimeout(flowTimer);
    cancelAnimationFrame(particleFrame);
    particles.replaceChildren();
    flowPlaying = false;
    flowButton.setAttribute('aria-pressed', 'false');
    flowButton.querySelector('span').textContent = enabled ? 'Play flow' : 'Next step';
    flowButton.querySelector('path').setAttribute('d', 'm4 2 9 6-9 6Z');
  }

  function traceConnection(edgeIndex, duration) {
    cancelAnimationFrame(particleFrame);
    particles.replaceChildren();
    if (!enabled) return;
    const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    dot.setAttribute('r', '3.2'); dot.setAttribute('fill', '#9771c5');
    particles.appendChild(dot);
    const start = performance.now();
    const tick = now => {
      if (!flowPlaying || !enabled) return;
      const edge = document.querySelectorAll('#demo-edges path')[edgeIndex];
      if (!edge) return;
      const progress = Math.min((now - start) / duration, 1);
      const point = edge.getPointAtLength(edge.getTotalLength() * progress);
      dot.setAttribute('cx', point.x); dot.setAttribute('cy', point.y);
      if (progress < 1) particleFrame = requestAnimationFrame(tick);
      else dot.remove();
    };
    particleFrame = requestAnimationFrame(tick);
  }

  function startFlow({ follow = false } = {}) {
    stopFlow();
    if (!enabled) { selectStage((currentStage + 1) % stages.length, { follow, announce: true }); return; }
    flowPlaying = true;
    flowButton.setAttribute('aria-pressed', 'true');
    flowButton.querySelector('span').textContent = 'Pause flow';
    flowButton.querySelector('path').setAttribute('d', 'M4 2h3v12H4ZM10 2h3v12h-3Z');
    selectStage(0, { follow });
    const advance = index => {
      if (!flowPlaying) return;
      if (index === stages.length) { stopFlow(); return; }
      selectStage(index, { follow });
      if (index < stages.length - 1) traceConnection(index, 720);
      flowTimer = setTimeout(() => advance(index + 1), 1000);
    };
    traceConnection(0, 720);
    flowTimer = setTimeout(() => advance(1), 1000);
  }

  flowButton.addEventListener('click', () => {
    hasInteracted = true;
    if (flowPlaying) stopFlow(); else startFlow({ follow: true });
  });
  stageButtons.forEach(button => button.addEventListener('click', () => {
    hasInteracted = true;
    stopFlow();
    selectStage(Number(button.dataset.stage), { follow: true, announce: true });
  }));
  document.addEventListener('canvas:rendered', highlightStage);
  document.addEventListener('canvas:interaction', () => { hasInteracted = true; stopFlow(); });
  document.querySelector('#palette').addEventListener('click', () => { hasInteracted = true; stopFlow(); });
  document.querySelector('#reset').addEventListener('click', () => {
    hasInteracted = true; stopFlow(); selectStage(0);
    canvasViewport.scrollTo({ left: 0, behavior: enabled ? 'smooth' : 'instant' });
  });
  if ('IntersectionObserver' in window) {
    const flowObserver = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (entry.intersectionRatio < .45) { stopFlow(); continue; }
        if (!autoPlayed && !hasInteracted && enabled && !document.hidden && canvasViewport.scrollWidth <= canvasViewport.clientWidth) {
          autoPlayed = true;
          startFlow();
        }
      }
    }, { threshold: .45 });
    flowObserver.observe(canvasViewport);
  }

  function applyMotionPreference() {
    enabled = !systemMotion.matches;
    root.classList.toggle('motion-paused', !enabled);
    if (!enabled) {
      stopFlow();
      [...animations].forEach(animation => animation.finish());
      [...counters].forEach(finish => finish());
    } else if (!flowPlaying) flowButton.querySelector('span').textContent = 'Play flow';
  }
  systemMotion.addEventListener('change', applyMotionPreference);
  document.addEventListener('visibilitychange', () => {
    root.classList.toggle('page-hidden', document.hidden);
    if (document.hidden) {
      stopFlow();
      [...animations].forEach(animation => animation.finish());
      [...counters].forEach(finish => finish());
    }
  });
  applyMotionPreference();
  highlightStage();
  if (canvasViewport.scrollWidth > canvasViewport.clientWidth) {
    document.querySelector('#canvas-status').textContent = 'Tap a step to explore · Drag a node to edit';
  }

  // One-time reveals never leave content hidden if an observer fails to run.
  const revealTargets = document.querySelectorAll(
    '.showcase-heading, .section-heading, .overview-copy, .section-top, .method-step, .memory-band, .refinement-copy, .case-study, .benchmark-lower>div, .results-table-wrap, .result-highlights>div, .research-definition, .brief-facts, .question-list, .citation-section, .resources'
  );
  if ('IntersectionObserver' in window) {
    const revealObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        revealObserver.unobserve(entry.target);
        const stagger = entry.target.classList.contains('method-step') ? [...entry.target.parentElement.children].indexOf(entry.target) * 65 : 0;
        animate(entry.target,
          [{ opacity: 0, transform: 'translateY(20px)' }, { opacity: 1, transform: 'translateY(0)' }],
          { duration: 700, delay: stagger, easing: 'cubic-bezier(.22,1,.36,1)', fill: 'backwards' });
        if (entry.target.classList.contains('results-table-wrap')) animateResultMeters();
        if (entry.target.classList.contains('memory-band')) {
          entry.target.querySelectorAll('.memory-levels>div').forEach((level, index) => {
            animate(level, [{ opacity: .25, transform: 'translateX(-9px)' }, { opacity: 1, transform: 'translateX(0)' }],
              { duration: 650, delay: 240 + index * 180, easing: 'cubic-bezier(.22,1,.36,1)', fill: 'backwards' });
          });
        }
        if (entry.target.classList.contains('citation-section')) {
          entry.target.querySelectorAll('.citation-orbit i').forEach((ring, index) => {
            animate(ring, [{ opacity: 0, transform: 'scale(.7)' }, { opacity: 1, transform: 'scale(1)' }],
              { duration: 950, delay: index * 120, easing: 'cubic-bezier(.22,1,.36,1)', fill: 'backwards' });
          });
        }
      });
    }, { threshold: .12 });
    revealTargets.forEach(element => revealObserver.observe(element));
    const heroObserver = new IntersectionObserver(entries => {
      document.querySelector('.hero').classList.toggle('is-offscreen', !entries[0].isIntersecting);
    });
    heroObserver.observe(document.querySelector('.hero'));
  }
  document.querySelectorAll('.hero-eyebrow, h1, .paper-title, .author-block, .hero-actions, .hero-caption, .hero-shortcuts').forEach((element, index) => {
    animate(element,
      [{ opacity: 0, transform: 'translateY(12px)' }, { opacity: 1, transform: 'translateY(0)' }],
      { duration: 800, delay: index * 70, easing: 'cubic-bezier(.22,1,.36,1)', fill: 'backwards' });
  });

  const formatter = new Intl.NumberFormat('en-US');
  function countUp(element) {
    if (!enabled || document.hidden) return;
    const value = Number(element.dataset.count), output = element.querySelector('span');
    const start = performance.now();
    let frame;
    const finish = () => { cancelAnimationFrame(frame); output.textContent = formatter.format(value); counters.delete(finish); };
    counters.add(finish);
    const tick = now => {
      const progress = Math.min((now - start) / 950, 1);
      output.textContent = formatter.format(Math.round(value * (1 - (1 - progress) ** 3)));
      if (progress < 1) frame = requestAnimationFrame(tick); else finish();
    };
    frame = requestAnimationFrame(tick);
  }
  if ('IntersectionObserver' in window) {
    const statObserver = new IntersectionObserver(entries => entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      statObserver.unobserve(entry.target); countUp(entry.target);
    }), { threshold: .7 });
    document.querySelectorAll('[data-count]').forEach(element => statObserver.observe(element));
  }

  function animateResultMeters() {
    document.querySelectorAll('.score-meter i').forEach((meter, index) => {
      animate(meter, [{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }],
        { duration: 650, delay: index % 3 * 50, easing: 'cubic-bezier(.22,1,.36,1)' });
    });
  }
  document.addEventListener('results:rendered', () => {
    const table = document.querySelector('.results-table-wrap');
    if (table.getBoundingClientRect().top < innerHeight) animateResultMeters();
  });

  const header = document.querySelector('.site-header');
  const navSections = [...document.querySelectorAll('.nav-links a[href^="#"]')]
    .map(link => ({ link, section: document.getElementById(link.hash.slice(1)) }))
    .filter(item => item.section);
  let scrollFrame = 0;
  function updateScroll() {
    scrollFrame = 0;
    const max = document.documentElement.scrollHeight - innerHeight;
    header.style.setProperty('--reading-progress', max > 0 ? Math.min(scrollY / max, 1) : 0);
    header.classList.toggle('is-scrolled', scrollY > 16);
    let active = null;
    navSections.forEach(item => { if (item.section.getBoundingClientRect().top <= 180) active = item; });
    navSections.forEach(item => {
      item.link.classList.toggle('is-active', item === active);
      if (item === active) item.link.setAttribute('aria-current', 'location'); else item.link.removeAttribute('aria-current');
    });
  }
  function scheduleScroll() { if (!scrollFrame) scrollFrame = requestAnimationFrame(updateScroll); }
  window.addEventListener('scroll', scheduleScroll, { passive: true });
  window.addEventListener('resize', scheduleScroll, { passive: true });
  updateScroll();

  const dialog = document.querySelector('#figure-dialog');
  const figureImage = document.querySelector('#figure-image');
  document.querySelectorAll('[data-figure]').forEach(button => button.addEventListener('click', event => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const image = button.querySelector('img');
    const paperFigure = button.classList.contains('paper-figure-view');
    dialog.classList.toggle('figure-dialog-wide', paperFigure);
    document.querySelector('#figure-eyebrow').textContent = paperFigure ? 'RESEARCH / PAPER FIGURE' : 'REFINEMENT CASE STUDY';
    document.querySelector('#figure-title').textContent = button.dataset.figureTitle || (button.dataset.figure === 'before' ? 'Initial solution' : 'After refinement');
    document.querySelector('#figure-caption').textContent = button.dataset.figureCaption || 'Software development lifecycle with change control · Manuscript Figure 9';
    document.querySelector('#figure-original').href = image.src;
    figureImage.src = image.src; figureImage.alt = image.alt;
    dialog.showModal(); document.body.classList.add('has-dialog');
    animate(dialog, [{ opacity: 0, transform: 'translateY(10px) scale(.98)' }, { opacity: 1, transform: 'none' }],
      { duration: 280, easing: 'cubic-bezier(.22,1,.36,1)' });
  }));
  document.querySelector('#close-figure').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => document.body.classList.remove('has-dialog'));
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });

  // Native details preserve all research text and navigation without JavaScript.
  const contents = document.querySelector('.mobile-contents');
  contents.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
    contents.open = false;
    const section = document.querySelector(link.hash);
    if (section) {
      section.setAttribute('tabindex', '-1');
      section.focus({ preventScroll: true });
    }
  }));
  document.addEventListener('pointerdown', event => {
    if (contents.open && !contents.contains(event.target)) contents.open = false;
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && contents.open) {
      contents.open = false;
      contents.querySelector('summary').focus();
    }
  });
  contents.addEventListener('focusout', event => {
    if (event.relatedTarget && !contents.contains(event.relatedTarget)) contents.open = false;
  });
  document.querySelectorAll('.research-question, .mobile-contents').forEach(detail => {
    detail.addEventListener('toggle', () => {
      if (!detail.open) return;
      const content = detail.querySelector('.question-answer, pre, .contents-panel');
      animate(content, [{ opacity: .3, transform: 'translateY(-5px)' }, { opacity: 1, transform: 'translateY(0)' }],
        { duration: 320, easing: 'cubic-bezier(.22,1,.36,1)' });
    });
  });

  const copyButton = document.querySelector('#copy-citation');
  const copyStatus = document.querySelector('#copy-status');
  let copyTimer;
  function showCopySuccess() {
    copyButton.classList.add('is-copied');
    copyButton.querySelector('span').textContent = 'Copied';
    copyButton.setAttribute('aria-label', 'Citation copied');
    copyStatus.classList.add('sr-only');
    copyStatus.textContent = 'BibTeX copied. Ready to paste into your bibliography.';
    animate(copyButton, [{ transform: 'scale(.97)' }, { transform: 'scale(1)' }], { duration: 240, easing: 'ease-out' });
    copyTimer = setTimeout(() => {
      copyButton.classList.remove('is-copied');
      copyButton.querySelector('span').textContent = 'Copy';
      copyButton.setAttribute('aria-label', 'Copy BibTeX citation');
    }, 2800);
  }
  copyButton.hidden = false;
  copyButton.addEventListener('click', async () => {
    clearTimeout(copyTimer);
    copyButton.classList.remove('is-copied');
    copyButton.querySelector('span').textContent = 'Copy';
    copyButton.setAttribute('aria-label', 'Copy BibTeX citation');
    const code = document.querySelector('#bibtex');
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(code.textContent.trim());
      showCopySuccess();
    } catch {
      code.parentElement.focus();
      const range = document.createRange();
      range.selectNodeContents(code);
      const selection = window.getSelection();
      selection.removeAllRanges(); selection.addRange(range);
      // Local file previews and older browsers may only expose this copy path.
      try {
        if (document.execCommand('copy')) { showCopySuccess(); return; }
      } catch { /* Keep the citation selected for manual copying. */ }
      copyStatus.classList.remove('sr-only');
      copyStatus.textContent = 'Citation selected. Press ⌘C or Ctrl+C to copy.';
    }
  });
})();
