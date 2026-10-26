import { useLanguage } from '../i18n/LanguageProvider';

type AppLoadingScreenProps = {
  subtitle?: string;
};

/**
 * Shown while the session is being resolved, immediately before a real page
 * renders. It deliberately reuses the app's own page ground rather than its own
 * gradient, so the hand-off to the loaded page is a content change instead of a
 * background change.
 */
export function AppLoadingScreen({ subtitle }: AppLoadingScreenProps) {
  const { t } = useLanguage();

  return (
    <div className="bg-soft-mesh dark:bg-soft-mesh-dark flex min-h-screen items-center justify-center bg-slate-50 px-6 dark:bg-slate-950">
      <div className="flex flex-col items-center text-center">
        <img
          src="/evodiagram.svg"
          alt=""
          aria-hidden="true"
          className="h-11 w-11 dark:hidden"
        />
        <img
          src="/evodiagram-dark.svg"
          alt=""
          aria-hidden="true"
          className="hidden h-11 w-11 dark:block"
        />

        <p className="mt-5 text-sm font-semibold text-slate-800 dark:text-slate-100">
          {t('common.loading')}
        </p>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          {subtitle ?? t('common.preparingWorkspace')}
        </p>

        {/* A track that fills and recedes: honest about being indeterminate,
            unlike a progress bar that implies a known percentage. */}
        <div
          role="status"
          aria-label={t('common.loading')}
          className="mt-5 h-0.5 w-32 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800"
        >
          <div className="app-loading-track h-full w-1/3 rounded-full bg-brand-500 dark:bg-brand-400" />
        </div>
      </div>
    </div>
  );
}

export default AppLoadingScreen;
