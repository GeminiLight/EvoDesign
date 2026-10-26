import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { AuthPanel } from '../features/auth/AuthPanel';
import { useBackendAuth } from '../features/auth/BackendAuthProvider';
import { consumeAuthReturnTo, rememberAuthReturnTo, resolveAuthReturnTo } from '../features/auth/authRedirect';
import { useLanguage } from '../i18n/LanguageProvider';

const LOGO_ASSET_VERSION = '20260303';

export const EmailAuthPage = () => {
  const { user, loading } = useBackendAuth();
  const { t } = useLanguage();
  const navigate = useNavigate();
  const location = useLocation();
  const [isDarkMode, setIsDarkMode] = useState(false);
  const logoSrc = `${isDarkMode ? '/evodiagram-dark.svg' : '/evodiagram.svg'}?v=${LOGO_ASSET_VERSION}`;
  const stateReturnTo = (location.state as { returnTo?: unknown } | null)?.returnTo;
  const queryReturnTo = new URLSearchParams(location.search).get('returnTo');
  const requestedReturnTo = stateReturnTo ?? queryReturnTo;
  const returnTo = useMemo(
    () => resolveAuthReturnTo(requestedReturnTo, '/home'),
    [requestedReturnTo],
  );
  const backTarget = useMemo(
    () => resolveAuthReturnTo(requestedReturnTo, '/'),
    [requestedReturnTo],
  );

  useEffect(() => {
    if (!loading && user) {
      navigate(consumeAuthReturnTo(returnTo), { replace: true });
    }
  }, [loading, navigate, returnTo, user]);

  useEffect(() => {
    rememberAuthReturnTo(returnTo);
  }, [returnTo]);

  useEffect(() => {
    const storedTheme = localStorage.getItem('smartdiagram_theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const nextDark = storedTheme === 'dark' || (storedTheme === 'system' && prefersDark);
    setIsDarkMode(nextDark);
  }, []);

  return (
    <div className="bg-soft-mesh dark:bg-soft-mesh-dark min-h-screen overflow-x-hidden bg-slate-100 dark:bg-slate-950">
      <main id="main-content" className="mx-auto flex min-h-dvh w-full max-w-6xl items-center justify-center px-4 py-8 sm:px-6 lg:px-8">
        <div className="grid w-full max-w-md items-stretch gap-6 lg:max-w-none lg:grid-cols-[1.05fr_0.95fr]">
          <section className="surface-glass hidden p-8 lg:flex lg:flex-col lg:justify-between">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-white/70 bg-white/65 px-3 py-1 text-xs font-semibold text-slate-600 dark:border-white/10 dark:bg-slate-900/70 dark:text-slate-300">
                {t('auth.account')}
              </div>
              <h2 className="mt-4 font-display text-3xl font-bold tracking-tight text-slate-900 dark:text-slate-100">{t('auth.welcomeTitle')}</h2>
              <p className="mt-3 max-w-md text-sm leading-relaxed text-slate-600 dark:text-slate-400">{t('auth.welcomeSubtitle')}</p>
            </div>

            <div className="mt-6 space-y-4">
              <div className="flex items-start gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600 dark:bg-brand-500/20 dark:text-brand-300">
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{t('auth.featureSpeedTitle')}</p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">{t('auth.featureSpeedDesc')}</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600 dark:bg-indigo-500/20 dark:text-indigo-300">
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z" /></svg>
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{t('auth.featureSyncTitle')}</p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">{t('auth.featureSyncDesc')}</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-purple-50 text-purple-600 dark:bg-purple-500/20 dark:text-purple-300">
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" /></svg>
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{t('auth.featureDnaTitle')}</p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">{t('auth.featureDnaDesc')}</p>
                </div>
              </div>
            </div>

            <div className="mt-8 rounded-2xl border border-white/70 bg-white/60 p-4 backdrop-blur-md dark:border-white/10 dark:bg-slate-900/70">
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/70 bg-white/70 p-2 shadow-[0_10px_20px_rgba(148,163,184,0.2)] dark:border-white/10 dark:bg-slate-900/75 dark:shadow-[0_10px_20px_rgba(2,6,23,0.45)]">
                  <img src={logoSrc} alt="EvoDesign Logo" className="h-7 w-7" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">EvoDesign</p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">{t('auth.tagline')}</p>
                </div>
              </div>
            </div>
          </section>

          <div className="surface-glass w-full p-6 sm:p-7">
          <button
            type="button"
            onClick={() => navigate(backTarget, { replace: true })}
            aria-label={t('common.back')}
            className="mb-3 inline-flex min-h-11 items-center gap-1 rounded-lg px-3 py-2 text-sm font-semibold text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200 dark:focus-visible:ring-offset-slate-950"
          >
            ← {t('common.back')}
          </button>

          <div className="mb-5 text-center">
            <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-2xl border border-white/70 bg-white/70 p-1.5 shadow-[0_10px_24px_rgba(148,163,184,0.2)] backdrop-blur-md dark:border-white/10 dark:bg-slate-900/75 dark:shadow-[0_10px_24px_rgba(2,6,23,0.45)]">
              <img src={logoSrc} alt="EvoDesign Logo" className="h-8 w-8" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-800 dark:text-slate-100">{t('auth.continueToEvo')}</h1>
            <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{t('auth.emailPageTitle')}</p>
            {returnTo !== '/home' && (
              <p className="mt-1 text-xs font-medium text-brand-600 dark:text-brand-300">{t('auth.returnToHint')}</p>
            )}
          </div>

          <AuthPanel returnTo={returnTo} />
          </div>
        </div>
      </main>
    </div>
  );
};
