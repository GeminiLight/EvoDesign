import { ArrowLeft, Compass, Home } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Header } from '../components/Header';
import { useBackendAuth } from '../features/auth/BackendAuthProvider';
import { useLanguage } from '../i18n/LanguageProvider';
import { BROWSER_MODE } from '../services/browser/runtime';

export const NotFoundPage = () => {
  const navigate = useNavigate();
  const { user } = useBackendAuth();
  const { t } = useLanguage();

  return (
    <div className="studio-shell studio-not-found flex min-h-screen flex-col">
      <Header variant="studio" />
      <main id="main-content" className="studio-page-main flex flex-1 items-center justify-center">
        <section className="studio-recovery-content w-full p-6 text-center sm:p-10">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-300">
            <Compass className="h-7 w-7" />
          </div>
          <p className="mt-6 text-sm font-semibold text-brand-600 dark:text-brand-300">404</p>
          <h1 className="mt-2 font-display text-3xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
            {t('common.pageNotFoundTitle')}
          </h1>
          <p className="mx-auto mt-3 max-w-lg text-sm leading-relaxed text-slate-500 dark:text-slate-400">
            {t('common.pageNotFoundDesc')}
          </p>
          <div className="mt-7 flex flex-col justify-center gap-3 sm:flex-row">
            <button
              type="button"
              onClick={() => navigate('/home', { replace: true })}
              className="studio-primary gap-2"
            >
              <Home className="h-4 w-4" />
              {t('common.goHome')}
            </button>
            <button
              type="button"
              onClick={() => navigate(-1)}
              className="studio-secondary gap-2 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300"
            >
              <ArrowLeft className="h-4 w-4" />
              {t('common.back')}
            </button>
            {!user && !BROWSER_MODE && (
              <button
                type="button"
                onClick={() => navigate('/', { replace: true })}
                className="studio-secondary dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300"
              >
                {t('common.goLanding')}
              </button>
            )}
          </div>
        </section>
      </main>
    </div>
  );
};
