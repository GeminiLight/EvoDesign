import { useRef, useEffect, useState, useCallback } from 'react';
import type { KeyboardEvent } from 'react';
import { Search, Sparkles } from 'lucide-react';

interface GalleryHeroProps {
  t: (key: string) => string;
  searchQuery: string;
  onSearchChange: (value: string) => void;
  activeTab: 'works' | 'dna';
  onTabChange: (tab: 'works' | 'dna') => void;
}

// ─── Particle system ──────────────────────
interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  depth: number; // 0..1 — simulates z-depth for parallax
  hue: number;   // color variation within brand range
}

const PARTICLE_COUNT = 48;
const CONNECTION_DIST = 0.12; // as fraction of canvas width
const MOUSE_RADIUS = 0.15;

function createParticles(): Particle[] {
  return Array.from({ length: PARTICLE_COUNT }, () => ({
    x: Math.random(),
    y: Math.random(),
    vx: (Math.random() - 0.5) * 0.0004,
    vy: (Math.random() - 0.5) * 0.0003,
    r: 0.8 + Math.random() * 1.8,
    depth: 0.3 + Math.random() * 0.7,
    hue: 200 + Math.random() * 30, // brand blue-ish range
  }));
}

const SEARCH_HINTS = ['searchHint1', 'searchHint2', 'searchHint3', 'searchHint4'] as const;
const TAB_ORDER: Array<'works' | 'dna'> = ['works', 'dna'];
const WORKS_TAB_ID = 'gallery-tab-works';
const DNA_TAB_ID = 'gallery-tab-dna';
const RESULTS_PANEL_ID = 'gallery-results-panel';

export const GalleryHero = ({
  t,
  searchQuery,
  onSearchChange,
  activeTab,
  onTabChange,
}: GalleryHeroProps) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const particlesRef = useRef<Particle[]>(createParticles());
  const mouseRef = useRef({ x: -1, y: -1 });
  const rafRef = useRef<number>(0);
  const sectionRef = useRef<HTMLElement>(null);
  const isVisibleRef = useRef(true);
  const [hintIndex, setHintIndex] = useState(0);
  const [searchFocused, setSearchFocused] = useState(false);
  const [streamKey, setStreamKey] = useState(0);
  const currentSearchHint = t(`gallery.${SEARCH_HINTS[hintIndex]}`);

  // ── Mouse tracking (normalized) ──
  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    mouseRef.current = {
      x: (e.clientX - rect.left) / rect.width,
      y: (e.clientY - rect.top) / rect.height,
    };
  }, []);

  const handleMouseLeave = useCallback(() => {
    mouseRef.current = { x: -1, y: -1 };
  }, []);

  // ── Canvas animation loop ──
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio, 2);
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener('resize', resize);

    const isDark = () => document.documentElement.classList.contains('dark');

    // ── Helper: draw a single static frame (particles + connections) ──
    const drawStaticFrame = () => {
      const { width: w, height: h } = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, w, h);

      const particles = particlesRef.current;
      const dark = isDark();

      // Draw connections
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const a = particles[i];
          const b = particles[j];
          const dist = Math.hypot(a.x - b.x, a.y - b.y);
          if (dist < CONNECTION_DIST) {
            const alpha = (1 - dist / CONNECTION_DIST) * 0.15 * Math.min(a.depth, b.depth);
            ctx.beginPath();
            ctx.moveTo(a.x * w, a.y * h);
            ctx.lineTo(b.x * w, b.y * h);
            ctx.strokeStyle = dark
              ? `hsla(${(a.hue + b.hue) / 2}, 60%, 65%, ${alpha})`
              : `hsla(${(a.hue + b.hue) / 2}, 70%, 55%, ${alpha})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
      }

      // Draw particles
      for (const p of particles) {
        const alpha = 0.15 + p.depth * 0.35;
        ctx.beginPath();
        ctx.arc(p.x * w, p.y * h, p.r * p.depth, 0, Math.PI * 2);
        ctx.fillStyle = dark
          ? `hsla(${p.hue}, 55%, 65%, ${alpha})`
          : `hsla(${p.hue}, 65%, 52%, ${alpha})`;
        ctx.fill();
      }
    };

    // ── prefers-reduced-motion: draw once and bail out ──
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) {
      drawStaticFrame();
      // Only clean up the resize listener; no rAF to cancel
      return () => {
        window.removeEventListener('resize', resize);
      };
    }

    // ── IntersectionObserver: pause rAF when section is off-screen ──
    let observer: IntersectionObserver | undefined;
    if (sectionRef.current) {
      observer = new IntersectionObserver(
        ([entry]) => {
          isVisibleRef.current = entry.isIntersecting;
        },
        { threshold: 0 },
      );
      observer.observe(sectionRef.current);
    }

    const tick = () => {
      // If the section is not visible, skip drawing but keep the loop alive
      if (!isVisibleRef.current) {
        rafRef.current = requestAnimationFrame(tick);
        return;
      }

      const { width: w, height: h } = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, w, h);

      const particles = particlesRef.current;
      const mx = mouseRef.current.x;
      const my = mouseRef.current.y;
      const dark = isDark();

      // Update positions
      for (const p of particles) {
        p.x += p.vx;
        p.y += p.vy;
        // Wrap around
        if (p.x < -0.02) p.x = 1.02;
        if (p.x > 1.02) p.x = -0.02;
        if (p.y < -0.02) p.y = 1.02;
        if (p.y > 1.02) p.y = -0.02;

        // Mouse gravity — gentle pull
        if (mx >= 0) {
          const dx = mx - p.x;
          const dy = my - p.y;
          const dist = Math.hypot(dx, dy);
          if (dist < MOUSE_RADIUS && dist > 0.005) {
            const force = ((MOUSE_RADIUS - dist) / MOUSE_RADIUS) * 0.00025 * p.depth;
            p.vx += (dx / dist) * force;
            p.vy += (dy / dist) * force;
          }
        }

        // Damping
        p.vx *= 0.998;
        p.vy *= 0.998;
      }

      // Draw connections (high-frequency, semi-transparent)
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const a = particles[i];
          const b = particles[j];
          const dist = Math.hypot(a.x - b.x, a.y - b.y);
          if (dist < CONNECTION_DIST) {
            const alpha = (1 - dist / CONNECTION_DIST) * 0.15 * Math.min(a.depth, b.depth);
            ctx.beginPath();
            ctx.moveTo(a.x * w, a.y * h);
            ctx.lineTo(b.x * w, b.y * h);
            ctx.strokeStyle = dark
              ? `hsla(${(a.hue + b.hue) / 2}, 60%, 65%, ${alpha})`
              : `hsla(${(a.hue + b.hue) / 2}, 70%, 55%, ${alpha})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
      }

      // Draw particles
      for (const p of particles) {
        const baseAlpha = 0.15 + p.depth * 0.35;
        // Brighten near mouse
        let alpha = baseAlpha;
        if (mx >= 0) {
          const md = Math.hypot(mx - p.x, my - p.y);
          if (md < MOUSE_RADIUS) {
            alpha += (1 - md / MOUSE_RADIUS) * 0.3;
          }
        }
        ctx.beginPath();
        ctx.arc(p.x * w, p.y * h, p.r * p.depth, 0, Math.PI * 2);
        ctx.fillStyle = dark
          ? `hsla(${p.hue}, 55%, 65%, ${alpha})`
          : `hsla(${p.hue}, 65%, 52%, ${alpha})`;
        ctx.fill();
      }

      // Mouse glow halo
      if (mx >= 0) {
        const grad = ctx.createRadialGradient(mx * w, my * h, 0, mx * w, my * h, w * 0.12);
        grad.addColorStop(0, dark ? 'rgba(82, 174, 255, 0.06)' : 'rgba(49, 141, 255, 0.05)');
        grad.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, w, h);
      }

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafRef.current);
      window.removeEventListener('resize', resize);
      observer?.disconnect();
    };
  }, []);

  // ── Rotate search hints ──
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const timer = setInterval(() => {
      setHintIndex((prev) => (prev + 1) % SEARCH_HINTS.length);
    }, 4000);
    return () => clearInterval(timer);
  }, []);

  // ── Trigger stream on input ──
  const handleSearchChange = useCallback((val: string) => {
    onSearchChange(val);
    if (val.length > 0) {
      setStreamKey((k) => k + 1);
    }
  }, [onSearchChange]);

  const focusTab = useCallback((tab: 'works' | 'dna') => {
    const targetId = tab === 'works' ? WORKS_TAB_ID : DNA_TAB_ID;
    window.requestAnimationFrame(() => document.getElementById(targetId)?.focus());
  }, []);

  const handleTabKeyDown = useCallback((event: KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;

    event.preventDefault();
    const currentIndex = TAB_ORDER.indexOf(activeTab);
    let nextTab: 'works' | 'dna';

    if (event.key === 'Home') {
      nextTab = TAB_ORDER[0];
    } else if (event.key === 'End') {
      nextTab = TAB_ORDER[TAB_ORDER.length - 1];
    } else {
      const direction = event.key === 'ArrowRight' ? 1 : -1;
      nextTab = TAB_ORDER[(currentIndex + direction + TAB_ORDER.length) % TAB_ORDER.length];
    }

    onTabChange(nextTab);
    focusTab(nextTab);
  }, [activeTab, focusTab, onTabChange]);

  return (
    <section
      ref={sectionRef}
      className="relative overflow-hidden border-b border-slate-200/30 bg-gradient-to-b from-slate-100/80 via-slate-50/50 to-slate-50 dark:border-slate-800/30 dark:from-slate-900 dark:via-slate-950/80 dark:to-slate-950"
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      {/* ── Canvas particle field ── */}
      <canvas
        ref={canvasRef}
        className="pointer-events-none absolute inset-0 h-full w-full"
      />

      {/* ── Depth vignette overlay ── */}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-slate-50 via-transparent to-transparent opacity-60 dark:from-slate-950 dark:opacity-80" />

      <div className="relative mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
        {/* Title + subtitle */}
        <div className="text-center hero-fade-up">
          <h1 className="font-display text-2xl font-bold text-slate-800 dark:text-slate-50 sm:text-3xl">
            {t('gallery.heroTitle')}
          </h1>
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
            {t('gallery.heroSubtitle')}
          </p>
        </div>

        {/* ── Borderless search with light-stream ── */}
        <div className="mx-auto mt-7 max-w-lg hero-fade-up hero-delay-1">
          <div className="relative">
            {/* Outer ambient glow when focused */}
            <div
              className={`absolute -inset-px rounded-2xl transition-all duration-500 ${
                searchFocused
                  ? 'opacity-100 shadow-[0_0_20px_rgba(49,141,255,0.12)] dark:shadow-[0_0_20px_rgba(82,174,255,0.08)]'
                  : 'opacity-0'
              }`}
            />

            {/* Top highlight line — simulates glass rim light */}
            <div className="absolute inset-x-4 top-0 h-px bg-gradient-to-r from-transparent via-brand-300/30 to-transparent dark:via-brand-500/20" />

            <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400/70 dark:text-slate-500/70" />

            <input
              type="text"
              value={searchQuery}
              onChange={(e) => handleSearchChange(e.target.value)}
              onFocus={() => setSearchFocused(true)}
              onBlur={() => setSearchFocused(false)}
              placeholder={t('gallery.searchPlaceholder')}
              aria-label={t('gallery.searchAriaLabel')}
              className="min-h-12 w-full rounded-2xl border-0 bg-white/40 py-3 pl-11 pr-10 text-sm text-slate-800 placeholder-slate-400/80 backdrop-blur-md transition-all duration-300 focus:bg-white/60 focus:outline-none focus:ring-0 focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:bg-slate-800/30 dark:text-slate-100 dark:placeholder-slate-500/80 dark:focus:bg-slate-800/50 dark:focus-visible:ring-brand-500 dark:focus-visible:ring-offset-slate-950"
            />

            {/* AI sparkle icon */}
            <Sparkles className={`absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 transition-all duration-300 ${
              searchFocused || searchQuery
                ? 'text-brand-400 dark:text-brand-400'
                : 'text-slate-300 dark:text-slate-600'
            }`} />

            {/* Light-stream under input on typing */}
            {searchQuery && (
              <div className="absolute bottom-0 left-0 right-0 h-px overflow-hidden rounded-full">
                <div
                  key={streamKey}
                  className="gallery-search-stream h-full w-1/3 bg-gradient-to-r from-transparent via-brand-400/60 to-transparent dark:via-brand-400/40"
                />
              </div>
            )}

            {/* Bottom ambient line */}
            <div className="absolute inset-x-6 bottom-0 h-px bg-gradient-to-r from-transparent via-slate-200/40 to-transparent dark:via-slate-700/30" />
          </div>

          {/* Rotating smart hints */}
          {!searchQuery && (
            <div className="mt-3 flex items-center justify-center gap-2 text-[11px] text-slate-500 dark:text-slate-400">
              <span className="select-none opacity-60">{t('gallery.searchTryLabel')}</span>
              <button
                type="button"
                key={hintIndex}
                onClick={() => handleSearchChange(t(`gallery.${SEARCH_HINTS[hintIndex]}`))}
                aria-label={t('gallery.searchHintAriaLabel').replace('{hint}', currentSearchHint)}
                className="gallery-search-hint inline-flex min-h-12 cursor-pointer items-center rounded-full bg-slate-200/30 px-3 py-1 font-medium text-brand-700 backdrop-blur-sm transition-colors hover:bg-brand-50/40 hover:text-brand-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:bg-slate-700/20 dark:text-brand-300 dark:hover:bg-brand-500/10 dark:hover:text-brand-200 dark:focus-visible:ring-brand-500 dark:focus-visible:ring-offset-slate-950"
              >
                {currentSearchHint}
              </button>
            </div>
          )}
        </div>

        {/* ── Capsule physics tab slider ── */}
        <div className="mx-auto mt-6 flex max-w-[260px] justify-center hero-fade-up hero-delay-2">
          <div
            role="tablist"
            aria-label={t('gallery.tabsLabel')}
            onKeyDown={handleTabKeyDown}
            className="relative flex w-full rounded-full bg-slate-200/40 p-[3px] backdrop-blur-sm dark:bg-slate-800/40"
          >
            {/* Sliding indicator */}
            <div
              className="absolute top-[3px] bottom-[3px] rounded-full bg-white shadow-sm border border-slate-200/50 transition-all duration-300 ease-[cubic-bezier(.22,1,.36,1)] dark:bg-slate-700 dark:border-white/10"
              style={{
                left: activeTab === 'works' ? '3px' : '50%',
                width: 'calc(50% - 3px)',
              }}
            />

            <button
              id={WORKS_TAB_ID}
              type="button"
              role="tab"
              aria-selected={activeTab === 'works'}
              aria-controls={RESULTS_PANEL_ID}
              tabIndex={activeTab === 'works' ? 0 : -1}
              onClick={() => onTabChange('works')}
              className={`relative z-10 min-h-11 flex-1 rounded-full py-2 text-[13px] transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-100 dark:focus-visible:ring-brand-500 dark:focus-visible:ring-offset-slate-900 ${
                activeTab === 'works'
                  ? 'font-semibold text-slate-900 dark:text-slate-100'
                  : 'font-medium text-slate-600 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200'
              }`}
            >
              {t('gallery.tabWorks')}
            </button>
            <button
              id={DNA_TAB_ID}
              type="button"
              role="tab"
              aria-selected={activeTab === 'dna'}
              aria-controls={RESULTS_PANEL_ID}
              tabIndex={activeTab === 'dna' ? 0 : -1}
              onClick={() => onTabChange('dna')}
              className={`relative z-10 min-h-11 flex-1 rounded-full py-2 text-[13px] transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-100 dark:focus-visible:ring-brand-500 dark:focus-visible:ring-offset-slate-900 ${
                activeTab === 'dna'
                  ? 'font-semibold text-slate-900 dark:text-slate-100'
                  : 'font-medium text-slate-600 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200'
              }`}
            >
              {t('gallery.tabDna')}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
};
