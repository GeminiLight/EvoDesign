import { BROWSER_MODE, openModelSettings } from '../services/browser/runtime';
import { useState, useRef, useEffect } from 'react';
import type { MouseEvent as ReactMouseEvent, ReactNode } from 'react';
import { ArrowUpRight, Bell, Bot, CheckCircle2, ChevronRight, CircleHelp, Cloud, Database, Folder, Home, Lightbulb, Languages, LogOut, Menu, Monitor, Moon, Settings2, Sparkles, Sun, UserRound, X } from 'lucide-react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useLanguage } from '../i18n/LanguageProvider';
import { useBackendAuth } from '../features/auth/BackendAuthProvider';
import { rememberAuthReturnTo } from '../features/auth/authRedirect';
import { readLocalStorage, writeLocalStorage } from '../utils/safeLocalStorage';
import { ChoiceSelect } from './ChoiceSelect';
import { useBrowserModelLabel } from '../hooks/useBrowserModelLabel';

const navBaseClass = 'relative inline-flex min-h-10 min-w-11 items-center justify-center rounded-lg px-3 text-sm font-medium transition-colors';
const navActiveClass = 'bg-brand-50 font-semibold text-brand-700 dark:bg-brand-500/15 dark:text-brand-300';
const navInactiveClass = 'text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-slate-100 after:absolute after:bottom-1 after:left-0 after:right-0 after:h-0.5 after:scale-x-0 after:rounded-full after:bg-brand-300 after:transition-transform hover:after:scale-x-100';
type ThemeMode = 'dark' | 'light' | 'system';
const LOGO_ASSET_VERSION = '20260303';

type HeaderProps = {
  children?: ReactNode;
  workspaceTabs?: ReactNode;
  variant?: 'app' | 'landing' | 'studio';
  onEnterGuest?: (prompt?: string) => void;
  onEnterEmailAuth?: () => void;
  authTransitionBlocked?: boolean;
  onAuthTransitionBlocked?: () => void;
  onBeforeNavigate?: (to: string) => boolean | Promise<boolean>;
  onOpenSettings?: () => void;
};

export const Header = ({
  children,
  workspaceTabs,
  variant = 'app',
  onEnterGuest,
  onEnterEmailAuth,
  authTransitionBlocked = false,
  onAuthTransitionBlocked,
  onBeforeNavigate,
  onOpenSettings,
}: HeaderProps) => {
  const isStudio = variant === 'studio';
  const isApp = variant !== 'landing';
  const { t, language, setLanguage } = useLanguage();
  const currentModelLabel = useBrowserModelLabel(t);
  const { user, signOut } = useBackendAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const pageTitle = isStudio ? (location.pathname === '/projects' || location.pathname === '/dashboard' ? t('nav.projects')
    : ['/insights', '/insight', '/gallery'].includes(location.pathname) ? t('nav.gallery')
      : location.pathname === '/dna' ? 'DNA' : '') : '';

  const [userOpen, setUserOpen] = useState(false);
  const [themeMode, setThemeMode] = useState<ThemeMode>('system');
  const [isDarkMode, setIsDarkMode] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const logoSrc = `${isDarkMode ? '/evodiagram-dark.svg' : '/evodiagram.svg'}?v=${LOGO_ASSET_VERSION}`;

  const userRef = useRef<HTMLDivElement>(null);
  const userButtonRef = useRef<HTMLButtonElement>(null);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const userKeyboardOpenRef = useRef(false);
  const notificationsRef = useRef<HTMLDivElement>(null);
  const notificationsButtonRef = useRef<HTMLButtonElement>(null);
  const notificationsPanelRef = useRef<HTMLDivElement>(null);
  const mobileNavButtonRef = useRef<HTMLButtonElement>(null);
  const mobileNavRef = useRef<HTMLElement>(null);
  const navigationGuardInFlightRef = useRef(false);

  const applyTheme = (mode: ThemeMode) => {
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const nextDark = mode === 'dark' || (mode === 'system' && prefersDark);
    setIsDarkMode(nextDark);
    document.documentElement.classList.toggle('dark', nextDark);
  };

  useEffect(() => {
    const storedTheme = readLocalStorage('smartdiagram_theme');
    const nextMode: ThemeMode = storedTheme === 'dark' || storedTheme === 'light' || storedTheme === 'system' ? storedTheme : 'system';
    setThemeMode(nextMode);
    applyTheme(nextMode);
  }, []);

  useEffect(() => {
    if (themeMode !== 'system') return;

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handleSystemThemeChange = () => applyTheme('system');

    mediaQuery.addEventListener('change', handleSystemThemeChange);
    return () => mediaQuery.removeEventListener('change', handleSystemThemeChange);
  }, [themeMode]);

  useEffect(() => {
    const handleClickOutside = (event: Event) => {
      if (event.target instanceof Node && userRef.current && !userRef.current.contains(event.target)) setUserOpen(false);
      if (notificationsRef.current && !notificationsRef.current.contains(event.target as Node)) setNotificationsOpen(false);
    };
    document.addEventListener('pointerdown', handleClickOutside);
    document.addEventListener('focusin', handleClickOutside);
    return () => {
      document.removeEventListener('pointerdown', handleClickOutside);
      document.removeEventListener('focusin', handleClickOutside);
    };
  }, []);

  useEffect(() => {
    if (!userOpen) return;

    const frameId = window.requestAnimationFrame(() => {
      if (userKeyboardOpenRef.current) {
        userMenuRef.current?.querySelector<HTMLElement>('[aria-pressed="true"]')?.focus({ preventScroll: true });
      }
    });

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopPropagation();
      setUserOpen(false);
      userButtonRef.current?.focus();
    };

    document.addEventListener('keydown', handleEscape);
    return () => {
      window.cancelAnimationFrame(frameId);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [userOpen]);

  useEffect(() => {
    if (!notificationsOpen) return;

    const frameId = window.requestAnimationFrame(() => {
      notificationsPanelRef.current?.querySelector<HTMLElement>('button, [href]')?.focus();
    });

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setNotificationsOpen(false);
      notificationsButtonRef.current?.focus();
    };

    document.addEventListener('keydown', handleEscape);
    return () => {
      window.cancelAnimationFrame(frameId);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [notificationsOpen]);

  useEffect(() => {
    if (!mobileNavOpen) return;

    const frameId = window.requestAnimationFrame(() => {
      mobileNavRef.current?.querySelector<HTMLElement>('a, button')?.focus();
    });

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setMobileNavOpen(false);
      mobileNavButtonRef.current?.focus();
    };
    const dismissOutside = (event: Event) => {
      if (event.target instanceof Node && !mobileNavRef.current?.contains(event.target)
        && !mobileNavButtonRef.current?.contains(event.target)) setMobileNavOpen(false);
    };

    document.addEventListener('keydown', handleEscape);
    document.addEventListener('pointerdown', dismissOutside);
    document.addEventListener('focusin', dismissOutside);
    return () => {
      window.cancelAnimationFrame(frameId);
      document.removeEventListener('keydown', handleEscape);
      document.removeEventListener('pointerdown', dismissOutside);
      document.removeEventListener('focusin', dismissOutside);
    };
  }, [mobileNavOpen]);

  const handleThemeChange = (mode: ThemeMode) => {
    setThemeMode(mode);
    applyTheme(mode);
    writeLocalStorage('smartdiagram_theme', mode);
  };

  const closeTransientPanels = () => {
    setMobileNavOpen(false);
    setUserOpen(false);
    setNotificationsOpen(false);
  };

  const canLeaveFor = async (to: string): Promise<boolean> => {
    if (to === location.pathname || !onBeforeNavigate) {
      return true;
    }

    if (navigationGuardInFlightRef.current) {
      return false;
    }

    navigationGuardInFlightRef.current = true;
    try {
      return await onBeforeNavigate(to);
    } finally {
      navigationGuardInFlightRef.current = false;
    }
  };

  const requestNavigation = async (
    to: string,
    options?: { replace?: boolean; state?: unknown },
  ): Promise<boolean> => {
    const canNavigate = await canLeaveFor(to);
    if (!canNavigate) return false;

    navigate(to, options);
    return true;
  };

  const handleNavLinkClick = (to: string, options?: { closeMobile?: boolean }) => (
    event: ReactMouseEvent<HTMLAnchorElement>,
  ) => {
    const isPlainPrimaryClick = (
      event.button === 0
      && !event.metaKey
      && !event.altKey
      && !event.ctrlKey
      && !event.shiftKey
      && !event.defaultPrevented
      && (!event.currentTarget.target || event.currentTarget.target === '_self')
    );

    if (!isPlainPrimaryClick) {
      return;
    }

    if (!onBeforeNavigate) {
      if (options?.closeMobile) setMobileNavOpen(false);
      return;
    }

    event.preventDefault();
    void (async () => {
      const didNavigate = await requestNavigation(to);
      if (didNavigate && options?.closeMobile) {
        setMobileNavOpen(false);
      }
    })();
  };

  const handleSignOut = async () => {
    if (authTransitionBlocked) {
      setUserOpen(false);
      onAuthTransitionBlocked?.();
      return;
    }

    const didSave = await canLeaveFor('/home');
    if (!didSave) return;

    setUserOpen(false);
    setMobileNavOpen(false);
    await signOut();
    navigate('/home', { replace: true, state: { signedOut: true } });
  };

  const handleLoginToSync = async () => {
    if (authTransitionBlocked) {
      setUserOpen(false);
      setNotificationsOpen(false);
      setMobileNavOpen(false);
      onAuthTransitionBlocked?.();
      return;
    }

    const returnTo = `${location.pathname}${location.search}${location.hash}`;
    const safeReturnTo = rememberAuthReturnTo(returnTo) ?? '/home';
    const didSave = await canLeaveFor('/auth/email');
    if (!didSave) return;

    navigate('/auth/email', { state: { returnTo: safeReturnTo } });
    closeTransientPanels();
  };

  const handleNotificationNavigate = (to: string) => {
    void (async () => {
      const didNavigate = await requestNavigation(to);
      if (didNavigate) closeTransientPanels();
    })();
  };

  return (
    <header className={`${isStudio ? 'studio-header' : ''} ${workspaceTabs ? 'workspace-header' : ''} sticky top-0 z-50 border-b backdrop-blur-2xl transition-colors duration-300 ${variant === 'landing' ? 'border-slate-200/50 dark:border-white/5 bg-white/50 dark:bg-slate-950/50 backdrop-blur-xl' : 'border-slate-200 bg-white/95 dark:border-slate-800 dark:bg-slate-950/95'}`}>
      <div className={`header-inner mx-auto flex h-14 items-center justify-between gap-2 px-3 sm:px-6 lg:px-8 ${variant === 'landing' ? 'max-w-7xl' : ''}`}>
        <div className="header-leading flex min-w-0 items-center gap-4 md:gap-8">
          <button
            type="button"
            aria-label="EvoDesign"
            title={isStudio ? 'EvoDesign' : undefined}
            onClick={() => {
              void (async () => {
                const didNavigate = await requestNavigation(variant === 'landing' ? '/' : '/home');
                if (didNavigate) closeTransientPanels();
              })();
            }}
            className="header-brand flex min-h-11 min-w-11 items-center gap-2 rounded-xl px-1 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300"
          >
            <img
              src={logoSrc}
              alt="EvoDesign Logo"
              className="header-logo h-8 w-8"
            />
            <span className={`header-wordmark hidden font-bold tracking-tight text-slate-900 dark:text-slate-100 sm:inline ${variant === 'landing' ? 'text-xl dark:text-white' : 'text-lg'}`}>Evo<span className="text-brand-600 dark:text-brand-400">Design</span></span>
          </button>

          {pageTitle && <h1 className="header-page-title">{pageTitle}</h1>}
          {isApp && (
            <nav className={`header-nav hidden md:flex items-center gap-1 ${isStudio ? 'studio-rail' : ''}`} aria-label={t('nav.menu')}>
              <NavLink to="/home" onClick={handleNavLinkClick('/home')} className={({ isActive }) => `${navBaseClass} ${isActive ? navActiveClass : navInactiveClass}`}>
                {isStudio && <Home size={22} strokeWidth={1.6} aria-hidden="true" />}<span>{t('nav.home')}</span>
              </NavLink>
              <NavLink to="/projects" onClick={handleNavLinkClick('/projects')} className={({ isActive }) => `${navBaseClass} ${isActive ? navActiveClass : navInactiveClass}`}>
                {isStudio && <Folder size={22} strokeWidth={1.6} aria-hidden="true" />}<span>{t('nav.projects')}</span>
              </NavLink>
              <NavLink to="/insights" onClick={handleNavLinkClick('/insights')} className={({ isActive }) => `${navBaseClass} ${isActive ? navActiveClass : navInactiveClass}`}>
                {isStudio && <Lightbulb size={22} strokeWidth={1.6} aria-hidden="true" />}<span>{t('nav.gallery')}</span>
              </NavLink>
              <NavLink to="/dna" onClick={handleNavLinkClick('/dna')} className={({ isActive }) => `${navBaseClass} ${isActive ? navActiveClass : navInactiveClass}`}>
                {isStudio && <Database size={22} strokeWidth={1.6} aria-hidden="true" />}<span>{t('nav.dna')}</span>
              </NavLink>
            </nav>
          )}
        </div>

          {workspaceTabs && <div className="workspace-header-tabs">{workspaceTabs}</div>}
          {isApp && (
            <button
              ref={mobileNavButtonRef}
              type="button"
              onClick={() => {
                setMobileNavOpen((prev) => !prev);
                setUserOpen(false);
                setNotificationsOpen(false);
              }}
              className="flex h-11 w-11 items-center justify-center rounded-full border border-slate-200/70 bg-white/70 text-slate-600 transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 md:hidden dark:border-white/10 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:bg-slate-800 dark:focus-visible:ring-offset-slate-950"
              aria-label={t('nav.menu')}
              aria-expanded={mobileNavOpen}
              aria-controls="app-mobile-nav"
            >
              {mobileNavOpen ? <X className="h-4.5 w-4.5" /> : <Menu className="h-4.5 w-4.5" />}
            </button>
          )}

        <div className="header-actions flex min-w-0 items-center gap-2 sm:gap-3">
          {/* Landing variant: theme toggle + language + guest/sign-in */}
          {variant === 'landing' && (
            <>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    const nextDark = !isDarkMode;
                    handleThemeChange(nextDark ? 'dark' : 'light');
                  }}
                  className="tap-target flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 dark:border-white/10 bg-slate-100/50 dark:bg-white/5 text-slate-600 dark:text-slate-300 transition-all hover:bg-slate-200 dark:hover:bg-white/10 hover:text-slate-900 dark:hover:text-white focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-1"
                  aria-label={isDarkMode ? t('common.themeLight') : t('common.themeDark')}
                  title={isDarkMode ? t('common.themeLight') : t('common.themeDark')}
                >
                  {isDarkMode ? <Sun className="h-4.5 w-4.5" /> : <Moon className="h-4.5 w-4.5" />}
                </button>
                <button
                  type="button"
                  onClick={() => setLanguage(language === 'zh' ? 'en' : 'zh')}
                  className="tap-target flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 dark:border-white/10 bg-slate-100/50 dark:bg-white/5 text-slate-600 dark:text-slate-300 transition-all hover:bg-slate-200 dark:hover:bg-white/10 hover:text-slate-900 dark:hover:text-white focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-1"
                  aria-label={language === 'zh' ? t('common.switchToEnglish') : t('common.switchToChinese')}
                  title={language === 'zh' ? t('common.switchToEnglish') : t('common.switchToChinese')}
                >
                  <Languages className="h-4.5 w-4.5" />
                </button>
              </div>
              {onEnterGuest && (
                <button
                  type="button"
                  onClick={() => onEnterGuest()}
                  className="hidden min-h-11 items-center rounded-lg border border-slate-200 dark:border-white/10 bg-slate-100/50 dark:bg-white/5 px-4 py-2.5 text-sm font-medium text-slate-600 dark:text-slate-300 transition-all hover:bg-slate-200 dark:hover:bg-white/10 hover:text-slate-900 dark:hover:text-white focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-1 sm:inline-flex"
                >
                  {t('landing.tryAsGuest')}
                </button>
              )}
              {onEnterEmailAuth && !BROWSER_MODE && (
                <button
                  type="button"
                  onClick={onEnterEmailAuth}
                  className="inline-flex min-h-11 items-center rounded-lg bg-slate-900 dark:bg-white px-3 py-2.5 text-sm font-medium text-white dark:text-slate-900 transition-all hover:bg-slate-800 dark:hover:bg-slate-200 focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-1 sm:px-4"
                >
                  {t('common.signIn')}
                </button>
              )}
            </>
          )}

          {/* App variant: children + notifications + user menu */}
          {isApp && (
            <>
          {children}
          {BROWSER_MODE && <button type="button" onClick={() => { closeTransientPanels(); openModelSettings(); }} aria-label={`${t('browser.modelSettings')}: ${currentModelLabel}`} title={currentModelLabel} aria-haspopup="dialog" className={isStudio ? 'header-model-trigger home-settings-button' : 'tool-button min-h-10 gap-2 px-3'}><Bot size={isStudio ? 20 : 16} strokeWidth={1.7} aria-hidden="true" /><span className={isStudio ? 'header-model-label' : 'hidden sm:inline'}>{currentModelLabel}</span></button>}

          {!BROWSER_MODE && <div className="relative" ref={notificationsRef}>
            <button
              ref={notificationsButtonRef}
              type="button"
              aria-label={t('nav.notifications')}
              aria-haspopup="dialog"
              aria-expanded={notificationsOpen}
              aria-controls="header-notifications-panel"
              onClick={() => {
                setNotificationsOpen((prev) => !prev);
                setUserOpen(false);
                setMobileNavOpen(false);
              }}
              className="tap-target relative flex h-9 w-9 items-center justify-center rounded-full border border-slate-200/70 bg-white/70 text-slate-600 transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:border-white/10 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:bg-slate-800 dark:focus-visible:ring-offset-slate-950"
            >
              <Bell className="h-4.5 w-4.5" />
              <span className={`absolute right-2 top-2 h-2 w-2 rounded-full ring-2 ring-white dark:ring-slate-900 ${user ? 'bg-emerald-400' : 'bg-amber-400'}`} />
            </button>

            {notificationsOpen && (
              <div
                id="header-notifications-panel"
                ref={notificationsPanelRef}
                role="dialog"
                aria-label={t('notifications.title')}
                className="fixed left-3 right-3 top-16 z-50 mt-0 w-auto origin-top surface-overlay rounded-2xl p-3 shadow-e4 focus:outline-none dark:shadow-e4-dark sm:absolute sm:left-auto sm:right-0 sm:top-auto sm:mt-2 sm:w-[min(22rem,calc(100vw-1.5rem))] sm:origin-top-right"
              >
                <div className="flex items-start justify-between gap-3 px-1 pb-2">
                  <div>
                    <p className="text-xs font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">{t('notifications.title')}</p>
                    <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {user ? t('notifications.allCaughtUp') : t('notifications.guestTitle')}
                    </h2>
                  </div>
                  <button
                    type="button"
                    onClick={() => setNotificationsOpen(false)}
                    aria-label={t('common.dismissNotification')}
                    className="tap-target flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-slate-400 transition hover:bg-white hover:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>

                {user ? (
                  <div className="space-y-2">
                    <button
                      type="button"
                      onClick={() => handleNotificationNavigate('/projects')}
                      className="flex w-full items-start gap-3 rounded-xl border border-slate-200/70 bg-white/70 px-3 py-3 text-left transition hover:border-brand-200 hover:bg-brand-50/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 dark:border-slate-700 dark:bg-slate-900/70 dark:hover:border-brand-500/40 dark:hover:bg-brand-500/10"
                    >
                      <Cloud className="mt-0.5 h-4.5 w-4.5 shrink-0 text-brand-500 dark:text-brand-300" />
                      <span className="min-w-0">
                        <span className="block text-sm font-semibold text-slate-800 dark:text-slate-100">{t('notifications.syncTitle')}</span>
                        <span className="mt-0.5 block text-xs leading-relaxed text-slate-500 dark:text-slate-400">{t('notifications.syncDesc')}</span>
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => handleNotificationNavigate('/dna')}
                      className="flex w-full items-start gap-3 rounded-xl border border-slate-200/70 bg-white/70 px-3 py-3 text-left transition hover:border-brand-200 hover:bg-brand-50/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 dark:border-slate-700 dark:bg-slate-900/70 dark:hover:border-brand-500/40 dark:hover:bg-brand-500/10"
                    >
                      <Sparkles className="mt-0.5 h-4.5 w-4.5 shrink-0 text-violet-500 dark:text-violet-300" />
                      <span className="min-w-0">
                        <span className="block text-sm font-semibold text-slate-800 dark:text-slate-100">{t('notifications.dnaTitle')}</span>
                        <span className="mt-0.5 block text-xs leading-relaxed text-slate-500 dark:text-slate-400">{t('notifications.dnaDesc')}</span>
                      </span>
                    </button>
                    <div className="flex items-center gap-2 rounded-xl border border-emerald-200/70 bg-emerald-50/70 px-3 py-2 text-xs font-medium text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
                      <CheckCircle2 className="h-4 w-4 shrink-0" />
                      {t('notifications.noAction')}
                    </div>
                  </div>
                ) : (
                  <div className="rounded-xl border border-amber-200/70 bg-amber-50/75 p-3 dark:border-amber-500/30 dark:bg-amber-500/10">
                    <p className="text-sm font-semibold text-amber-900 dark:text-amber-200">{t('notifications.guestSyncTitle')}</p>
                    <p className="mt-1 text-xs leading-relaxed text-amber-700 dark:text-amber-300">{t('notifications.guestSyncDesc')}</p>
                    <button
                      type="button"
                      onClick={BROWSER_MODE ? () => { setUserOpen(false); openModelSettings(); } : handleLoginToSync}
                      aria-disabled={authTransitionBlocked}
                      title={authTransitionBlocked ? t('workspace.authTransitionBlocked') : undefined}
                      className={`mt-3 min-h-11 w-full rounded-xl px-4 py-2.5 text-sm font-semibold text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-900 ${
                        authTransitionBlocked
                          ? 'cursor-not-allowed bg-slate-400 hover:bg-slate-400 dark:bg-slate-700 dark:hover:bg-slate-700'
                          : 'bg-brand-600 hover:bg-brand-500'
                      }`}
                    >
                      {BROWSER_MODE ? t('browser.modelSettings') : t('common.logInToSync')}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>

          }
          <div className="relative ml-2" ref={userRef}>
            <button
              ref={userButtonRef}
              type="button"
              aria-label={t(BROWSER_MODE ? 'nav.preferences' : 'nav.accountPreferences')}
              title={t(BROWSER_MODE ? 'nav.preferences' : 'nav.accountPreferences')}
              aria-haspopup="dialog"
              aria-expanded={userOpen}
              aria-controls="header-user-menu"
              onClick={event => {
                userKeyboardOpenRef.current = event.detail === 0;
                setUserOpen((prev) => !prev);
                setNotificationsOpen(false);
                setMobileNavOpen(false);
              }}
              onKeyDown={event => {
                if (event.key === 'ArrowDown') {
                  event.preventDefault();
                  userKeyboardOpenRef.current = true;
                  setUserOpen(true);
                  setNotificationsOpen(false);
                  setMobileNavOpen(false);
                }
              }}
              className={`${BROWSER_MODE ? 'header-preferences-trigger home-settings-button' : 'header-user-trigger tap-target flex min-h-9 items-center gap-2 rounded-full border border-slate-200/70 bg-white/70 py-1 pl-1 pr-2.5 transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:border-white/10 dark:bg-slate-900/70 dark:hover:bg-slate-800 dark:focus-visible:ring-offset-slate-950'}`}
            >
              {BROWSER_MODE ? <Settings2 size={20} strokeWidth={1.7} aria-hidden="true" /> : <>
              <div className={`flex h-7 w-7 items-center justify-center rounded-full text-white text-xs font-bold ${user ? 'bg-purple-500' : 'bg-slate-600'}`}>
                {user ? (user.username || user.email || 'U')[0].toUpperCase() : 'G'}
              </div>
              <span className="hidden max-w-[140px] truncate text-sm font-medium text-slate-700 sm:block dark:text-slate-200">
                {user ? (user.username || user.email?.split('@')[0]) : (BROWSER_MODE ? t('browser.localMode') : t('common.guestMode'))}
              </span>
              <svg className="hidden h-4 w-4 text-slate-400 sm:block dark:text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
              </>}
            </button>

            {userOpen && (
              <div id="header-user-menu" ref={userMenuRef} role="dialog" aria-labelledby="header-preferences-title"
                className="header-preferences-panel">
                <div className="header-preferences-heading">
                  <h2 id="header-preferences-title">{t(BROWSER_MODE ? 'nav.preferences' : 'nav.accountPreferences')}</h2>
                  <button type="button" className="header-preferences-close" aria-label={t('common.close')}
                    onClick={() => { setUserOpen(false); userButtonRef.current?.focus(); }}><X size={16} aria-hidden="true" /></button>
                </div>

                {!BROWSER_MODE && user && <div className="header-account-summary">
                  <span className="header-account-avatar" aria-hidden="true">{(user.username || user.email || 'U')[0].toUpperCase()}</span>
                  <div><strong>{user.username || user.email?.split('@')[0]}</strong><span>{user.email}</span></div>
                </div>}

                <div className="header-preference-row">
                  <span>{t('settings.appearance')}</span>
                  <div className="header-theme-options" role="group" aria-label={t('common.theme')}>
                    {([{ mode: 'light', Icon: Sun, label: 'common.themeLight' }, { mode: 'dark', Icon: Moon, label: 'common.themeDark' },
                      { mode: 'system', Icon: Monitor, label: 'common.themeSystem' }] as const).map(({ mode, Icon, label }) => (
                      <button key={mode} type="button" onClick={() => handleThemeChange(mode)}
                        aria-label={t(label)} aria-pressed={themeMode === mode} title={t(label)}>
                        <Icon size={17} strokeWidth={1.7} aria-hidden="true" />
                      </button>
                    ))}
                  </div>
                </div>
                <div className="header-preference-row">
                  <label htmlFor="header-language">{t('settings.language')}</label>
                  <ChoiceSelect id="header-language" label={t('settings.language')} value={language} menuWidth={144} placement="below" align="end"
                    options={[{ value: 'zh', label: '简体中文', lang: 'zh' }, { value: 'en', label: 'English', lang: 'en' }]}
                    onChange={value => setLanguage(value === 'zh' ? 'zh' : 'en')} />
                </div>

                <div className="header-preferences-links">
                  <button type="button" onClick={() => handleNotificationNavigate('/dna')}>
                    <Database size={17} aria-hidden="true" /><span>{language === 'zh' ? 'DNA 设计偏好' : 'DNA preferences'}</span><ChevronRight size={13} className="ml-auto" aria-hidden="true" />
                  </button>
                  {onOpenSettings && <button type="button" onClick={() => {
                    setUserOpen(false);
                    userButtonRef.current?.focus();
                    onOpenSettings();
                  }}><Settings2 size={17} aria-hidden="true" /><span>{t('settings.canvasOptions')}</span></button>}
                  <a href="https://github.com/GeminiLight/EvoDesign" target="_blank" rel="noreferrer">
                    <CircleHelp size={17} aria-hidden="true" /><span>{t('settings.helpFeedback')}</span><ArrowUpRight size={13} aria-hidden="true" />
                  </a>
                  {!BROWSER_MODE && <button type="button" onClick={() => { void (user ? handleSignOut() : handleLoginToSync()); }}
                    aria-disabled={authTransitionBlocked} title={authTransitionBlocked ? t('workspace.authTransitionBlocked') : undefined}>
                    {user ? <LogOut size={17} aria-hidden="true" /> : <UserRound size={17} aria-hidden="true" />}<span>{t(user ? 'common.signOut' : 'common.logInToSync')}</span>
                  </button>}
                </div>
              </div>
            )}
          </div>
            </>
          )}
        </div>
      </div>
      {isApp && mobileNavOpen && (
        <nav ref={mobileNavRef} id="app-mobile-nav" className="border-t border-white/60 bg-white/50 px-4 py-3 backdrop-blur-2xl md:hidden dark:border-white/10 dark:bg-slate-950/55">
          <div className="flex flex-col gap-1">
            <NavLink to="/home" onClick={handleNavLinkClick('/home', { closeMobile: true })} className={({ isActive }) => `flex min-h-11 items-center rounded-lg px-3 py-2 text-sm font-medium transition-colors ${isActive ? 'bg-brand-50 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300' : 'text-slate-600 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800'}`}>
              {t('nav.home')}
            </NavLink>
            <NavLink to="/projects" onClick={handleNavLinkClick('/projects', { closeMobile: true })} className={({ isActive }) => `flex min-h-11 items-center rounded-lg px-3 py-2 text-sm font-medium transition-colors ${isActive ? 'bg-brand-50 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300' : 'text-slate-600 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800'}`}>
              {t('nav.projects')}
            </NavLink>
            <NavLink to="/insights" onClick={handleNavLinkClick('/insights', { closeMobile: true })} className={({ isActive }) => `flex min-h-11 items-center rounded-lg px-3 py-2 text-sm font-medium transition-colors ${isActive ? 'bg-brand-50 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300' : 'text-slate-600 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800'}`}>
              {t('nav.gallery')}
            </NavLink>
            <NavLink to="/dna" onClick={handleNavLinkClick('/dna', { closeMobile: true })} className={({ isActive }) => `flex min-h-11 items-center rounded-lg px-3 py-2 text-sm font-medium transition-colors ${isActive ? 'bg-brand-50 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300' : 'text-slate-600 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800'}`}>
              {t('nav.dna')}
            </NavLink>
          </div>
        </nav>
      )}
    </header>
  );
};
