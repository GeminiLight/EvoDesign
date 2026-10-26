import { useMemo, useRef, useState } from 'react';
import {
  ArrowRight,
  CheckCircle2,
  Network,
  PenLine,
  Sparkles,
  WandSparkles,
} from 'lucide-react';
import { useLanguage } from '../i18n/LanguageProvider';
import { Header } from '../components/Header';
import { DiagramTypeOutline } from '../components/DiagramTypeOutline';
import type { DiagramType } from '../types/api';

interface LandingPageProps {
  onEnterGuest: () => void;
  onGeneratePrompt: (prompt: string, diagramType: DiagramType) => void;
  onEnterEmailAuth: () => void;
}

type HeroPill = {
  id: 'adaptive' | 'flowchart' | 'architecture' | 'sequence';
  labelKey: string;
};

type TemplateCard = {
  id: 'architecture' | 'sequence' | 'flowchart' | 'mindmap';
  labelKey: string;
  titleKey: string;
  promptKey: string;
  pillId: HeroPill['id'];
  tone: 'blue' | 'indigo' | 'emerald' | 'slate';
};

const heroPills: HeroPill[] = [
  { id: 'adaptive', labelKey: 'landing.heroPillAdaptive' },
  { id: 'flowchart', labelKey: 'landing.heroPillFlowchart' },
  { id: 'architecture', labelKey: 'landing.heroPillArchitecture' },
  { id: 'sequence', labelKey: 'landing.heroPillSequence' },
];

const pillPlaceholderKeys: Record<HeroPill['id'], string> = {
  adaptive: 'landing.placeholderAdaptive',
  flowchart: 'landing.placeholderFlowchart',
  architecture: 'landing.placeholderArchitecture',
  sequence: 'landing.placeholderSequence',
};

const heroDiagramTypes: Record<HeroPill['id'], DiagramType> = {
  adaptive: 'automated',
  flowchart: 'flow',
  architecture: 'architecture',
  sequence: 'sequence',
};

const heroFallbackPromptKeys: Record<HeroPill['id'], string> = {
  adaptive: 'landing.exampleAdaptive',
  flowchart: 'landing.exampleFlowchart',
  architecture: 'landing.exampleArchitecture',
  sequence: 'landing.exampleSequence',
};

const templateCards: TemplateCard[] = [
  {
    id: 'architecture',
    labelKey: 'home.pillArchitectureLabel',
    titleKey: 'home.sampleMicroservice',
    promptKey: 'landing.exampleArchitecture',
    pillId: 'architecture',
    tone: 'blue',
  },
  {
    id: 'sequence',
    labelKey: 'home.pillSequenceLabel',
    titleKey: 'landing.exampleSequence',
    promptKey: 'landing.exampleSequence',
    pillId: 'sequence',
    tone: 'indigo',
  },
  {
    id: 'flowchart',
    labelKey: 'home.pillFlowLabel',
    titleKey: 'home.sampleTraining',
    promptKey: 'landing.exampleFlowchart',
    pillId: 'flowchart',
    tone: 'emerald',
  },
  {
    id: 'mindmap',
    labelKey: 'home.pillMindMapLabel',
    titleKey: 'home.sampleBrowser',
    promptKey: 'landing.exampleAdaptive',
    pillId: 'adaptive',
    tone: 'slate',
  },
];

const workflowSteps = [
  { key: 'landing.workflowExtract', icon: PenLine },
  { key: 'landing.workflowIntent', icon: WandSparkles },
  { key: 'landing.workflowLayout', icon: Network },
  { key: 'landing.workflowRefine', icon: CheckCircle2 },
];

const outlineToneClasses: Record<TemplateCard['tone'], string> = {
  blue: 'text-brand-400 dark:text-brand-500',
  indigo: 'text-indigo-400 dark:text-indigo-500',
  emerald: 'text-emerald-400 dark:text-emerald-500',
  slate: 'text-slate-500 dark:text-slate-400',
};

const toneClasses: Record<TemplateCard['tone'], string> = {
  blue: 'border-brand-200 bg-brand-50/70 text-brand-700 dark:border-brand-500/30 dark:bg-brand-500/10 dark:text-brand-200',
  indigo: 'border-indigo-200 bg-indigo-50/70 text-indigo-700 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-200',
  emerald: 'border-emerald-200 bg-emerald-50/70 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200',
  slate: 'border-slate-200 bg-slate-100/80 text-slate-700 dark:border-slate-600/50 dark:bg-slate-800/80 dark:text-slate-200',
};

export const LandingPage = ({ onEnterGuest, onGeneratePrompt, onEnterEmailAuth }: LandingPageProps) => {
  const { t } = useLanguage();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [activePill, setActivePill] = useState<HeroPill['id']>('adaptive');
  const [textareaValue, setTextareaValue] = useState('');

  const heroPrompt = useMemo(() => t(pillPlaceholderKeys[activePill]), [t, activePill]);
  const selectedDiagramType = heroDiagramTypes[activePill];
  const promptLength = textareaValue.length;

  const handleGenerateFromHero = () => {
    const prompt = textareaValue.trim() || t(heroFallbackPromptKeys[activePill]);
    onGeneratePrompt(prompt, selectedDiagramType);
  };

  const handleUseTemplate = (template: TemplateCard) => {
    setActivePill(template.pillId);
    setTextareaValue(t(template.promptKey));
    window.requestAnimationFrame(() => textareaRef.current?.focus());
  };

  return (
    <div className="min-h-screen overflow-x-hidden bg-slate-50 text-slate-900 transition-colors duration-300 selection:bg-brand-500/25 dark:bg-[#050914] dark:text-slate-100">
      <section id="main-content" className="relative overflow-hidden border-b border-slate-200/70 dark:border-white/10">
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(rgba(49,141,255,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(49,141,255,0.08)_1px,transparent_1px)] bg-[size:64px_64px] opacity-60 dark:opacity-25" />
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(980px_520px_at_8%_8%,rgba(82,174,255,0.18),transparent_60%),radial-gradient(860px_520px_at_94%_16%,rgba(20,184,166,0.12),transparent_62%)] dark:bg-[radial-gradient(980px_520px_at_8%_8%,rgba(49,141,255,0.18),transparent_60%),radial-gradient(860px_520px_at_94%_16%,rgba(20,184,166,0.12),transparent_62%)]" />

        <Header variant="landing" onEnterGuest={onEnterGuest} onEnterEmailAuth={onEnterEmailAuth} />

        <div className="relative z-10 mx-auto flex max-w-7xl flex-col items-center px-4 pb-10 pt-8 text-center sm:px-6 lg:min-h-[calc(100dvh-4rem)] lg:px-8 lg:pb-14 lg:pt-12">
          <div className="w-full max-w-4xl">
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-brand-200 bg-white/80 px-3 py-1.5 text-xs font-semibold tracking-[0.18em] text-brand-700 shadow-sm backdrop-blur dark:border-brand-500/30 dark:bg-slate-950/75 dark:text-brand-200 sm:mb-5">
              <span className="h-2 w-2 rounded-full bg-brand-500" />
              {t('landing.heroEyebrow')}
            </div>

            <h1 className="mx-auto max-w-4xl font-display text-[2.5rem] font-extrabold leading-[0.98] tracking-tight text-slate-950 dark:text-white sm:text-6xl lg:text-7xl">
              {t('landing.heroTitle1')}
              <span className="block text-brand-600 dark:text-brand-300">{t('landing.heroTitle2')}</span>
            </h1>

            <p className="mx-auto mt-4 max-w-2xl text-base leading-7 text-slate-600 dark:text-slate-300 sm:mt-5 sm:text-lg">
              {t('landing.heroSubheadline')}
            </p>

            <div className="mx-auto mt-6 max-w-3xl rounded-[1.75rem] border border-white/80 bg-white/88 p-2 text-left shadow-[0_24px_70px_rgba(49,93,130,0.18)] backdrop-blur-2xl dark:border-white/10 dark:bg-slate-950/80 dark:shadow-[0_24px_70px_rgba(0,0,0,0.42)] sm:mt-8 sm:p-3">
              <div className="mb-3 flex flex-wrap items-center gap-2" role="radiogroup" aria-label={t('landing.heroPillsLabel')}>
                {heroPills.map((pill) => {
                  const isActive = pill.id === activePill;
                  return (
                    <button
                      key={pill.id}
                      type="button"
                      onClick={() => setActivePill(pill.id)}
                      aria-pressed={isActive}
                      className={`tap-target min-h-9 rounded-full px-3 text-sm font-semibold transition-all focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-offset-slate-950 sm:min-h-10 sm:px-4 ${
                        isActive
                          ? 'bg-brand-600 text-white shadow-[0_10px_24px_rgba(49,141,255,0.24)]'
                          : 'bg-slate-100 text-slate-600 hover:bg-brand-50 hover:text-brand-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-brand-500/15 dark:hover:text-brand-200'
                      }`}
                    >
                      {t(pill.labelKey)}
                    </button>
                  );
                })}
              </div>

              <div className="rounded-[1.25rem] border border-slate-200 bg-slate-50/80 dark:border-slate-800 dark:bg-slate-900/80">
                <textarea
                  ref={textareaRef}
                  maxLength={2000}
                  className="min-h-[92px] w-full resize-none border-none bg-transparent px-4 py-4 text-base leading-7 text-slate-800 placeholder:text-slate-400 focus:ring-0 dark:text-slate-100 dark:placeholder:text-slate-500 sm:min-h-[132px]"
                  placeholder={heroPrompt}
                  value={textareaValue}
                  onChange={(event) => setTextareaValue(event.target.value)}
                  aria-label={t('landing.heroPromptPlaceholder')}
                />
                <div className="flex flex-col gap-3 border-t border-slate-200 px-4 py-3 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-2 text-xs font-medium text-slate-500 dark:text-slate-400">
                    <Sparkles className="h-4 w-4 text-brand-500" />
                    <span>{t(`landing.pillDesc${activePill.charAt(0).toUpperCase() + activePill.slice(1)}`)}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3 sm:justify-end">
                    <span className="font-mono text-xs text-slate-500 dark:text-slate-400">{promptLength}/2000</span>
                    <button
                      type="button"
                      onClick={handleGenerateFromHero}
                      className="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-xl bg-brand-600 px-5 text-sm font-bold text-white shadow-[0_12px_28px_rgba(49,141,255,0.26)] transition-all hover:-translate-y-0.5 hover:bg-brand-500 active:translate-y-0 focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-50 dark:focus-visible:ring-offset-slate-950"
                    >
                      {t('landing.heroGenerateNow')}
                      <ArrowRight className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-8 w-full max-w-5xl sm:mt-10">
            <div className="rounded-[2rem] border border-white/80 bg-white/82 p-4 shadow-[0_28px_90px_rgba(49,93,130,0.18)] backdrop-blur-2xl dark:border-white/10 dark:bg-slate-950/78 dark:shadow-[0_28px_90px_rgba(0,0,0,0.48)]">
              <div className="flex items-center justify-between border-b border-slate-200/75 pb-3 dark:border-slate-800">
                <div>
                  <p className="text-left text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{t('landing.previewRealtime')}</p>
                  <p className="mt-1 text-left text-sm font-semibold text-slate-800 dark:text-slate-100">{t('landing.agentPowerTitle')}</p>
                </div>
                <div className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-200 dark:ring-emerald-500/25">
                  <span className="h-2 w-2 rounded-full bg-emerald-500" />
                  {t('landing.previewActive')}
                </div>
              </div>

              <div className="grid gap-4 pt-4 lg:grid-cols-[minmax(0,1fr)_12rem]">
                <div className="min-h-[21rem] rounded-[1.5rem] border border-slate-200 bg-slate-950 p-4 text-white shadow-inner dark:border-slate-800">
                  <ArchitecturePreview />
                </div>
                <div className="flex flex-col gap-3">
                  {workflowSteps.map((step, index) => {
                    const Icon = step.icon;
                    return (
                      <div key={step.key} className="rounded-2xl border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900">
                        <div className="flex items-center gap-2">
                          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-200">
                            <Icon className="h-4 w-4" />
                          </span>
                          <span className="font-mono text-[11px] text-slate-400">0{index + 1}</span>
                        </div>
                        <p className="mt-2 text-sm font-semibold text-slate-800 dark:text-slate-100">{t(step.key)}</p>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="relative z-10 border-b border-slate-200/70 bg-white/82 py-12 backdrop-blur dark:border-white/10 dark:bg-slate-950/72 sm:py-14">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="mb-8 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="font-display text-2xl font-bold tracking-tight text-slate-950 dark:text-white sm:text-3xl">{t('landing.templateTitle')}</h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">{t('landing.templateSubtitle')}</p>
            </div>
            <button
              type="button"
              onClick={onEnterGuest}
              className="inline-flex min-h-11 items-center gap-2 self-start rounded-xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-700 transition hover:border-brand-300 hover:text-brand-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-brand-500"
            >
              {t('landing.templateBrowseAll')}
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {templateCards.map((template) => (
              <article
                key={template.id}
                className="group flex min-h-[19rem] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm transition-all hover:-translate-y-1 hover:border-brand-300 hover:shadow-[0_20px_44px_rgba(49,93,130,0.14)] dark:border-slate-800 dark:bg-slate-900 dark:hover:border-brand-500/60"
              >
                <div className={`border-b px-4 py-3 text-xs font-bold ${toneClasses[template.tone]}`}>
                  {t(template.labelKey)}
                </div>
                <div className={`h-32 border-b border-slate-100 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950 ${outlineToneClasses[template.tone]}`}>
                  <DiagramTypeOutline kind={template.id} />
                </div>
                <div className="flex flex-1 flex-col p-4">
                  <h3 className="line-clamp-3 text-sm font-semibold leading-6 text-slate-900 dark:text-slate-100">{t(template.titleKey)}</h3>
                  <button
                    type="button"
                    onClick={() => handleUseTemplate(template)}
                    className="mt-auto inline-flex min-h-10 items-center justify-between rounded-xl bg-slate-100 px-3 text-sm font-semibold text-slate-700 transition hover:bg-brand-50 hover:text-brand-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-brand-500/15 dark:hover:text-brand-200"
                  >
                    {t('landing.templateUse')}
                    <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                  </button>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-slate-50 py-16 dark:bg-[#050914] sm:py-20">
        <div className="mx-auto grid max-w-7xl gap-10 px-4 sm:px-6 lg:grid-cols-[0.85fr_1.15fr] lg:px-8">
          <div>
            <h2 className="font-display text-3xl font-bold tracking-tight text-slate-950 dark:text-white sm:text-4xl">{t('landing.creationTitle')}</h2>
            <p className="mt-4 max-w-xl text-base leading-7 text-slate-600 dark:text-slate-300">{t('landing.creationDesc')}</p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            {workflowSteps.map((step, index) => {
              const Icon = step.icon;
              return (
                <article key={step.key} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
                  <div className="mb-5 flex items-center justify-between">
                    <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-200">
                      <Icon className="h-5 w-5" />
                    </span>
                    <span className="font-mono text-xs font-semibold text-slate-500 dark:text-slate-400">STEP {index + 1}</span>
                  </div>
                  <h3 className="text-lg font-bold text-slate-900 dark:text-white">{t(step.key)}</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{t(`landing.workflowStepDesc${index + 1}`)}</p>
                </article>
              );
            })}
          </div>
        </div>
      </section>

      <section className="border-t border-slate-200 bg-white py-14 dark:border-white/10 dark:bg-slate-950 sm:py-16">
        <div className="mx-auto flex max-w-5xl flex-col items-start gap-6 px-4 sm:px-6 md:flex-row md:items-center md:justify-between lg:px-8">
          <div>
            <h2 className="font-display text-3xl font-bold tracking-tight text-slate-950 dark:text-white">{t('landing.ctaTitle')}</h2>
            <p className="mt-2 max-w-2xl text-base text-slate-600 dark:text-slate-300">{t('landing.ctaDesc')}</p>
          </div>
          <button
            type="button"
            onClick={onEnterGuest}
            className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-brand-600 px-6 text-base font-bold text-white shadow-[0_14px_30px_rgba(49,141,255,0.24)] transition hover:-translate-y-0.5 hover:bg-brand-500 active:translate-y-0 focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-offset-slate-950"
          >
            {t('landing.ctaButton')}
            <ArrowRight className="h-5 w-5" />
          </button>
        </div>
      </section>
    </div>
  );
};

function ArchitecturePreview() {
  return (
    <svg viewBox="0 0 520 360" className="h-full w-full" fill="none" role="img" aria-label="Generated architecture diagram preview">
      <defs>
        <linearGradient id="previewNode" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor="#52aeff" stopOpacity="0.22" />
          <stop offset="1" stopColor="#14b8a6" stopOpacity="0.16" />
        </linearGradient>
        <marker id="previewArrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto">
          <path d="M0,0 L0,6 L9,3 z" fill="#7dd3fc" />
        </marker>
      </defs>
      <rect x="1" y="1" width="518" height="358" rx="24" fill="#07111f" stroke="#1e3a5f" />
      <path d="M44 82H476M44 180H476M44 278H476" stroke="#1e3a5f" strokeDasharray="6 8" />
      <text x="44" y="44" fill="#dbeafe" fontSize="18" fontWeight="700">Browser agent system</text>
      <text x="44" y="64" fill="#7dd3fc" fontSize="11" fontFamily="monospace">structure + layout + refinement</text>

      <rect x="50" y="104" width="112" height="52" rx="14" fill="url(#previewNode)" stroke="#52aeff" />
      <text x="106" y="126" textAnchor="middle" fill="#e0f2fe" fontSize="12" fontWeight="700">Planner</text>
      <text x="106" y="144" textAnchor="middle" fill="#93c5fd" fontSize="10">task graph</text>

      <rect x="204" y="104" width="112" height="52" rx="14" fill="#2563eb" fillOpacity="0.14" stroke="#60a5fa" />
      <text x="260" y="126" textAnchor="middle" fill="#e0f2fe" fontSize="12" fontWeight="700">Executor</text>
      <text x="260" y="144" textAnchor="middle" fill="#93c5fd" fontSize="10">browser tools</text>

      <rect x="358" y="104" width="112" height="52" rx="14" fill="#0f766e" fillOpacity="0.18" stroke="#2dd4bf" />
      <text x="414" y="126" textAnchor="middle" fill="#ecfeff" fontSize="12" fontWeight="700">Reviewer</text>
      <text x="414" y="144" textAnchor="middle" fill="#99f6e4" fontSize="10">quality gate</text>

      <rect x="128" y="216" width="120" height="52" rx="14" fill="#111827" stroke="#64748b" />
      <text x="188" y="238" textAnchor="middle" fill="#e2e8f0" fontSize="12" fontWeight="700">Memory</text>
      <text x="188" y="256" textAnchor="middle" fill="#94a3b8" fontSize="10">project DNA</text>

      <rect x="284" y="216" width="120" height="52" rx="14" fill="#1e3a8a" fillOpacity="0.24" stroke="#3b82f6" />
      <text x="344" y="238" textAnchor="middle" fill="#e0f2fe" fontSize="12" fontWeight="700">Approval</text>
      <text x="344" y="256" textAnchor="middle" fill="#93c5fd" fontSize="10">human control</text>

      <path d="M162 130H204" stroke="#7dd3fc" strokeWidth="2" markerEnd="url(#previewArrow)" />
      <path d="M316 130H358" stroke="#7dd3fc" strokeWidth="2" markerEnd="url(#previewArrow)" />
      <path d="M260 156C260 190 220 188 188 216" stroke="#7dd3fc" strokeWidth="2" markerEnd="url(#previewArrow)" />
      <path d="M414 156C414 190 380 190 344 216" stroke="#5eead4" strokeWidth="2" markerEnd="url(#previewArrow)" />
      <path d="M248 242H284" stroke="#7dd3fc" strokeWidth="2" strokeDasharray="6 6" markerEnd="url(#previewArrow)" />
      <path d="M344 216C330 178 298 158 274 154" stroke="#60a5fa" strokeWidth="2" strokeDasharray="5 7" markerEnd="url(#previewArrow)" />
    </svg>
  );
}
