import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, Loader2, X } from 'lucide-react';
import { useBackendAuth } from '../features/auth/BackendAuthProvider';
import { useLanguage } from '../i18n/LanguageProvider';
import { useToast } from './toastContext';
import {
  getPendingGuestImportSummary,
  importGuestProjectsToAccount,
  type PendingGuestImportSummary,
} from '../services/guestImportService';

const hasOpenModalDialog = (): boolean => (
  typeof document !== 'undefined'
  && Boolean(document.querySelector('[role="dialog"][aria-modal="true"]'))
);

export function GuestImportPrompt() {
  const { user } = useBackendAuth();
  const { t } = useLanguage();
  const { showToast } = useToast();
  const [pendingSummary, setPendingSummary] = useState<PendingGuestImportSummary | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [hasBlockingDialog, setHasBlockingDialog] = useState(false);
  const promptRef = useRef<HTMLDivElement | null>(null);

  const userId = user?.user_id ?? null;
  const promptVisible = Boolean(userId && !dismissed && pendingSummary && !hasBlockingDialog);

  const refreshPendingSummary = useCallback(() => {
    if (!userId || dismissed) {
      setPendingSummary(null);
      return;
    }

    setPendingSummary(getPendingGuestImportSummary(userId));
  }, [dismissed, userId]);

  useEffect(() => {
    refreshPendingSummary();
  }, [refreshPendingSummary]);

  useEffect(() => {
    try {
      setDismissed(Boolean(userId && sessionStorage.getItem(`guest-import-later:${userId}`)));
    } catch {
      setDismissed(false);
    }
  }, [userId]);

  const dismissForSession = () => {
    setDismissed(true);
    try {
      if (userId) sessionStorage.setItem(`guest-import-later:${userId}`, 'true');
    } catch { /* Dismissing still works for this page when browser storage is unavailable. */ }
  };

  useEffect(() => {
    const refreshDialogPresence = () => {
      setHasBlockingDialog(hasOpenModalDialog());
    };

    refreshDialogPresence();

    const observer = new MutationObserver(refreshDialogPresence);
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ['aria-modal', 'role'],
    });

    return () => {
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    const clearPromptOffset = () => {
      root.removeAttribute('data-guest-import-prompt');
      root.style.removeProperty('--guest-import-prompt-offset');
    };

    if (!promptVisible) {
      clearPromptOffset();
      return clearPromptOffset;
    }

    const updatePromptOffset = () => {
      const promptHeight = promptRef.current?.getBoundingClientRect().height ?? 0;
      root.setAttribute('data-guest-import-prompt', 'visible');
      root.style.setProperty(
        '--guest-import-prompt-offset',
        `${Math.ceil(promptHeight + 32)}px`,
      );
    };

    updatePromptOffset();

    const resizeObserver = typeof ResizeObserver !== 'undefined'
      ? new ResizeObserver(updatePromptOffset)
      : null;
    if (resizeObserver && promptRef.current) {
      resizeObserver.observe(promptRef.current);
    }

    window.addEventListener('resize', updatePromptOffset);

    return () => {
      resizeObserver?.disconnect();
      window.removeEventListener('resize', updatePromptOffset);
      clearPromptOffset();
    };
  }, [promptVisible]);

  const handleImport = async () => {
    if (!userId || isImporting) return;

    setIsImporting(true);
    try {
      const result = await importGuestProjectsToAccount(userId);
      setPendingSummary(null);
      setDismissed(true);
      showToast(
        t('guestImport.success')
          .replace('{projectCount}', String(result.importedProjects))
          .replace('{snapshotCount}', String(result.importedSnapshots)),
        'success',
      );
    } catch (error) {
      console.error('Guest project import failed:', error);
      showToast(t('guestImport.failed'), 'error');
      refreshPendingSummary();
    } finally {
      setIsImporting(false);
    }
  };

  if (!promptVisible || !pendingSummary) {
    return null;
  }

  return (
    <div ref={promptRef} className="fixed inset-x-0 bottom-4 z-[60] px-4 sm:px-6" role="status" aria-live="polite">
      <div className="mx-auto flex max-w-3xl flex-col gap-3 rounded-2xl border border-brand-200/80 bg-white/92 p-4 shadow-[0_24px_70px_rgba(49,141,255,0.2)] ring-1 ring-white/70 backdrop-blur-2xl dark:border-brand-500/35 dark:bg-slate-950/92 dark:shadow-[0_24px_70px_rgba(2,6,23,0.55)] dark:ring-white/10 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            {t('guestImport.title')}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-slate-600 dark:text-slate-400">
            {t('guestImport.description')
              .replace('{projectCount}', String(pendingSummary.projectCount))
              .replace('{snapshotCount}', String(pendingSummary.snapshotCount))}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={handleImport}
            disabled={isImporting}
            className="btn-primary min-h-11 gap-2 px-4 text-xs"
          >
            {isImporting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <ArrowRight className="h-3.5 w-3.5" />
            )}
            {isImporting ? t('guestImport.importing') : t('guestImport.importNow')}
          </button>
          <button
            type="button"
            onClick={dismissForSession}
            disabled={isImporting}
            className="inline-flex min-h-11 items-center justify-center rounded-xl border border-slate-200 bg-white/75 px-3 py-2 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:text-slate-800 focus-visible:ring-2 focus-visible:ring-brand-300 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900/75 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-slate-100"
          >
            {t('guestImport.later')}
          </button>
          <button
            type="button"
            onClick={dismissForSession}
            disabled={isImporting}
            className="inline-flex h-11 w-11 items-center justify-center rounded-xl text-slate-400 transition hover:bg-slate-100 hover:text-slate-600 focus-visible:ring-2 focus-visible:ring-brand-300 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-slate-800 dark:hover:text-slate-300"
            aria-label={t('guestImport.dismiss')}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
