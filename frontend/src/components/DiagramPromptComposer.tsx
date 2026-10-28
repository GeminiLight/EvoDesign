import { BROWSER_MODE } from '../services/browser/runtime';
import { shouldSubmitOnEnter } from '../utils/keyboard';
import {
  Activity,
  ArrowRight,
  X,
  BarChart3,
  Bot,
  Box,
  Brain,
  Check,
  ChevronDown,
  Clock3,
  Database,
  GitBranch,
  Loader2,
  Network,
  Paperclip,
  SendHorizontal,
  Settings,
  Sparkles,
  SquarePen,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { GenerationProgress } from '../types/app';
import { StageProgress } from './StageProgress';

export type PromptPill = {
  id: string;
  label: string;
  prefix: string;
  icon: string;
};

export type PromptOption = {
  id: string;
  label: string;
};

const pillIconMap: Record<string, LucideIcon> = {
  adaptive: Sparkles,
  flow: GitBranch,
  architecture: Network,
  sequence: Clock3,
  mindmap: Brain,
  entity: Database,
  state: Activity,
  gantt: BarChart3,
  class: Box,
};

const getPillIcon = (id: string) => pillIconMap[id] ?? Network;

type Props = {
  prompt: string;
  onPromptChange: (value: string) => void;
  onGenerate: () => void;
  onEnhance: () => void;
  onSelectPill: (pill: PromptPill) => void;
  selectedPillId: string;
  pills: PromptPill[];
  morePills: PromptPill[];
  modelOptions: PromptOption[];
  modelIndex: number;
  onModelChange: (index: number) => void;
  canvasOptions: PromptOption[];
  canvasIndex: number;
  onCanvasChange: (index: number) => void;
  attachTitle: string;
  enhanceTitle: string;
  generateTitle: string;
  actionLabel?: string;
  variant?: 'default' | 'dialog' | 'home';
  leadingContent?: ReactNode;
  moreLabel: string;
  onAttachmentClick?: () => void;
  attachedFileName?: string | null;
  onRemoveAttachment?: () => void;
  disableGenerate?: boolean;
  isGenerating?: boolean;
  isDisabled?: boolean;
  progress?: GenerationProgress | null;
  t?: (key: string) => string;
  autoFocusPrompt?: boolean;
  promptFocusRequest?: number;
};

export function DiagramPromptComposer({
  prompt,
  onPromptChange,
  onGenerate,
  onEnhance,
  onSelectPill,
  selectedPillId,
  pills,
  morePills,
  modelOptions,
  modelIndex,
  onModelChange,
  canvasOptions,
  canvasIndex,
  onCanvasChange,
  attachTitle,
  enhanceTitle,
  generateTitle,
  actionLabel,
  variant = 'default',
  leadingContent,
  moreLabel,
  onAttachmentClick,
  attachedFileName,
  onRemoveAttachment,
  disableGenerate = false,
  isGenerating = false,
  isDisabled = false,
  progress,
  t,
  autoFocusPrompt = false,
  promptFocusRequest = 0,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const modelMenuRef = useRef<HTMLDivElement>(null);
  const canvasMenuRef = useRef<HTMLDivElement>(null);
  const modelTriggerRef = useRef<HTMLButtonElement>(null);
  const canvasTriggerRef = useRef<HTMLButtonElement>(null);
  const modelOptionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const canvasOptionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [canvasMenuOpen, setCanvasMenuOpen] = useState(false);
  const [showMorePills, setShowMorePills] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const currentModel = modelOptions[modelIndex] ?? modelOptions[0];
  const currentCanvas = canvasOptions[canvasIndex] ?? canvasOptions[0];
  const canAttach = Boolean(onAttachmentClick);
  const controlsDisabled = isGenerating || isDisabled;
  const focusRingClass = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-brand-500 dark:focus-visible:ring-offset-slate-900';
  const menuOptionClass = `flex min-h-11 w-full items-center justify-between rounded-lg px-3 py-2 text-sm transition-colors ${focusRingClass}`;
  const menuSurfaceClass = 'absolute bottom-12 left-1/2 z-20 max-h-[calc(100dvh-8rem)] max-w-[calc(100vw-2rem)] -translate-x-1/2 overflow-y-auto overscroll-contain surface-overlay rounded-xl p-2 shadow-e4 dark:shadow-e4-dark';
  const disabledControlClass = 'disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-slate-200 disabled:hover:bg-slate-100 disabled:hover:text-slate-600 dark:disabled:hover:border-slate-700 dark:disabled:hover:bg-slate-800/95 dark:disabled:hover:text-slate-300';
  const morePillsRegionId = 'diagram-prompt-more-pills';
  const advancedControlsId = 'diagram-prompt-advanced-controls';
  const modelListboxId = 'diagram-prompt-model-listbox';
  const canvasListboxId = 'diagram-prompt-canvas-listbox';

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = '0px';
    const nextHeight = Math.max(variant === 'home' ? 108 : 132, Math.min(textarea.scrollHeight, 240));
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > 240 ? 'auto' : 'hidden';
  }, [prompt, variant]);

  useEffect(() => {
    if (!autoFocusPrompt && !promptFocusRequest) return;
    const textarea = textareaRef.current;
    if (!textarea) return;

    const frameId = window.requestAnimationFrame(() => {
      textarea.focus({ preventScroll: promptFocusRequest > 0 });
      if (promptFocusRequest) textarea.scrollIntoView({ block: 'center',
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [autoFocusPrompt, promptFocusRequest]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (modelMenuRef.current && !modelMenuRef.current.contains(event.target as Node)) {
        setModelMenuOpen(false);
      }
      if (canvasMenuRef.current && !canvasMenuRef.current.contains(event.target as Node)) {
        setCanvasMenuOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    if (!controlsDisabled) return;
    setModelMenuOpen(false);
    setCanvasMenuOpen(false);
    setShowAdvanced(false);
  }, [controlsDisabled]);

  useEffect(() => {
    if (!modelMenuOpen) return;
    const frameId = window.requestAnimationFrame(() => {
      modelOptionRefs.current[modelIndex]?.focus();
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [modelIndex, modelMenuOpen]);

  useEffect(() => {
    if (!canvasMenuOpen) return;
    const frameId = window.requestAnimationFrame(() => {
      canvasOptionRefs.current[canvasIndex]?.focus();
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [canvasIndex, canvasMenuOpen]);

  const focusOptionAtIndex = (
    refs: React.MutableRefObject<Array<HTMLButtonElement | null>>,
    index: number,
  ) => {
    refs.current[index]?.focus();
  };

  const handleOptionKeyDown = (
    event: React.KeyboardEvent<HTMLButtonElement>,
    index: number,
    count: number,
    refs: React.MutableRefObject<Array<HTMLButtonElement | null>>,
    closeMenu: () => void,
    triggerRef: React.RefObject<HTMLButtonElement | null>,
  ) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      focusOptionAtIndex(refs, (index + 1) % count);
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      focusOptionAtIndex(refs, (index - 1 + count) % count);
      return;
    }

    if (event.key === 'Home') {
      event.preventDefault();
      focusOptionAtIndex(refs, 0);
      return;
    }

    if (event.key === 'End') {
      event.preventDefault();
      focusOptionAtIndex(refs, count - 1);
      return;
    }

    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      closeMenu();
      triggerRef.current?.focus();
    }
  };

  const handleTriggerKeyDown = (
    event: React.KeyboardEvent<HTMLButtonElement>,
    openMenu: () => void,
  ) => {
    if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      openMenu();
    }

    if (event.key === 'Escape' && (modelMenuOpen || canvasMenuOpen)) {
      event.preventDefault();
      event.stopPropagation();
      setModelMenuOpen(false);
      setCanvasMenuOpen(false);
    }
  };

  return (
    <>
      <div className={`w-full relative group ${variant === 'home' ? 'home-composer' : ''}`} aria-busy={isGenerating}>
        <div className="diagram-prompt-surface relative flex flex-col rounded-2xl border border-slate-200/80 bg-white shadow-e2 transition-colors dark:border-slate-700 dark:bg-slate-900 dark:shadow-e2-dark">
          <div className="relative flex-1">
            {variant !== 'home' && <button
              type="button"
              title={enhanceTitle}
              aria-label={enhanceTitle}
              onClick={onEnhance}
              disabled={!prompt.trim() || disableGenerate || controlsDisabled}
              className={`tap-target absolute right-3 top-3 z-10 flex h-9 w-9 items-center justify-center rounded-full border border-slate-200 bg-white/90 text-slate-600 backdrop-blur transition-colors hover:border-brand-300 hover:text-brand-600 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900/85 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300 ${focusRingClass}`}
            >
              <Sparkles className="h-4 w-4" />
            </button>}

            <textarea
              ref={textareaRef}
              value={prompt}
              onChange={(event) => onPromptChange(event.target.value)}
              disabled={controlsDisabled}
              placeholder={t?.('home.promptPlaceholder') || 'Describe your diagram...'}
              aria-label={t?.('home.promptPlaceholder') || 'Describe your diagram...'}
              className="diagram-prompt-input w-full resize-none border-none bg-transparent px-6 pb-2 pr-20 pt-6 text-lg text-slate-800 outline-none transition disabled:cursor-not-allowed disabled:text-slate-500 disabled:placeholder:text-slate-400 focus:ring-0 dark:text-slate-100 dark:disabled:text-slate-500 dark:placeholder:text-slate-500"
              onKeyDown={(event) => {
                if (shouldSubmitOnEnter(event)) {
                  event.preventDefault();
                  if (!disableGenerate && !controlsDisabled && prompt.trim()) {
                    onGenerate();
                  }
                }
              }}
            />
          </div>

          {attachedFileName && (
            <div className="home-reference-chip" role="status">
              <Paperclip size={13} aria-hidden="true" /><span title={attachedFileName}>{attachedFileName}</span>
              {onRemoveAttachment && <button type="button" onClick={onRemoveAttachment} disabled={controlsDisabled} aria-label={t?.('home.removeReference') || 'Remove reference'}><X size={14} /></button>}
            </div>
          )}

          <div className="diagram-prompt-footer flex flex-col gap-2 border-t border-slate-100 px-3 py-3 dark:border-slate-800 sm:flex-row sm:items-center sm:py-2">
            {leadingContent && <div className={`diagram-prompt-leading min-w-0 flex-1 ${variant === 'home' ? 'home-composer-model' : ''}`}>{leadingContent}</div>}
            {/* The attach control is only rendered when it can actually do
                something. Showing a permanently disabled button plus a
                "coming soon" caption spent the most valuable row in the app on
                a feature that does not exist yet. */}
            {canAttach && (
              <div className="diagram-prompt-attach flex min-w-0 items-center gap-2 sm:w-auto">
                <button
                  type="button"
                  title={attachTitle}
                  aria-label={attachTitle}
                  onClick={onAttachmentClick}
                  disabled={controlsDisabled}
                  className={`tap-target flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-white/80 text-slate-600 transition-colors hover:border-brand-300 hover:text-brand-600 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300 ${focusRingClass}`}
                >
                  <Paperclip className="h-4.5 w-4.5" />{variant === 'home' && <span>{t?.('home.addReference') || 'Add reference'}</span>}
                </button>
              </div>
            )}

            <div className="diagram-prompt-actions flex w-full min-w-0 flex-wrap items-center justify-end gap-2 sm:ml-auto sm:w-auto">
            {variant === 'default' && <button
              type="button"
              disabled={controlsDisabled}
              onClick={() => setShowAdvanced((prev) => !prev)}
              aria-label={t?.('home.advancedSettings') || 'Model & canvas settings'}
              title={t?.('home.advancedSettings') || 'Model & canvas settings'}
              aria-expanded={showAdvanced}
              aria-pressed={showAdvanced}
              aria-controls={advancedControlsId}
              className={`tap-target flex h-9 w-9 shrink-0 items-center justify-center rounded-full border ring-1 transition-colors ${disabledControlClass} ${focusRingClass} ${showAdvanced ? 'border-brand-300 bg-brand-50 text-brand-600 ring-brand-200 dark:border-brand-500 dark:bg-brand-500/20 dark:text-brand-300 dark:ring-brand-500/40' : 'border-slate-200 bg-slate-100 text-slate-600 ring-slate-200 hover:border-brand-300 hover:text-brand-600 dark:border-slate-700 dark:bg-slate-800/95 dark:text-slate-300 dark:ring-slate-700 dark:hover:border-brand-500 dark:hover:text-brand-300'}`}
            >
              <Settings className="h-4 w-4" />
            </button>}

            {(showAdvanced || variant === 'dialog') && (
              <div id={advancedControlsId} className="contents">
                <div className="relative" ref={modelMenuRef}>
                  <button
                    ref={modelTriggerRef}
                    type="button"
                    disabled={controlsDisabled || modelOptions.length <= 1}
                    title={modelOptions.length <= 1 ? t?.(BROWSER_MODE ? 'browser.modelHint' : 'home.serverModelHint') : undefined}
                    onClick={() => {
                      setModelMenuOpen((prev) => !prev);
                      setCanvasMenuOpen(false);
                    }}
                    onKeyDown={(event) => handleTriggerKeyDown(event, () => {
                      setModelMenuOpen(true);
                      setCanvasMenuOpen(false);
                    })}
                    aria-expanded={modelMenuOpen}
                    aria-haspopup="listbox"
                    aria-controls={modelListboxId}
                    className={`tap-target inline-flex h-9 max-w-[12rem] items-center gap-1.5 rounded-full border bg-slate-100 px-3 text-sm font-semibold text-slate-700 ring-1 ring-slate-200 transition-colors hover:border-brand-300 hover:text-brand-600 dark:bg-slate-800/95 dark:text-slate-200 dark:ring-slate-700 dark:hover:border-brand-500 dark:hover:text-brand-300 ${disabledControlClass} ${focusRingClass} ${modelMenuOpen ? 'border-brand-300 text-brand-600 dark:border-brand-500 dark:text-brand-300' : 'border-slate-200 dark:border-slate-700'}`}
                  >
                    <Bot className="h-4 w-4" />
                    <span className="truncate">{currentModel?.label}</span>
                  </button>

                  {modelMenuOpen && (
                    <div id={modelListboxId} role="listbox" aria-label={t?.('home.modelIconTitle') || 'Model'} className={`${menuSurfaceClass} w-56`}>
                      {modelOptions.map((model, index) => (
                        <button
                          key={model.id}
                          ref={(node) => {
                            modelOptionRefs.current[index] = node;
                          }}
                          type="button"
                          role="option"
                          aria-selected={index === modelIndex}
                          tabIndex={index === modelIndex ? 0 : -1}
                          onClick={() => {
                            onModelChange(index);
                            setModelMenuOpen(false);
                            modelTriggerRef.current?.focus();
                          }}
                          onKeyDown={(event) => handleOptionKeyDown(
                            event,
                            index,
                            modelOptions.length,
                            modelOptionRefs,
                            () => setModelMenuOpen(false),
                            modelTriggerRef,
                          )}
                          className={`${menuOptionClass} ${index === modelIndex ? 'bg-brand-50 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300' : 'text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800'}`}
                        >
                          <span>{model.label}</span>
                          {index === modelIndex && <Check className="h-4 w-4" />}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                <div className="relative" ref={canvasMenuRef}>
                  <button
                    ref={canvasTriggerRef}
                    type="button"
                    disabled={controlsDisabled}
                    onClick={() => {
                      setCanvasMenuOpen((prev) => !prev);
                      setModelMenuOpen(false);
                    }}
                    onKeyDown={(event) => handleTriggerKeyDown(event, () => {
                      setCanvasMenuOpen(true);
                      setModelMenuOpen(false);
                    })}
                    aria-expanded={canvasMenuOpen}
                    aria-haspopup="listbox"
                    aria-controls={canvasListboxId}
                    className={`tap-target inline-flex h-9 items-center gap-1.5 rounded-full border bg-slate-100 px-3 text-sm font-semibold text-slate-700 ring-1 ring-slate-200 transition-colors hover:border-brand-300 hover:text-brand-600 dark:bg-slate-800/95 dark:text-slate-200 dark:ring-slate-700 dark:hover:border-brand-500 dark:hover:text-brand-300 ${disabledControlClass} ${focusRingClass} ${canvasMenuOpen ? 'border-brand-300 text-brand-600 dark:border-brand-500 dark:text-brand-300' : 'border-slate-200 dark:border-slate-700'}`}
                  >
                    <SquarePen className="h-4 w-4" />
                    {currentCanvas?.label}
                  </button>

                  {canvasMenuOpen && (
                    <div id={canvasListboxId} role="listbox" aria-label={t?.('home.canvasIconTitle') || 'Canvas'} className={`${menuSurfaceClass} w-44`}>
                      {canvasOptions.map((canvas, index) => (
                        <button
                          key={canvas.id}
                          ref={(node) => {
                            canvasOptionRefs.current[index] = node;
                          }}
                          type="button"
                          role="option"
                          aria-selected={index === canvasIndex}
                          tabIndex={index === canvasIndex ? 0 : -1}
                          onClick={() => {
                            onCanvasChange(index);
                            setCanvasMenuOpen(false);
                            canvasTriggerRef.current?.focus();
                          }}
                          onKeyDown={(event) => handleOptionKeyDown(
                            event,
                            index,
                            canvasOptions.length,
                            canvasOptionRefs,
                            () => setCanvasMenuOpen(false),
                            canvasTriggerRef,
                          )}
                          className={`${menuOptionClass} ${index === canvasIndex ? 'bg-brand-50 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300' : 'text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800'}`}
                        >
                          <span>{canvas.label}</span>
                          {index === canvasIndex && <Check className="h-4 w-4" />}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {variant !== 'dialog' && <button
              type="button"
              onClick={onGenerate}
              disabled={!prompt.trim() || disableGenerate || controlsDisabled}
              title={generateTitle}
              aria-label={generateTitle}
              aria-busy={isGenerating}
              className={`tap-target flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-xl px-4 text-sm font-semibold shadow-e1 transition-all hover:-translate-y-px active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0 ${focusRingClass} ${isGenerating ? 'bg-amber-500 text-white' : 'bg-brand-600 text-white hover:bg-brand-500'}`}
            >
              {isGenerating ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                variant === 'home' ? <ArrowRight className="h-5 w-5" /> : <><span>{actionLabel ?? generateTitle}</span><SendHorizontal className="h-4 w-4" /></>
              )}
            </button>}
          </div>
          </div>
        </div>
      </div>

      {isGenerating && progress && t && (
        <div className="mt-4 flex justify-center" role="status" aria-live="polite">
          <div className="inline-flex items-center gap-3 rounded-full border border-slate-200 bg-white/90 px-4 py-2 shadow-sm backdrop-blur-sm dark:border-slate-700 dark:bg-slate-900/90">
            <StageProgress progress={progress} t={t} />
          </div>
        </div>
      )}

      {variant !== 'home' && <div className="flex flex-col items-center mt-6">
        <div className="flex flex-wrap justify-center gap-3">
          {pills.map((pill) => (
            <button
              type="button"
              disabled={controlsDisabled}
              key={pill.id}
              onClick={() => onSelectPill(pill)}
              aria-pressed={selectedPillId === pill.id}
              className={`flex min-h-11 items-center gap-2 rounded-full border px-4 py-2.5 text-sm font-medium transition-all shadow-sm disabled:cursor-not-allowed disabled:opacity-50 ${focusRingClass} ${selectedPillId === pill.id ? 'border-brand-300 bg-brand-50 text-brand-700 dark:border-brand-500 dark:bg-brand-500/20 dark:text-brand-300' : 'border-slate-200 bg-white text-slate-600 hover:border-brand-300 hover:bg-brand-50 hover:text-brand-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:bg-brand-500/20 dark:hover:text-brand-300'}`}
            >
              {(() => {
                const Icon = getPillIcon(pill.id);
                return <Icon className="h-4 w-4 shrink-0" />;
              })()}
              {pill.label}
            </button>
          ))}
          <button
            type="button"
            disabled={controlsDisabled}
            onClick={() => setShowMorePills((prev) => !prev)}
            aria-expanded={showMorePills}
            aria-controls={morePillsRegionId}
            className={`flex min-h-11 items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-600 shadow-sm transition-all hover:border-brand-300 hover:bg-brand-50 hover:text-brand-600 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:bg-brand-500/20 dark:hover:text-brand-300 ${focusRingClass}`}
          >
            <ChevronDown className={`h-4 w-4 transition-transform duration-300 ${showMorePills ? 'rotate-180' : ''}`} />
            {moreLabel}
          </button>
        </div>

        <div
          id={morePillsRegionId}
          aria-hidden={!showMorePills}
          className={`grid transition-all duration-300 ease-in-out ${showMorePills ? 'pointer-events-auto visible mt-3 grid-rows-[1fr] opacity-100' : 'invisible pointer-events-none mt-0 grid-rows-[0fr] opacity-0'}`}
        >
          <div className="overflow-hidden flex flex-wrap justify-center gap-3">
            {morePills.map((pill) => (
              <button
                type="button"
                key={pill.id}
                disabled={controlsDisabled}
                tabIndex={showMorePills && !controlsDisabled ? 0 : -1}
                onClick={() => onSelectPill(pill)}
                aria-pressed={selectedPillId === pill.id}
                className={`flex min-h-11 items-center gap-2 rounded-full border px-4 py-2.5 text-sm font-medium transition-all shadow-sm disabled:cursor-not-allowed disabled:opacity-50 ${focusRingClass} ${selectedPillId === pill.id ? 'border-brand-300 bg-brand-50 text-brand-700 dark:border-brand-500 dark:bg-brand-500/20 dark:text-brand-300' : 'border-slate-200 bg-white text-slate-600 hover:border-brand-300 hover:bg-brand-50 hover:text-brand-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:bg-brand-500/20 dark:hover:text-brand-300'}`}
              >
                {(() => {
                  const Icon = getPillIcon(pill.id);
                  return <Icon className="h-4 w-4 shrink-0" />;
                })()}
                {pill.label}
              </button>
            ))}
          </div>
        </div>
      </div>}
    </>
  );
}

export default DiagramPromptComposer;
