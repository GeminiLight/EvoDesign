import { useEffect, useRef, useState } from 'react';
import { Dna, X, Pencil, Check } from 'lucide-react';
import { DnaSyncStatus } from '../DNA/DnaSyncStatus';
import { useRuleLibrary } from '../../hooks/useRuleLibrary';
import { guestHasProjectDna, guestDeleteProjectDnaRules } from '../../services/guestStorage';
import { useBackendAuth } from '../../features/auth/BackendAuthProvider';
import { useLanguage } from '../../i18n/LanguageProvider';
import type { CabinId } from '../../types/dna';

interface ProjectDnaDrawerProps {
  projectId: string;
  onClose: () => void;
}

const CABIN_META: Record<CabinId, { label: string; labelZh: string; color: string; bg: string; border: string }> = {
  structure: {
    label: 'Structure',
    labelZh: '结构',
    color: 'text-indigo-600 dark:text-indigo-400',
    bg: 'bg-indigo-50 dark:bg-indigo-500/10',
    border: 'border-indigo-200 dark:border-indigo-500/30',
  },
  style: {
    label: 'Style',
    labelZh: '样式',
    color: 'text-violet-600 dark:text-violet-400',
    bg: 'bg-violet-50 dark:bg-violet-500/10',
    border: 'border-violet-200 dark:border-violet-500/30',
  },
  layout: {
    label: 'Layout',
    labelZh: '布局',
    color: 'text-teal-600 dark:text-teal-400',
    bg: 'bg-teal-50 dark:bg-teal-500/10',
    border: 'border-teal-200 dark:border-teal-500/30',
  },
};

const CABIN_IDS: CabinId[] = ['structure', 'style', 'layout'];

/**
 * Inner component that mounts only when project DNA is enabled.
 * Mounting triggers useRuleLibrary which pre-populates from global DNA on first use.
 */
function ProjectDnaCabins({ projectId }: { projectId: string }) {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const ruleLib = useRuleLibrary({ projectId });

  return (
    <div className="space-y-5">
      <DnaSyncStatus {...ruleLib} />
      <fieldset disabled={!ruleLib.canEditRules} className="min-w-0 space-y-5">
      {CABIN_IDS.map((cabinId) => {
        const meta = CABIN_META[cabinId];
        const rules = ruleLib.ruleLibrary[cabinId];
        return (
          <div key={cabinId} className={`rounded-xl border p-4 ${meta.border} ${meta.bg}`}>
            <p className={`mb-3 text-xs font-bold uppercase tracking-widest ${meta.color}`}>
              {zh ? meta.labelZh : meta.label}
              <span className="ml-2 font-normal normal-case text-slate-400">
                {rules.filter((r) => r.enabled).length}/{rules.length} {zh ? '启用' : 'enabled'}
              </span>
            </p>

            {rules.length === 0 ? (
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {zh ? '暂无规则' : 'No rules yet'}
              </p>
            ) : (
              <div className="space-y-2">
                {rules.map((rule) => {
                  const isEditing =
                    ruleLib.editing?.cabinId === cabinId && ruleLib.editing.rule.id === rule.id;
                  return (
                    <div
                      key={rule.id}
                      className="flex items-start gap-3 rounded-lg border border-white/70 bg-white/80 px-3 py-2.5 dark:border-slate-700 dark:bg-slate-800/60"
                    >
                      {/* Enable toggle */}
                      <button
                        type="button"
                        role="switch"
                        aria-checked={rule.enabled}
                        aria-label={`${rule.enabled ? (zh ? '停用' : 'Disable') : (zh ? '启用' : 'Enable')} ${rule.title}`}
                        onClick={() => ruleLib.toggleRuleEnabled(cabinId, rule.id)}
                        className="mt-0.5 inline-flex h-11 w-14 shrink-0 items-center justify-center rounded-xl transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-900"
                      >
                        <span className={`flex h-6 w-11 items-center rounded-full border-2 border-transparent transition-colors ${rule.enabled ? 'bg-brand-500' : 'bg-slate-200 dark:bg-slate-600'}`}>
                          <span
                            className={`h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform ${rule.enabled ? 'translate-x-5' : 'translate-x-0.5'}`}
                          />
                        </span>
                      </button>

                      {/* Rule content */}
                      <div className="min-w-0 flex-1">
                        {isEditing ? (
                          <div className="space-y-1.5">
                            <input
                              value={ruleLib.draftTitle}
                              onChange={(e) => ruleLib.setDraftTitle(e.target.value)}
                              className="min-h-11 w-full rounded-lg border border-brand-200 bg-white px-3 py-2 text-xs font-semibold text-slate-800 outline-none transition focus:border-brand-400 focus-visible:ring-2 focus-visible:ring-brand-300 dark:border-brand-500/60 dark:bg-slate-900 dark:text-slate-100"
                              placeholder={zh ? '规则名称' : 'Rule title'}
                            />
                            <textarea
                              value={ruleLib.draftPreview}
                              onChange={(e) => ruleLib.setDraftPreview(e.target.value)}
                              rows={2}
                              className="min-h-20 w-full resize-none rounded-lg border border-brand-200 bg-white px-3 py-2 text-xs text-slate-600 outline-none transition focus:border-brand-400 focus-visible:ring-2 focus-visible:ring-brand-300 dark:border-brand-500/60 dark:bg-slate-900 dark:text-slate-300"
                              placeholder={zh ? '描述此规则的效果' : 'Describe what this rule does'}
                            />
                            <div className="flex gap-1.5">
                              <button
                                type="button"
                                onClick={() => ruleLib.saveEdit()}
                                className="flex min-h-11 items-center gap-1 rounded-lg px-3 py-2 text-[11px] font-medium text-brand-600 transition hover:bg-brand-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 dark:text-brand-400 dark:hover:bg-brand-500/10"
                              >
                                <Check className="h-3 w-3" />
                                {zh ? '保存' : 'Save'}
                              </button>
                              <button
                                type="button"
                                onClick={() => ruleLib.setEditing(null)}
                                className="min-h-11 rounded-lg px-3 py-2 text-[11px] font-medium text-slate-500 transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 dark:text-slate-400 dark:hover:bg-slate-800"
                              >
                                {zh ? '取消' : 'Cancel'}
                              </button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <p
                              className={`text-xs font-semibold ${rule.enabled ? 'text-slate-700 dark:text-slate-200' : 'text-slate-500 dark:text-slate-400'}`}
                            >
                              {rule.title}
                            </p>
                            <p
                              className={`mt-0.5 text-[11px] leading-relaxed ${rule.enabled ? 'text-slate-500 dark:text-slate-400' : 'text-slate-300 dark:text-slate-600'}`}
                            >
                              {rule.preview}
                            </p>
                          </>
                        )}
                      </div>

                      {/* Edit button */}
                      {!isEditing && (
                        <button
                          type="button"
                          onClick={() => ruleLib.openEdit(cabinId, rule)}
                          aria-label={zh ? '编辑' : 'Edit'}
                          className="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 dark:text-slate-500 dark:hover:bg-slate-700 dark:hover:text-slate-300"
                        >
                          <Pencil className="h-3 w-3" />
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
      </fieldset>
    </div>
  );
}

export function ProjectDnaDrawer({ projectId, onClose }: ProjectDnaDrawerProps) {
  const { user, token } = useBackendAuth();
  const { language } = useLanguage();
  const zh = language === 'zh';
  const storageScopeId = token && user?.user_id ? user.user_id : null;
  const [enabled, setEnabled] = useState(() => guestHasProjectDna(projectId, storageScopeId));
  const drawerRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const lastFocusedElementRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    setEnabled(guestHasProjectDna(projectId, storageScopeId));
  }, [projectId, storageScopeId]);

  useEffect(() => {
    lastFocusedElementRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;

    const previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const frameId = window.requestAnimationFrame(() => closeButtonRef.current?.focus());

    return () => {
      window.cancelAnimationFrame(frameId);
      document.body.style.overflow = previousBodyOverflow;
      lastFocusedElementRef.current?.focus();
    };
  }, []);

  const handleToggleOff = () => {
    guestDeleteProjectDnaRules(projectId, storageScopeId);
    setEnabled(false);
  };

  const handleToggleOn = () => {
    setEnabled(true);
    // ProjectDnaCabins will mount and useRuleLibrary will pre-populate from global on first save
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-end"
      role="dialog"
      aria-modal="true"
      aria-labelledby="project-dna-drawer-title"
      aria-describedby="project-dna-drawer-desc"
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          onClose();
          return;
        }

        if (event.key !== 'Tab') return;
        const container = drawerRef.current;
        if (!container) return;

        const focusable = Array.from(
          container.querySelectorAll<HTMLElement>(
            'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
          ),
        ).filter((element) => !element.hasAttribute('hidden'));

        if (focusable.length === 0) return;

        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const active = document.activeElement;

        if (event.shiftKey && active === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && active === last) {
          event.preventDefault();
          first.focus();
        }
      }}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/30 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />

      {/* Panel */}
      <div ref={drawerRef} className="relative z-10 flex h-full w-full max-w-md flex-col overflow-hidden border-l border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900">
        {/* Header */}
        <div className="flex shrink-0 items-center gap-3 border-b border-slate-100 px-5 py-4 dark:border-slate-800">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-brand-50 dark:bg-brand-500/15">
            <Dna className="h-4 w-4 text-brand-600 dark:text-brand-400" />
          </span>
          <div className="flex-1">
            <p id="project-dna-drawer-title" className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              {zh ? '项目专属 DNA' : 'Project DNA'}
            </p>
            <p id="project-dna-drawer-desc" className="text-[11px] text-slate-500 dark:text-slate-400">
              {zh ? '仅对此项目下的图表生效' : 'Applies to all diagrams in this project'}
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label={zh ? '关闭' : 'Close'}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-slate-200 text-slate-400 transition hover:border-slate-300 hover:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:border-slate-700 dark:hover:border-slate-600 dark:hover:text-slate-200 dark:focus-visible:ring-offset-slate-900"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Toggle row */}
        <div className="shrink-0 border-b border-slate-100 px-5 py-3 dark:border-slate-800">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                {zh ? '启用项目专属 DNA' : 'Use Project-Specific DNA'}
              </p>
              <p className="text-[11px] text-slate-500 dark:text-slate-400">
                {enabled
                  ? zh ? '当前使用项目专属规则' : 'Using project-specific rules'
                  : zh ? '当前使用通用 DNA' : 'Currently using global DNA'}
              </p>
            </div>
            {/* Toggle switch */}
            <button
              type="button"
              role="switch"
              aria-checked={enabled}
              aria-label={zh ? '启用项目专属 DNA' : 'Use project-specific DNA'}
              onClick={enabled ? handleToggleOff : handleToggleOn}
              className="relative inline-flex h-11 w-14 shrink-0 cursor-pointer items-center justify-center rounded-xl transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-900"
            >
              <span className={`flex h-6 w-11 items-center rounded-full border-2 border-transparent transition-colors ${enabled ? 'bg-brand-600' : 'bg-slate-200 dark:bg-slate-700'}`}>
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform ${enabled ? 'translate-x-5' : 'translate-x-0.5'}`}
                />
              </span>
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="custom-scrollbar flex-1 overflow-y-auto px-5 py-4">
          {enabled ? (
            <ProjectDnaCabins projectId={projectId} />
          ) : (
            <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
              <Dna className="h-10 w-10 text-slate-300 dark:text-slate-600" />
              <p className="text-sm font-medium text-slate-500 dark:text-slate-400">
                {zh ? '未启用项目专属 DNA' : 'Project DNA not enabled'}
              </p>
              <p className="max-w-xs text-[12px] text-slate-500 dark:text-slate-400">
                {zh
                  ? '开启后，此项目下的所有图表将使用独立的 DNA 规则，不影响其他项目。初始规则从通用 DNA 复制。'
                  : 'When enabled, all diagrams in this project use their own DNA rules, independent of other projects. Initial rules are copied from your global DNA.'}
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="shrink-0 border-t border-slate-100 px-5 py-3 dark:border-slate-800">
          <button
            type="button"
            onClick={onClose}
            className="min-h-11 w-full rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-900"
          >
            {zh ? '完成' : 'Done'}
          </button>
        </div>
      </div>
    </div>
  );
}
