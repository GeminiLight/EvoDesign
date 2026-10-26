import { useCallback, useEffect, useRef, useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { useBackendAuth } from './BackendAuthProvider';
import { rememberAuthReturnTo } from './authRedirect';
import { useLanguage } from '../../i18n/LanguageProvider';

type AuthPanelProps = {
  returnTo?: string;
};

export const AuthPanel = ({ returnTo }: AuthPanelProps) => {
  const { signInWithPassword, signUpWithPassword, signInWithOAuth, loading } = useBackendAuth();
  const { t, language } = useLanguage();
  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<'email' | 'password' | 'verificationCode' | 'firstName' | 'lastName', string>>>({});
  const [busy, setBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showVerificationCode, setShowVerificationCode] = useState(false);
  const [focusVerificationCodeOnShow, setFocusVerificationCodeOnShow] = useState(false);
  const verificationCodeInputRef = useRef<HTMLInputElement>(null);

  const requiredText = language === 'zh' ? '此项为必填' : 'This field is required';
  const invalidEmailText = language === 'zh' ? '请输入有效邮箱地址' : 'Please enter a valid email address';
  const normalizedVerificationCode = verificationCode.trim();
  const isSubmitting = busy || loading;
  const emailErrorId = 'auth-email-error';
  const passwordErrorId = 'auth-password-error';
  const verificationCodeErrorId = 'auth-verification-code-error';
  const verificationCodeHintId = 'auth-verification-code-hint';
  const verificationCodeInputId = 'auth-verification-code';
  const formErrorId = 'auth-form-error';
  const isVisibleVerificationCodeEmpty = mode === 'signup' && showVerificationCode && !normalizedVerificationCode;

  const normalizeVerificationCode = (raw: string) => raw.trim();

  useEffect(() => {
    if (!showVerificationCode || !focusVerificationCodeOnShow) return;

    const frameId = window.requestAnimationFrame(() => {
      verificationCodeInputRef.current?.focus();
      setFocusVerificationCodeOnShow(false);
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [focusVerificationCodeOnShow, showVerificationCode]);

  const validateFields = useCallback(() => {
    const nextErrors: Partial<Record<'email' | 'password' | 'verificationCode' | 'firstName' | 'lastName', string>> = {};

    if (!email.trim()) {
      nextErrors.email = requiredText;
    } else if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      nextErrors.email = invalidEmailText;
    }

    if (!password.trim()) {
      nextErrors.password = requiredText;
    }

    if (isVisibleVerificationCodeEmpty) {
      nextErrors.verificationCode = requiredText;
      setFocusVerificationCodeOnShow(true);
      window.setTimeout(() => {
        verificationCodeInputRef.current?.focus();
      }, 100);
    }

    setFieldErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  }, [email, invalidEmailText, isVisibleVerificationCodeEmpty, password, requiredText]);

  const switchMode = (nextMode: 'signin' | 'signup') => {
    setMode(nextMode);
    setError(null);
    setFieldErrors({});
    setShowVerificationCode(nextMode === 'signup' && verificationCode.trim().length > 0);
  };

  const validateSingleField = (field: 'email' | 'password' | 'verificationCode') => {
    let nextError: string | undefined;

    if (field === 'email') {
      if (!email.trim()) {
        nextError = requiredText;
      } else if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
        nextError = invalidEmailText;
      }
    }

    if (field === 'password' && !password.trim()) {
      nextError = requiredText;
    }

    if (field === 'verificationCode' && isVisibleVerificationCodeEmpty) {
      nextError = requiredText;
    }

    setFieldErrors((prev) => ({
      ...prev,
      [field]: nextError,
    }));
  };

  const getPasswordStrength = (value: string) => {
    const pwd = value.trim();
    if (!pwd) return { level: 0, label: '', color: 'bg-slate-300 dark:bg-slate-600' };

    let score = 0;
    if (pwd.length >= 8) score += 1;
    if (/[A-Z]/.test(pwd) && /[a-z]/.test(pwd)) score += 1;
    if (/\d/.test(pwd)) score += 1;
    if (/[^A-Za-z0-9]/.test(pwd)) score += 1;

    if (score <= 1) {
      return {
        level: 1,
        label: language === 'zh' ? '密码强度：弱' : 'Password strength: weak',
        color: 'bg-red-400',
      };
    }
    if (score <= 3) {
      return {
        level: 2,
        label: language === 'zh' ? '密码强度：中' : 'Password strength: medium',
        color: 'bg-amber-400',
      };
    }
    return {
      level: 3,
      label: language === 'zh' ? '密码强度：强' : 'Password strength: strong',
      color: 'bg-emerald-500',
    };
  };

  const passwordStrength = getPasswordStrength(password);

  const resolveAuthErrorMessage = useCallback((err: unknown) => {
    if (
      err instanceof TypeError
      && /failed to fetch|networkerror|load failed|network request failed/i.test(err.message)
    ) {
      return t('auth.networkFailed');
    }

    const message = err instanceof Error ? err.message : '';
    return message || t('auth.authFailed');
  }, [t]);

  const mapBackendErrorToField = useCallback((message: string) => {
    const lower = message.toLowerCase();
    if (lower.includes('email')) {
      setFieldErrors((prev) => ({ ...prev, email: message }));
      return;
    }
    if (lower.includes('password') || lower.includes('credential')) {
      setFieldErrors((prev) => ({ ...prev, password: message }));
      return;
    }
    if (lower.includes('verification') || lower.includes('code') || lower.includes('otp')) {
      setShowVerificationCode(true);
      setFocusVerificationCodeOnShow(true);
      setFieldErrors((prev) => ({ ...prev, verificationCode: message }));
      return;
    }
    setError(message);
  }, []);

  const handleOAuthSignIn = (provider: 'google' | 'github') => {
    rememberAuthReturnTo(returnTo);
    signInWithOAuth(provider);
  };

  const submit = useCallback(async () => {
    setError(null);
    if (!validateFields()) return;
    setBusy(true);
    try {
      if (mode === 'signin') {
        await signInWithPassword(email, password);
      } else {
        const signupName = `${firstName} ${lastName}`.trim();
        await signUpWithPassword(email, password, normalizedVerificationCode, signupName || undefined);
      }
    } catch (err) {
      const msg = resolveAuthErrorMessage(err);
      mapBackendErrorToField(msg);
    } finally {
      setBusy(false);
    }
  }, [
    email,
    firstName,
    lastName,
    mapBackendErrorToField,
    mode,
    normalizedVerificationCode,
    password,
    resolveAuthErrorMessage,
    signInWithPassword,
    signUpWithPassword,
    validateFields,
  ]);

  return (
    <form
      className="rounded-2xl border border-white/70 bg-white/65 p-4 shadow-[0_16px_30px_rgba(148,163,184,0.2)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/75 dark:shadow-[0_16px_30px_rgba(2,6,23,0.45)]"
      aria-busy={isSubmitting}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">{t('auth.account')}</p>
          <h3 className="text-2xl font-bold text-slate-800 dark:text-slate-100">{mode === 'signin' ? t('auth.signInTab') : t('auth.signUpTab')}</h3>
        </div>
        <div className="flex rounded-xl border border-white/70 bg-white/70 p-1 dark:border-slate-700 dark:bg-slate-800/80" role="tablist" aria-label={t('auth.account')}>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'signin'}
            onClick={() => switchMode('signin')}
            className={`min-h-11 rounded-lg px-4 py-2 text-sm font-semibold transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 ${
              mode === 'signin' ? 'bg-white text-brand-600 shadow-sm dark:bg-slate-900 dark:text-brand-300' : 'text-slate-500 hover:bg-white hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-slate-200'
            }`}
          >
            {t('auth.signInTab')}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'signup'}
            onClick={() => switchMode('signup')}
            className={`min-h-11 rounded-lg px-4 py-2 text-sm font-semibold transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 ${
              mode === 'signup' ? 'bg-white text-brand-600 shadow-sm dark:bg-slate-900 dark:text-brand-300' : 'text-slate-500 hover:bg-white hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-slate-200'
            }`}
          >
            {t('auth.signUpTab')}
          </button>
        </div>
      </div>

      <div className="mt-4 space-y-2.5">
        {mode === 'signup' && (
          <div className="grid grid-cols-2 gap-3">
            <input
              type="text"
              value={firstName}
              onChange={(event) => {
                setFirstName(event.target.value);
                setFieldErrors((prev) => ({ ...prev, firstName: undefined }));
              }}
              placeholder={t('auth.firstNamePlaceholder')}
              aria-label={t('auth.firstNamePlaceholder')}
              autoComplete="given-name"
              className="min-h-11 w-full rounded-xl border border-slate-200/80 bg-white/80 px-4 py-2.5 text-sm text-slate-800 placeholder:text-slate-400 focus:border-brand-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-1 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-brand-500"
            />
            <input
              type="text"
              value={lastName}
              onChange={(event) => {
                setLastName(event.target.value);
                setFieldErrors((prev) => ({ ...prev, lastName: undefined }));
              }}
              placeholder={t('auth.lastNamePlaceholder')}
              aria-label={t('auth.lastNamePlaceholder')}
              autoComplete="family-name"
              className="min-h-11 w-full rounded-xl border border-slate-200/80 bg-white/80 px-4 py-2.5 text-sm text-slate-800 placeholder:text-slate-400 focus:border-brand-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-1 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-brand-500"
            />
          </div>
        )}
        <input
          type="email"
          value={email}
          onChange={(event) => {
            setEmail(event.target.value);
            setFieldErrors((prev) => ({ ...prev, email: undefined }));
          }}
          onBlur={() => validateSingleField('email')}
          placeholder={t('auth.emailPlaceholder')}
          aria-label={t('auth.emailPlaceholder')}
          aria-invalid={Boolean(fieldErrors.email)}
          aria-describedby={fieldErrors.email ? emailErrorId : undefined}
          autoComplete="email"
          required
          className="min-h-11 w-full rounded-xl border border-slate-200/80 bg-white/80 px-4 py-2.5 text-sm text-slate-800 placeholder:text-slate-400 focus:border-brand-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-1 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-brand-500"
        />
        {fieldErrors.email && <p id={emailErrorId} role="alert" className="-mt-1 text-xs text-red-500">{fieldErrors.email}</p>}
        <div className="relative">
          <input
            type={showPassword ? 'text' : 'password'}
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              setFieldErrors((prev) => ({ ...prev, password: undefined }));
            }}
            onBlur={() => validateSingleField('password')}
            placeholder={t('auth.passwordPlaceholder')}
            aria-label={t('auth.passwordPlaceholder')}
            aria-invalid={Boolean(fieldErrors.password)}
            aria-describedby={fieldErrors.password ? passwordErrorId : undefined}
            autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
            required
            className="min-h-11 w-full rounded-xl border border-slate-200/80 bg-white/80 px-4 py-2.5 pr-14 text-sm text-slate-800 placeholder:text-slate-400 focus:border-brand-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-1 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-brand-500"
          />
          <button
            type="button"
            onClick={() => setShowPassword((prev) => !prev)}
            className="absolute right-1.5 top-1/2 inline-flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300"
            aria-label={showPassword ? t('auth.hidePassword') : t('auth.showPassword')}
          >
            {showPassword ? <EyeOff className="h-4.5 w-4.5" /> : <Eye className="h-4.5 w-4.5" />}
          </button>
        </div>
        {mode === 'signup' && password.trim() && (
          <div className="-mt-1 rounded-lg border border-slate-200/70 bg-white/70 px-3 py-2 dark:border-slate-700 dark:bg-slate-900/70">
            <div className="mb-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
              <div
                className={`h-full rounded-full transition-all ${passwordStrength.color}`}
                style={{ width: `${(passwordStrength.level / 3) * 100}%` }}
              />
            </div>
            <p className="text-[11px] text-slate-500 dark:text-slate-400">{passwordStrength.label}</p>
          </div>
        )}
        {fieldErrors.password && <p id={passwordErrorId} role="alert" className="-mt-1 text-xs text-red-500">{fieldErrors.password}</p>}
        {mode === 'signup' && (
          <>
            {!showVerificationCode ? (
              <button
                type="button"
                onClick={() => {
                  setShowVerificationCode(true);
                  setFocusVerificationCodeOnShow(true);
                }}
                aria-expanded={showVerificationCode}
                aria-controls={verificationCodeInputId}
                className="-mt-1 inline-flex min-h-11 items-center rounded-lg px-1 text-xs font-semibold text-brand-600 transition-colors hover:text-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 dark:text-brand-300 dark:hover:text-brand-200"
              >
                {t('auth.haveVerificationCode')}
              </button>
            ) : (
              <>
                <input
                  ref={verificationCodeInputRef}
                  id={verificationCodeInputId}
                  type="text"
                  value={verificationCode}
                  onChange={(event) => {
                    const sanitized = normalizeVerificationCode(event.target.value);
                    setVerificationCode(sanitized);
                    setFieldErrors((prev) => ({ ...prev, verificationCode: undefined }));
                  }}
                  onPaste={(event) => {
                    event.preventDefault();
                    const pasted = event.clipboardData.getData('text');
                    setVerificationCode(normalizeVerificationCode(pasted));
                    setFieldErrors((prev) => ({ ...prev, verificationCode: undefined }));
                  }}
                  onBlur={() => validateSingleField('verificationCode')}
                  placeholder={t('auth.verificationCodePlaceholder')}
                  aria-label={t('auth.verificationCodePlaceholder')}
                  aria-invalid={Boolean(fieldErrors.verificationCode)}
                  aria-describedby={fieldErrors.verificationCode ? `${verificationCodeErrorId} ${verificationCodeHintId}` : verificationCodeHintId}
                  autoComplete="one-time-code"
                  maxLength={64}
                  className="min-h-11 w-full rounded-xl border border-slate-200/80 bg-white/80 px-4 py-2.5 text-sm text-slate-800 placeholder:text-slate-400 transition-all focus:border-brand-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-1 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-brand-500"
                />
                {fieldErrors.verificationCode && <p id={verificationCodeErrorId} role="alert" className="-mt-1 text-xs text-red-500">{fieldErrors.verificationCode}</p>}
                <p id={verificationCodeHintId} className="-mt-1 text-xs text-slate-500 dark:text-slate-400">{t('auth.verificationCodeHint')}</p>
              </>
            )}
          </>
        )}
        {error && <p id={formErrorId} role="alert" className="text-sm text-red-500">{error}</p>}
        <button
          type="submit"
          aria-describedby={error ? formErrorId : undefined}
          className="min-h-11 w-full rounded-xl bg-gradient-to-r from-brand-500 to-brand-600 px-4 py-2.5 text-base font-semibold text-white shadow-lg shadow-brand-500/30 transition hover:-translate-y-px hover:shadow-brand-500/40 active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-60"
          disabled={isSubmitting}
          onMouseDown={(event) => {
            if (isVisibleVerificationCodeEmpty) {
              event.preventDefault();
              verificationCodeInputRef.current?.focus();
            }
          }}
        >
          {busy ? t('auth.processing') : mode === 'signin' ? t('auth.signInAction') : t('auth.signUpAction')}
        </button>
        {mode === 'signup' && password.trim() && passwordStrength.level === 1 && (
          <p className="-mt-1 text-xs text-amber-600 dark:text-amber-400">
            {language === 'zh' ? '建议使用至少 8 位，并包含大小写字母、数字或符号，提高账号安全性。' : 'For better security, use at least 8 characters and include uppercase/lowercase letters, numbers, or symbols.'}
          </p>
        )}
      </div>

      <div className="mt-4 flex items-center gap-3">
        <div className="h-px flex-1 bg-slate-200 dark:bg-slate-700" />
        <span className="text-xs font-medium text-slate-500 dark:text-slate-400">{t('auth.orDivider')}</span>
        <div className="h-px flex-1 bg-slate-200 dark:bg-slate-700" />
      </div>

      <div className="mt-3 space-y-2.5">
        <button
          type="button"
          className="flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-slate-200/80 bg-white/80 px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:border-brand-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-brand-500 dark:focus-visible:ring-offset-slate-950"
          onClick={() => handleOAuthSignIn('google')}
          disabled={isSubmitting}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
          </svg>
          {t('auth.continueWithGoogle')}
        </button>
        <button
          type="button"
          className="flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-slate-200/80 bg-white/80 px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:border-brand-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-brand-500 dark:focus-visible:ring-offset-slate-950"
          onClick={() => handleOAuthSignIn('github')}
          disabled={isSubmitting}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
          </svg>
          {t('auth.continueWithGithub')}
        </button>
      </div>
    </form>
  );
};
