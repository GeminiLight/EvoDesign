import { useRouteError } from 'react-router-dom';
import { useLanguage } from '../i18n/LanguageProvider';

export function RouteErrorScreen() {
  const error = useRouteError();
  const { t } = useLanguage();
  const chunkFailed = error instanceof Error && (
    error.name === 'ChunkLoadError'
    || /(?:failed to fetch|error loading) dynamically imported module|importing a module script failed|unable to preload css/i.test(error.message)
  );

  return (
    <main id="main-content" className="bg-soft-mesh dark:bg-soft-mesh-dark flex min-h-screen items-center justify-center bg-slate-50 px-6 dark:bg-slate-950" aria-labelledby="route-error-title">
      <div className="max-w-md text-center">
        <h1 id="route-error-title" className="text-xl font-semibold text-slate-900 dark:text-slate-100">
          {t(chunkFailed ? 'common.routeAssetsUnavailable' : 'common.routeLoadFailed')}
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-slate-600 dark:text-slate-400">
          {t(chunkFailed ? 'common.routeAssetsRecovery' : 'common.routeLoadRecovery')}
        </p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-4">
          <button type="button" onClick={() => window.location.reload()} className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">
            {t('common.reloadPage')}
          </button>
          <a href="/home" className="px-2 py-2 text-sm font-medium text-slate-700 underline dark:text-slate-200">
            {t('nav.home')}
          </a>
        </div>
      </div>
    </main>
  );
}
