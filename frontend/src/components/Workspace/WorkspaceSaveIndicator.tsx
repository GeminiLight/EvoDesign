import { AlertTriangle, Check, Loader2, Save } from 'lucide-react';
import type { WorkspaceSaveStatus } from '../../hooks/useDiagramSync';
import { useLanguage } from '../../i18n/LanguageProvider';
import { BROWSER_MODE } from '../../services/browser/runtime';

export function WorkspaceSaveIndicator({ status, dirty, disabled, onSave, compact = false }: {
  compact?: boolean;
  status: WorkspaceSaveStatus;
  dirty: boolean;
  disabled: boolean;
  onSave: () => void;
}) {
  const { t } = useLanguage();
  const saving = status === 'saving';
  const issue = ['failed', 'conflict', 'authExpired', 'missingProject'].includes(status);
  const label = t(`workspace.${saving ? 'savingChanges' : status === 'conflict' ? 'saveConflictAction'
    : status === 'authExpired' ? 'saveAuthExpiredAction' : status === 'missingProject' ? 'saveProjectMissingAction'
    : status === 'failed' ? 'retrySave' : dirty ? 'saveChanges' : 'changesSaved'}`);
  const hint = !dirty && !saving && !issue ? t(BROWSER_MODE ? 'workspace.savedInBrowser' : 'workspace.changesSaved') : label;
  const Icon = saving ? Loader2 : issue ? AlertTriangle : dirty ? Save : Check;
  const content = <><Icon size={14} aria-hidden="true" className={saving ? 'animate-spin' : ''} /><span className={compact && !issue ? 'sr-only' : 'canvas-save-label'}>{label}</span></>;

  return <div role="status" aria-live="polite" className="canvas-save-status shrink-0" data-attention={issue} data-compact={compact}>
    {dirty || issue ? <button type="button" className="tool-button" onClick={onSave} disabled={disabled || saving} aria-label={hint} title={hint}>{content}</button>
      : <span className="inline-flex min-h-9 items-center gap-1.5 px-1.5 text-[11px] text-slate-500 dark:text-slate-400" title={hint} aria-label={hint}>{content}</span>}
  </div>;
}
