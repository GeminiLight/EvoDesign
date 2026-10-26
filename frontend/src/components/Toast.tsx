import { useCallback, useState, useRef, useEffect } from 'react';
import type { ReactNode } from 'react';
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react';
import { useLanguage } from '../i18n/LanguageProvider';
import { ToastContext } from './toastContext';
import type { ToastVariant } from './toastContext';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ToastItem {
  id: string;
  message: string;
  variant: ToastVariant;
  /** Set to true when the exit animation starts so CSS can react. */
  exiting?: boolean;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

const AUTO_DISMISS_MS: Record<ToastVariant, number> = {
  success: 4000,
  info: 4000,
  error: 6000,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const removalTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: string) => {
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }

    if (removalTimersRef.current.has(id)) return;

    // Start exit animation
    setToasts((prev) => prev.map((t) => (t.id === id ? { ...t, exiting: true } : t)));
    // Remove after animation finishes
    const removalTimer = setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
      removalTimersRef.current.delete(id);
    }, 300);

    removalTimersRef.current.set(id, removalTimer);
  }, []);

  const showToast = useCallback(
    (message: string, variant: ToastVariant = 'info') => {
      const id = `toast_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
      setToasts((prev) => [...prev, { id, message, variant }]);

      const timer = setTimeout(() => {
        dismiss(id);
      }, AUTO_DISMISS_MS[variant]);

      timersRef.current.set(id, timer);
    },
    [dismiss],
  );

  // Clean up timers on unmount
  useEffect(() => {
    const timers = timersRef.current;
    const removalTimers = removalTimersRef.current;
    return () => {
      timers.forEach((timer) => clearTimeout(timer));
      removalTimers.forEach((timer) => clearTimeout(timer));
    };
  }, []);

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// UI
// ---------------------------------------------------------------------------

const variantStyles: Record<ToastVariant, string> = {
  success:
    'border-emerald-200 bg-white/85 text-emerald-800 dark:border-emerald-500/30 dark:bg-slate-900/90 dark:text-emerald-300',
  error:
    'border-red-200 bg-white/85 text-red-800 dark:border-red-500/30 dark:bg-slate-900/90 dark:text-red-300',
  info:
    'border-slate-200 bg-white/85 text-slate-800 dark:border-slate-600 dark:bg-slate-900/90 dark:text-slate-200',
};

const variantIcons: Record<ToastVariant, ReactNode> = {
  success: <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-500" />,
  error: <AlertCircle className="h-5 w-5 shrink-0 text-red-500" />,
  info: <Info className="h-5 w-5 shrink-0 text-brand-500" />,
};

function ToastContainer({
  toasts,
  onDismiss,
}: {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
}) {
  const { t } = useLanguage();

  if (toasts.length === 0) return null;

  return (
    <div className="pointer-events-none fixed inset-0 z-[9999] flex flex-col items-stretch gap-3 p-4 pt-16 sm:items-end">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role={toast.variant === 'error' ? 'alert' : 'status'}
          aria-live={toast.variant === 'error' ? 'assertive' : 'polite'}
          className={`pointer-events-auto flex w-full items-start gap-3 rounded-xl border py-3 pl-4 pr-2 shadow-lg backdrop-blur-xl sm:max-w-sm ${
            variantStyles[toast.variant]
          } ${toast.exiting ? 'toast-slide-out' : 'toast-slide-in'}`}
        >
          <span className="mt-2 sm:mt-0">{variantIcons[toast.variant]}</span>
          <p className="min-w-0 flex-1 self-center text-sm font-medium leading-snug">{toast.message}</p>
          <button
            type="button"
            onClick={() => onDismiss(toast.id)}
            aria-label={t('common.dismissNotification')}
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg opacity-70 transition hover:bg-black/5 hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:hover:bg-white/10 dark:focus-visible:ring-offset-slate-950"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  );
}
