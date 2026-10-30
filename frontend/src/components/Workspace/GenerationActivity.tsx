import { Activity, AlertTriangle, BrainCircuit, Check, Circle, LayoutTemplate, Loader2, Minus, Network, Palette, PencilLine, ShieldCheck, Sparkles, Square, X } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { useAnchoredPopover } from '../../hooks/useAnchoredPopover';
import { useLanguage } from '../../i18n/LanguageProvider';
import { BROWSER_MODE } from '../../services/browser/runtime';
import type { GenerationProgress, StreamStageExtended } from '../../types/app';
import { activityCanAutoClose, generationActivityStages } from '../../utils/generationActivity';
import { formatGenerationDuration, getGenerationReviewState } from '../../utils/generationReport';
import type { GenerationReport as Report } from '../../utils/generationReport';
import { GenerationReport } from '../GenerationReport';

const icons = { memory: BrainCircuit, structure: Network, styling: Palette, layout: LayoutTemplate,
  render: LayoutTemplate, verification: ShieldCheck, refining: Sparkles, final_verification: ShieldCheck, learning: BrainCircuit };
const labels: Record<StreamStageExtended, [string, string]> = { memory: ['读取 DNA', 'Read DNA'], structure: ['构建结构', 'Plan structure'],
  styling: ['设计样式', 'Design style'], layout: ['编排布局', 'Arrange layout'], render: ['渲染画布', 'Render canvas'],
  verification: ['检查图表', 'Check diagram'], refining: ['评审与精修', 'Review & refine'], final_verification: ['复核结果', 'Verify result'], learning: ['学习偏好', 'Learn preferences'] };

export function GenerationActivity({ running, progress, report, failed = false, cancelled = false, contextLabel, documentKey, onCancel }: {
  contextLabel?: string; documentKey?: string;
  running: boolean; progress: GenerationProgress | null; report?: Report; failed?: boolean; cancelled?: boolean; onCancel: () => void;
}) {
  const { language, t } = useLanguage();
  const zh = language === 'zh';
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(Date.now);
  const lastProgress = useRef<GenerationProgress | null>(null);
  const wasRunning = useRef(false);
  const automatic = useRef(false);
  const runDocument = useRef(documentKey);
  const runStartedAt = useRef(0);
  const scope = useRef(documentKey);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const id = useId();
  const stopped = cancelled && documentKey === runDocument.current;
  const interrupted = failed || stopped;
  const reviewState = report ? getGenerationReviewState(report) : undefined;
  const needsAttention = !running && !interrupted && ['needs_attention', 'kept_original'].includes(reviewState ?? '');
  useAnchoredPopover(open, trigger, panel, 316, 'below', 'end');
  useEffect(() => { if (progress) lastProgress.current = progress; }, [progress]);
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);
  useEffect(() => {
    let timer: number | undefined;
    if (!running && !wasRunning.current && scope.current !== documentKey) {
      setOpen(false); automatic.current = false; lastProgress.current = null;
    }
    scope.current = documentKey;
    if (running && !wasRunning.current) { automatic.current = true; runDocument.current = documentKey; runStartedAt.current = Date.now(); setOpen(true); setNow(Date.now()); }
    if (wasRunning.current && activityCanAutoClose(running, interrupted || needsAttention, automatic.current)) timer = window.setTimeout(() => {
      if (automatic.current) setOpen(false);
    }, 2600);
    wasRunning.current = running;
    return () => clearTimeout(timer);
  }, [running, interrupted, needsAttention, documentKey]);
  useEffect(() => {
    if (!open) return;
    const outside = (event: Event) => {
      if (event.target instanceof Node && !panel.current?.contains(event.target) && !trigger.current?.contains(event.target)) {
        automatic.current = false; setOpen(false);
      }
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault(); event.stopPropagation(); automatic.current = false; setOpen(false); trigger.current?.focus();
    };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape, true);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape, true); };
  }, [open]);
  if (!running && !report && !interrupted) return null;
  const current = running ? progress : lastProgress.current;
  const rows = generationActivityStages(current, interrupted ? undefined : report, running, BROWSER_MODE, now);
  const currentRow = rows.find(row => row.state === 'running');
  const title = running ? currentRow ? labels[currentRow.key][zh ? 0 : 1] : zh ? '准备生成' : 'Preparing'
    : interrupted ? zh ? stopped ? '已停止' : '生成未完成' : stopped ? 'Stopped' : 'Generation interrupted'
      : zh ? '生成记录' : 'Generation record';
  const duration = running ? Math.max(0, now - (current?.startedAt ?? runStartedAt.current ?? now)) : !interrupted ? report?.durationMs : undefined;
  const statusHint = reviewState === 'edited' ? (zh ? '已修改' : 'Edited') : needsAttention ? (zh ? '需要检查' : 'Needs review') : '';
  const TriggerIcon = running ? Loader2 : interrupted || needsAttention ? AlertTriangle : reviewState === 'edited' ? PencilLine : Activity;
  return <div className="generation-activity" data-running={running} data-attention={interrupted || needsAttention}>
    <button ref={trigger} type="button" className="tool-button generation-activity-trigger" aria-label={statusHint ? `${title} · ${statusHint}` : title}
      aria-expanded={open} aria-haspopup="dialog" aria-controls={id} title={statusHint ? `${title} · ${statusHint}` : title}
      onClick={() => { automatic.current = false; setOpen(value => !value); }}>
      <TriggerIcon size={15} className={running ? 'animate-spin' : undefined} aria-hidden="true" />
      <span className="generation-activity-label">{title}</span>
      {duration !== undefined && <time>{formatGenerationDuration(duration)}</time>}
    </button>
    <span className="sr-only" role="status" aria-live="polite">{title}</span>
    {open && <div ref={panel} id={id} popover="manual" role="dialog" aria-label={zh ? '生成进度' : 'Generation progress'} className="generation-activity-panel"
      onPointerDown={() => { automatic.current = false; }} onFocusCapture={() => { automatic.current = false; }}>
      <header><strong>{title}</strong><button type="button" className="tool-button" aria-label={zh ? '关闭生成记录' : 'Close generation record'}
        onClick={() => { automatic.current = false; setOpen(false); trigger.current?.focus(); }}><X size={14} /></button></header>
      <ol>{rows.map(row => {
        const Icon = icons[row.key];
        return <li key={row.key} data-stage={row.key} data-state={row.state}>
          <span className="generation-stage-symbol"><Icon size={16} aria-hidden="true" /></span>
          <span>{labels[row.key][zh ? 0 : 1]}</span>
          <time>{row.durationMs === undefined ? '—' : formatGenerationDuration(row.durationMs)}</time>
          {row.state === 'running' ? <Loader2 size={13} className="animate-spin" aria-label={zh ? '进行中' : 'Running'} />
            : row.state === 'done' ? <Check size={13} aria-label={zh ? '已完成' : 'Completed'} />
              : row.state === 'skipped' ? <Minus size={13} aria-label={zh ? '已跳过' : 'Skipped'} />
                : <Circle size={7} aria-label={zh ? row.state === 'interrupted' ? '未完成' : '等待中' : row.state === 'interrupted' ? 'Interrupted' : 'Pending'} />}
        </li>;
      })}</ol>
      {running && <footer><span>{contextLabel || (zh ? '正在创作' : 'Creating')}{duration !== undefined ? ` · ${formatGenerationDuration(duration)}` : ''}</span>
        <button type="button" className="tool-button" onClick={onCancel}><Square size={11} />{zh ? '停止' : 'Stop'}</button></footer>}
      {!running && !interrupted && report && <GenerationReport report={report} t={t} hideTimings compactLabel={zh ? '评审详情' : 'Review details'} />}
      {interrupted && <p className="generation-activity-note">{zh ? '已保留当前画布，可调整后重试。' : 'Your canvas is kept. Adjust the prompt and try again.'}</p>}
    </div>}
  </div>;
}
