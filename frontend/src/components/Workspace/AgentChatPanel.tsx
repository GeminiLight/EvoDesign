import { shouldSubmitOnEnter } from '../../utils/keyboard';
import { useRef, useEffect } from 'react';
import type { FormEvent } from 'react';
import { ArrowUp, ChevronDown, ChevronRight, Loader2, PencilLine, RefreshCcw, Sparkles, SquareDashedMousePointer, Zap } from 'lucide-react';
import { useLanguage } from '../../i18n/LanguageProvider';

export type AgentChatBusyKind = 'generation' | 'local-edit' | 'save-recovery' | 'history-switch';

export interface AgentChatPanelProps {
  chatMessages: Array<{ id: string; role: 'user' | 'agent'; content: string }>;
  chatInput: string;
  onChatInputChange: (value: string) => void;
  onSendMessage: () => void;
  onQuickPrompt?: (text: string) => void;
  hasContent?: boolean;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
  isGenerating?: boolean;
  busyKind?: AgentChatBusyKind | null;
  selectedCount?: number;
  selectionLabel?: string;
  staleSelectedCount?: number;
  preflightReviewActive?: boolean;
  /** True while the canvas onboarding card is showing its own starter prompts. */
  startPromptsHandledElsewhere?: boolean;
}

type ChatModeTone = 'start' | 'preflight' | 'local' | 'global' | 'stale' | 'busy';

const quickPromptsEn = [
  'Simplify this diagram',
  'Add error handling paths',
  'Unify colors and styling',
  'Add labels to all edges',
];

const quickPromptsZh = [
  '简化这个图表',
  '添加错误处理路径',
  '统一配色与样式',
  '给所有连线加标签',
];

const localEditPromptsEn = [
  'Clarify the selected elements',
  'Align the selected elements',
  'Highlight this selection',
  'Shorten selected labels',
];

const localEditPromptsZh = [
  '让选中元素更清晰',
  '对齐选中元素',
  '突出这组选区',
  '缩短选中标签',
];

const emptyCanvasPromptsEn = [
  'Generate a flowchart',
  'Create an architecture diagram',
  'Design a sequence diagram',
  'Draw a mind map',
];

const emptyCanvasPromptsZh = [
  '生成一个流程图',
  '创建一个架构图',
  '设计一个时序图',
  '画一个思维导图',
];

export function AgentChatPanel({
  chatMessages,
  chatInput,
  onChatInputChange,
  onSendMessage,
  hasContent = false,
  isCollapsed = false,
  onToggleCollapse,
  isGenerating = false,
  busyKind = null,
  selectedCount = 0,
  selectionLabel,
  staleSelectedCount = 0,
  preflightReviewActive = false,
  startPromptsHandledElsewhere = false,
}: AgentChatPanelProps) {
  const { t, language } = useLanguage();
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const panelId = 'workspace-agent-chat-panel';
  const logId = 'workspace-agent-chat-log';
  const inputHintId = 'workspace-agent-chat-input-hint';
  const modeNoticeId = 'workspace-agent-chat-mode-notice';
  const describedBy = `${modeNoticeId} ${inputHintId}`;
  const focusRingClass = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-brand-500 dark:focus-visible:ring-offset-slate-950';
  const effectiveBusyKind: AgentChatBusyKind | null = busyKind ?? (isGenerating ? 'generation' : null);
  const isWorkspaceBusy = Boolean(effectiveBusyKind);
  const hasSelection = selectedCount > 0;
  const hasStaleSelection = hasContent && staleSelectedCount > 0 && !hasSelection;
  const isPreflightStartMode = preflightReviewActive && !hasContent;
  const baseModeTone: Exclude<ChatModeTone, 'busy'> = isPreflightStartMode
    ? 'preflight'
    : !hasContent
    ? 'start'
    : hasSelection
      ? 'local'
      : hasStaleSelection
        ? 'stale'
      : 'global';
  const modeTone: ChatModeTone = isWorkspaceBusy ? 'busy' : baseModeTone;
  const ModeIcon = baseModeTone === 'local'
    ? SquareDashedMousePointer
    : baseModeTone === 'global'
      ? RefreshCcw
      : baseModeTone === 'preflight'
        ? PencilLine
      : baseModeTone === 'stale'
        ? SquareDashedMousePointer
        : Sparkles;
  const busyTitle = effectiveBusyKind === 'save-recovery'
    ? t('workspace.chatBusySaveRecoveryTitle')
    : effectiveBusyKind === 'history-switch'
      ? t('workspace.chatBusyHistorySwitchTitle')
      : effectiveBusyKind === 'local-edit'
        ? t('workspace.chatBusyLocalEditTitle')
        : effectiveBusyKind === 'generation'
          ? t('workspace.chatBusyGenerationTitle')
          : '';
  const busyDescription = effectiveBusyKind === 'save-recovery'
    ? t('workspace.chatBusySaveRecoveryHint')
    : effectiveBusyKind === 'history-switch'
      ? t('workspace.chatBusyHistorySwitchHint')
      : effectiveBusyKind === 'local-edit'
        ? t('workspace.chatBusyLocalEditHint')
        : effectiveBusyKind === 'generation'
          ? t('workspace.chatBusyGenerationHint')
          : '';
  const EffectiveModeIcon = isWorkspaceBusy ? Loader2 : ModeIcon;
  const modeTitle = modeTone === 'local'
    ? t('workspace.chatModeLocalTitle').replace('{count}', String(selectedCount))
    : modeTone === 'global'
      ? t('workspace.chatModeGlobalTitle')
      : modeTone === 'stale'
        ? t('workspace.chatModeStaleTitle')
        : modeTone === 'busy'
          ? busyTitle
          : modeTone === 'preflight'
            ? t('workspace.chatModePreflightTitle')
          : t('workspace.chatModeStartTitle');
  const modeDescription = modeTone === 'local'
    ? t('workspace.chatModeLocalHint')
    : modeTone === 'global'
      ? t('workspace.chatModeGlobalHint')
      : modeTone === 'stale'
        ? t('workspace.chatModeStaleHint')
        : modeTone === 'busy'
          ? busyDescription
          : modeTone === 'preflight'
            ? t('workspace.chatModePreflightHint')
          : t('workspace.chatModeStartHint');
  const sendLabel = baseModeTone === 'local'
    ? t('workspace.sendLocalEdit')
    : baseModeTone === 'global'
      ? t('workspace.sendGlobalRegenerate')
      : baseModeTone === 'stale'
        ? t('workspace.sendSelectionExpired')
        : baseModeTone === 'preflight'
          ? t('workspace.sendPreflightReview')
      : t('workspace.sendStartDiagram');
  const inputPlaceholder = baseModeTone === 'local'
    ? t('workspace.typeLocalEdit')
    : baseModeTone === 'global'
      ? t('workspace.typeGlobalUpdate')
      : baseModeTone === 'stale'
        ? t('workspace.typeStaleSelection')
        : baseModeTone === 'preflight'
          ? t('workspace.typePreflightReview')
        : t('workspace.typeStartDiagram');
  const modeToneClass = modeTone === 'local'
    ? 'border-brand-200 bg-brand-50/80 text-brand-800 dark:border-brand-500/30 dark:bg-brand-500/10 dark:text-brand-200'
    : modeTone === 'global'
      ? 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-300'
      : modeTone === 'busy'
        ? 'border-brand-200 bg-brand-50/85 text-brand-900 dark:border-brand-500/35 dark:bg-brand-500/12 dark:text-brand-100'
      : modeTone === 'preflight'
        ? 'border-brand-200 bg-brand-50/85 text-brand-900 dark:border-brand-500/35 dark:bg-brand-500/12 dark:text-brand-100'
      : modeTone === 'stale'
        ? 'border-rose-200 bg-rose-50/85 text-rose-900 dark:border-rose-500/35 dark:bg-rose-500/10 dark:text-rose-100'
      : 'border-slate-200 bg-slate-50/85 text-slate-700 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-200';
  const modeIconClass = modeTone === 'local'
    ? 'text-brand-500 dark:text-brand-300'
    : modeTone === 'global'
      ? 'text-slate-500 dark:text-slate-400'
      : modeTone === 'busy'
        ? 'text-brand-500 dark:text-brand-300'
      : modeTone === 'preflight'
        ? 'text-brand-500 dark:text-brand-300'
      : modeTone === 'stale'
        ? 'text-rose-600 dark:text-rose-300'
      : 'text-slate-500 dark:text-slate-300';
  const quickPromptMode: 'start' | 'local' | 'global' | 'stale' = !hasContent
    ? 'start'
    : hasSelection
      ? 'local'
      : hasStaleSelection
        ? 'stale'
      : 'global';
  const quickPromptGroupLabel = quickPromptMode === 'local'
    ? t('workspace.quickPromptsLocalTitle')
    : quickPromptMode === 'global'
      ? t('workspace.quickPromptsGlobalTitle')
      : quickPromptMode === 'stale'
        ? t('workspace.quickPromptsStaleTitle')
      : t('workspace.quickPromptsStartTitle');
  const quickPromptButtonLabel = quickPromptMode === 'local'
    ? t('workspace.quickPromptLocalAria')
    : quickPromptMode === 'global'
      ? t('workspace.quickPromptGlobalAria')
      : quickPromptMode === 'stale'
        ? t('workspace.quickPromptStaleAria')
      : t('workspace.quickPromptStartAria');
  const QuickPromptIcon = quickPromptMode === 'local'
    ? SquareDashedMousePointer
    : quickPromptMode === 'global'
      ? RefreshCcw
      : quickPromptMode === 'stale'
        ? SquareDashedMousePointer
      : Zap;

  const quickPrompts = quickPromptMode === 'local'
    ? (language === 'zh' ? localEditPromptsZh : localEditPromptsEn)
    : quickPromptMode === 'global'
      ? (language === 'zh' ? quickPromptsZh : quickPromptsEn)
      : (language === 'zh' ? emptyCanvasPromptsZh : emptyCanvasPromptsEn);
  const quickPromptsDisabled = isWorkspaceBusy || quickPromptMode === 'stale';
  // The onboarding card over the canvas already offers starter prompts under
  // the same heading. Showing a second, different list here made one screen
  // present two competing answers to "how do I start".
  const showQuickPrompts = !isPreflightStartMode
    && !(startPromptsHandledElsewhere && quickPromptMode === 'start');
  const chatInputHint = isWorkspaceBusy
    ? t('workspace.chatInputBusyHint')
    : isPreflightStartMode
      ? t('workspace.chatInputPreflightHint')
    : t('workspace.chatInputHint');
  const canSendMessage = !isWorkspaceBusy && !hasStaleSelection && chatInput.trim().length > 0;
  const conversationMessages = chatMessages.filter(message => message.id !== 'agent-init');
  const isEmptyConversation = conversationMessages.length === 0;

  // Auto-scroll to latest message
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [chatMessages]);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.max(44, Math.min(el.scrollHeight, 120))}px`;
  }, [chatInput]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (shouldSubmitOnEnter(e)) {
      e.preventDefault();
      if (canSendMessage) onSendMessage();
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (canSendMessage) onSendMessage();
  };

  const promptButtons = (
    <div className="assistant-prompt-grid" data-scope={quickPromptMode}>
      {quickPrompts.map((qp) => (
        <button
          key={qp}
          type="button"
          disabled={quickPromptsDisabled}
          aria-label={quickPromptButtonLabel.replace('{prompt}', qp)}
          title={isWorkspaceBusy ? busyTitle : quickPromptGroupLabel}
          onClick={() => {
            onChatInputChange(qp);
            textareaRef.current?.focus();
          }}
          className={`inline-flex max-w-full items-center border disabled:cursor-not-allowed disabled:opacity-55 ${focusRingClass}`}
        >
          <QuickPromptIcon className="h-2.5 w-2.5 shrink-0" />
          <span className="min-w-0 break-words text-left">{qp}</span>
        </button>
      ))}
    </div>
  );

  if (isCollapsed) {
    return (
      <aside
        id={panelId}
        aria-label={t('workspace.agentName')}
        aria-busy={isWorkspaceBusy}
        className="assistant-rail"
      >
        <button
          type="button"
          onClick={onToggleCollapse}
          className={`inline-flex h-11 w-11 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 shadow-sm transition hover:border-brand-300 hover:text-brand-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400 dark:hover:border-brand-500 dark:hover:text-brand-300 ${focusRingClass}`}
          aria-label={t('workspace.expandChat')}
          aria-expanded="false"
          aria-controls={panelId}
          title={t('workspace.expandChat')}
        >
          <ChevronRight className="h-4 w-4 rotate-180" />
        </button>
        <Sparkles className="h-4 w-4 text-brand-500" />
      </aside>
    );
  }

  return (
    <aside
      id={panelId}
      aria-label={t('workspace.agentName')}
      aria-busy={isWorkspaceBusy}
      className="assistant-panel"
    >
      {/* Collapse toggle */}
      <button
        type="button"
        onClick={onToggleCollapse}
        className={`absolute right-3 top-4 z-10 hidden h-8 w-8 items-center justify-center rounded-lg text-slate-500 transition hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800 lg:inline-flex ${focusRingClass}`}
        aria-label={t('workspace.collapseChat')}
        aria-expanded="true"
        aria-controls={panelId}
        title={t('workspace.collapseChat')}
      >
        <ChevronRight className="h-3.5 w-3.5" />
      </button>

      <div className="assistant-header">
        <span className="assistant-avatar"><Sparkles size={18} aria-hidden="true" /></span>
        <div>
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{t('workspace.agentName')}</h2>
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{t('workspace.assistantSubtitle')}</p>
        </div>
      </div>

      {/* Message feed */}
      <div
        id={logId}
        ref={scrollRef}
        role="log"
        aria-label={t('workspace.chatMessages')}
        aria-live="polite"
        className="assistant-feed custom-scrollbar"
      >
        {isEmptyConversation && !startPromptsHandledElsewhere && (
          <div className="assistant-welcome">
            <div className="assistant-welcome-symbol" aria-hidden="true"><SquareDashedMousePointer size={25} strokeWidth={1.4} /></div>
            <h3>{t(hasContent ? 'workspace.assistantWelcome' : 'workspace.assistantStart')}</h3>
            <p>{t(hasContent ? 'workspace.assistantWelcomeHint' : 'workspace.assistantStartHint')}</p>
            {showQuickPrompts && <div className="assistant-suggestions" role="group" aria-label={quickPromptGroupLabel}>
              <p className="assistant-suggestions-label">{quickPromptGroupLabel}</p>
              {promptButtons}
            </div>}
          </div>
        )}
        {isEmptyConversation && startPromptsHandledElsewhere && <p className="pt-4 text-[13px] leading-6 text-slate-500 dark:text-slate-400">
          {language === 'zh' ? '先在画布上创建图表。完成后，可以在这里调整整体，或选中元素进行局部修改。' : 'Start with an idea on the canvas. Then refine the whole diagram here, or select an element to edit it.'}
        </p>}
        <div className="space-y-4">
          {conversationMessages.map((msg) =>
            msg.role === 'agent' ? (
              <div key={msg.id} className="flex items-start gap-2">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-brand-50 dark:bg-brand-500/15">
                  <Sparkles className="h-3 w-3 text-brand-500" />
                </span>
                <div className="assistant-message min-w-0 flex-1 whitespace-pre-wrap break-words text-sm leading-7 text-slate-700 dark:text-slate-200">
                  {msg.content}
                </div>
              </div>
            ) : (
              <div key={msg.id} className="flex justify-end">
                <div className="assistant-message min-w-0 max-w-[90%] whitespace-pre-wrap break-words rounded-2xl rounded-tr-md bg-brand-50 px-3 py-2 text-sm leading-relaxed text-brand-900 dark:bg-brand-500/15 dark:text-brand-100">
                  {msg.content}
                </div>
              </div>
            )
          )}

          {isWorkspaceBusy && (
            <div className="flex items-start gap-2" role="status" aria-label={busyTitle || t('workspace.typingStatus')}>
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-brand-50 dark:bg-brand-500/15">
                <Sparkles className="h-3 w-3 text-brand-500" />
              </span>
              <div className="flex items-center gap-1.5 rounded-2xl rounded-tl-sm bg-slate-50 px-3 py-2.5 dark:bg-slate-800">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:0ms]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:150ms]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:300ms]" />
              </div>
            </div>
          )}
        </div>
      </div>

      {!startPromptsHandledElsewhere && <form className="assistant-composer" onSubmit={handleSubmit}>
        {!isEmptyConversation && showQuickPrompts && <details className="assistant-followups">
          <summary><ChevronDown size={13} aria-hidden="true" />{quickPromptGroupLabel}</summary>
          {promptButtons}
        </details>}
        <div className="assistant-composer-box">
          <div id={modeNoticeId} className={`assistant-scope ${modeToneClass}`}
            data-testid="workspace-chat-mode-notice" aria-live="polite">
            <div className="flex items-center gap-2">
              <EffectiveModeIcon className={`h-3.5 w-3.5 shrink-0 ${modeIconClass} ${isWorkspaceBusy ? 'animate-spin' : ''}`} />
              <p className="text-xs font-semibold">{modeTitle}</p>
            </div>
            {modeTone === 'local' && selectionLabel && <p className="mt-1 truncate text-xs font-medium" title={selectionLabel}>{selectionLabel}</p>}
            <p className="mt-1 text-xs leading-relaxed">{modeDescription}</p>
          </div>
          <textarea
            ref={textareaRef}
            value={chatInput}
            onChange={(e) => onChatInputChange(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={2}
            placeholder={inputPlaceholder}
            aria-label={inputPlaceholder}
            aria-describedby={describedBy}
            aria-controls={logId}
            className="assistant-textarea"
          />
          <div className="assistant-composer-actions">
            <span id={inputHintId} className="text-[10px] leading-relaxed text-slate-400 dark:text-slate-500">{chatInputHint}</span>
            <button type="submit" disabled={!canSendMessage}
              title={isWorkspaceBusy ? busyTitle : sendLabel}
              aria-label={isWorkspaceBusy ? busyTitle : sendLabel} aria-busy={isWorkspaceBusy}
              className={`assistant-send ${focusRingClass}`}>
              {isWorkspaceBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
              <span>{t('workspace.chatSend')}</span>
            </button>
          </div>
        </div>
      </form>}
    </aside>
  );
}
