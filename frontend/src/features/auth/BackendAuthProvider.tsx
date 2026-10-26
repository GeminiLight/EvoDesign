import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { BackendAuthResponse } from '../../contracts/backendApi.generated';
import { apiV1Url, readResponseDetail } from '../../services/httpClient';
import { AUTH_INVALIDATED_EVENT, AUTH_USER_ID_STORAGE_KEY, notifyAuthInvalidated } from './authEvents';
import { readLocalStorage, removeLocalStorage } from '../../utils/safeLocalStorage';
import { useToast } from '../../components/toastContext';
import { useLanguage } from '../../i18n/LanguageProvider';

interface User {
  user_id: string;
  email: string;
  username: string;
  avatar_url?: string;
  auth_provider: string;
}

interface AuthContextValue {
  user: User | null;
  token: string | null;
  loading: boolean;
  signInWithPassword: (email: string, password: string) => Promise<void>;
  signUpWithPassword: (email: string, password: string, verificationCode: string, name?: string) => Promise<void>;
  signInWithOAuth: (provider: 'google' | 'github') => void;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const AUTH_USER_PROFILE_STORAGE_KEY = 'auth_user_profile';

const normalizeUser = (raw: BackendAuthResponse['user']): User => {
  const username = raw.username ?? raw.email.split('@')[0];

  return {
    user_id: raw.user_id,
    email: raw.email,
    username,
    avatar_url: raw.avatar_url ?? undefined,
    auth_provider: raw.auth_provider,
  };
};

const persistSession = (token: string, rawUser: BackendAuthResponse['user']) => {
  const normalizedUser = normalizeUser(rawUser);
  localStorage.setItem('auth_token', token);
  localStorage.setItem(AUTH_USER_ID_STORAGE_KEY, normalizedUser.user_id);
  localStorage.setItem(AUTH_USER_PROFILE_STORAGE_KEY, JSON.stringify(normalizedUser));
  return normalizedUser;
};

const clearStoredSession = () => {
  localStorage.removeItem('auth_token');
  localStorage.removeItem(AUTH_USER_ID_STORAGE_KEY);
  localStorage.removeItem(AUTH_USER_PROFILE_STORAGE_KEY);
};

const isStoredTokenCurrent = (token: string) => localStorage.getItem('auth_token') === token;
const isAuthInvalidResponse = (response: Response) => response.status === 401 || response.status === 403;

const readCachedUser = (): User | null => {
  const rawProfile = readLocalStorage(AUTH_USER_PROFILE_STORAGE_KEY);
  if (rawProfile) {
    try {
      const parsed = JSON.parse(rawProfile) as Partial<User>;
      if (
        typeof parsed.user_id === 'string'
        && typeof parsed.username === 'string'
        && typeof parsed.email === 'string'
        && typeof parsed.auth_provider === 'string'
      ) {
        return {
          user_id: parsed.user_id,
          email: parsed.email,
          username: parsed.username,
          avatar_url: typeof parsed.avatar_url === 'string' ? parsed.avatar_url : undefined,
          auth_provider: parsed.auth_provider,
        };
      }
    } catch {
      removeLocalStorage(AUTH_USER_PROFILE_STORAGE_KEY);
    }
  }

  const cachedUserId = readLocalStorage(AUTH_USER_ID_STORAGE_KEY);
  if (!cachedUserId) {
    return null;
  }

  return {
    user_id: cachedUserId,
    email: '',
    username: 'Signed-in user',
    auth_provider: 'unknown',
  };
};

const getInitialToken = () => readLocalStorage('auth_token');

const getInitialUser = () => {
  if (!readLocalStorage('auth_token')) {
    return null;
  }
  return readCachedUser();
};

export const BackendAuthProvider = ({ children }: { children: React.ReactNode }) => {
  const [user, setUser] = useState<User | null>(() => getInitialUser());
  const [token, setToken] = useState<string | null>(() => getInitialToken());
  const [loading, setLoading] = useState(true);
  const { showToast } = useToast();
  const { t } = useLanguage();
  const oauthErrorHandledRef = useRef(false);

  useEffect(() => {
    let mounted = true;

    const loadSession = async (tokenOverride?: string) => {
      let storedToken: string | null = null;
      try {
        storedToken = tokenOverride ?? localStorage.getItem('auth_token');
        if (!storedToken) {
          setLoading(false);
          return;
        }

        const response = await fetch(apiV1Url('/auth/me'), {
          headers: {
            'Authorization': `Bearer ${storedToken}`,
          },
        });

        if (!mounted) return;

        if (!isStoredTokenCurrent(storedToken)) {
          if (!localStorage.getItem('auth_token')) {
            localStorage.removeItem(AUTH_USER_ID_STORAGE_KEY);
            setUser(null);
            setToken(null);
          }
          return;
        }

        if (response.ok) {
          const data = (await response.json()) as BackendAuthResponse;
          setUser(persistSession(storedToken, data.user));
          setToken(storedToken);
        } else if (isAuthInvalidResponse(response)) {
          if (isStoredTokenCurrent(storedToken)) {
            notifyAuthInvalidated();
          }
        } else if (isStoredTokenCurrent(storedToken)) {
          setToken(storedToken);
          setUser((currentUser) => currentUser ?? readCachedUser());
        }
      } catch (error) {
        console.error('Failed to load session', error);
        if (storedToken && mounted && isStoredTokenCurrent(storedToken)) {
          setToken(storedToken);
          setUser((currentUser) => currentUser ?? readCachedUser());
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };

    // 处理 OAuth 回调
    const handleOAuthCallback = async () => {
      const urlParams = new URLSearchParams(window.location.search);
      const callbackCode = urlParams.get('code');

      if (callbackCode) {
        // Clear URL immediately to prevent code reuse on refresh
        window.history.replaceState({}, document.title, '/');
        try {
          const exchangeResponse = await fetch(apiV1Url('/auth/exchange'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code: callbackCode }),
          });
          if (exchangeResponse.ok) {
            const data = (await exchangeResponse.json()) as BackendAuthResponse;
            const exchangedToken = data.token;
            const normalizedUser = persistSession(exchangedToken, data.user);
            setToken(exchangedToken);
            setUser(normalizedUser);
            if (mounted) setLoading(false);
          } else {
            console.error('OAuth code exchange failed');
            if (mounted) setLoading(false);
          }
        } catch (error) {
          console.error('OAuth code exchange error', error);
          if (mounted) setLoading(false);
        }
        return true;
      }

      return false;
    };

    const handleInit = async () => {
      const handledCallback = await handleOAuthCallback();
      if (!handledCallback) {
        await loadSession();
      }
    };

    handleInit();

    return () => {
      mounted = false;
    };
  }, []);

  // The backend redirects to `${frontend_url}/?error=<code>` when an OAuth
  // callback fails its state check. Only `?code=` was handled before, so a
  // rejected sign-in dropped the user back on the landing page with no clue
  // that anything had gone wrong.
  useEffect(() => {
    if (oauthErrorHandledRef.current) return;

    const params = new URLSearchParams(window.location.search);
    const oauthError = params.get('error');
    if (!oauthError) return;

    oauthErrorHandledRef.current = true;
    // Drop the params so a refresh does not replay the same toast.
    params.delete('error');
    params.delete('error_description');
    const query = params.toString();
    window.history.replaceState(
      {},
      document.title,
      `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`,
    );

    showToast(
      t(oauthError === 'invalid_state' ? 'auth.oauthInvalidState' : 'auth.oauthFailed'),
      'error',
    );
  }, [showToast, t]);

  useEffect(() => {
    const clearSessionState = () => {
      clearStoredSession();
      setUser(null);
      setToken(null);
    };

    const hydrateSession = async (nextToken: string) => {
      setLoading(true);
      try {
        const response = await fetch(apiV1Url('/auth/me'), {
          headers: {
            'Authorization': `Bearer ${nextToken}`,
          },
        });

        if (!isStoredTokenCurrent(nextToken)) {
          return;
        }

        if (!response.ok) {
          if (isAuthInvalidResponse(response)) {
            notifyAuthInvalidated();
            return;
          }
          setToken(nextToken);
          setUser(readCachedUser());
          return;
        }

        const data = (await response.json()) as BackendAuthResponse;
        setUser(persistSession(nextToken, data.user));
        setToken(nextToken);
      } catch (error) {
        console.error('Failed to hydrate session from storage event', error);
        if (isStoredTokenCurrent(nextToken)) {
          setToken(nextToken);
          setUser(readCachedUser());
        }
      } finally {
        setLoading(false);
      }
    };

    const handleStorage = (event: StorageEvent) => {
      if (event.key !== 'auth_token') return;
      if (!event.newValue) {
        notifyAuthInvalidated();
        return;
      }
      void hydrateSession(event.newValue);
    };

    const handleAuthInvalidated = () => {
      clearSessionState();
    };

    window.addEventListener('storage', handleStorage);
    window.addEventListener(AUTH_INVALIDATED_EVENT, handleAuthInvalidated);
    return () => {
      window.removeEventListener('storage', handleStorage);
      window.removeEventListener(AUTH_INVALIDATED_EVENT, handleAuthInvalidated);
    };
  }, []);

  const signInWithPassword = useCallback(async (email: string, password: string) => {
    const response = await fetch(apiV1Url('/auth/login'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, password }),
    });

    if (!response.ok) {
      const detail = await readResponseDetail(response, '登录失败');
      throw new Error(detail);
    }

    const data = (await response.json()) as BackendAuthResponse;
    setUser(persistSession(data.token, data.user));
    setToken(data.token);
  }, []);

  const signUpWithPassword = useCallback(async (email: string, password: string, verificationCode: string, name?: string) => {
    const response = await fetch(apiV1Url('/auth/register'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, password, username: name, verification_code: verificationCode }),
    });

    if (!response.ok) {
      const detail = await readResponseDetail(response, '注册失败');
      throw new Error(detail);
    }

    const data = (await response.json()) as BackendAuthResponse;
    setUser(persistSession(data.token, data.user));
    setToken(data.token);
  }, []);

  const signInWithOAuth = useCallback((provider: 'google' | 'github') => {
    window.location.href = apiV1Url(`/auth/${provider}`);
  }, []);

  const signOut = useCallback(async () => {
    notifyAuthInvalidated('signed-out');
    clearStoredSession();
    setUser(null);
    setToken(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      loading,
      signInWithPassword,
      signUpWithPassword,
      signInWithOAuth,
      signOut,
    }),
    [user, token, loading, signInWithPassword, signUpWithPassword, signInWithOAuth, signOut]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

// eslint-disable-next-line react-refresh/only-export-components
export const useBackendAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useBackendAuth must be used within BackendAuthProvider');
  }
  return ctx;
};
