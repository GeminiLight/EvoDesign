/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { messages } from './messages';
import { readLocalStorage, writeLocalStorage } from '../utils/safeLocalStorage';

export type Language = 'zh' | 'en';

type LanguageContextValue = {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (path: string) => string;
};

const STORAGE_KEY = 'smartdiagram_language';

const LanguageContext = createContext<LanguageContextValue | null>(null);

const getByPath = (obj: unknown, path: string): string | undefined => {
  const value = path.split('.').reduce<unknown>((acc, part) => {
    if (acc && typeof acc === 'object' && part in acc) {
      return (acc as Record<string, unknown>)[part];
    }
    return undefined;
  }, obj);

  return typeof value === 'string' ? value : undefined;
};

const resolveInitialLanguage = (): Language => {
  const saved = readLocalStorage(STORAGE_KEY);
  if (saved === 'zh' || saved === 'en') {
    return saved;
  }

  const browserLang = navigator.language.toLowerCase();
  if (browserLang.startsWith('zh')) {
    return 'zh';
  }

  return 'en';
};

export const LanguageProvider = ({ children }: { children: React.ReactNode }) => {
  const [language, setLanguage] = useState<Language>(resolveInitialLanguage);

  useEffect(() => {
    writeLocalStorage(STORAGE_KEY, language);
    // Keep the document language in sync so assistive tech announces the UI
    // with the right voice and hyphenation rules follow the active locale.
    document.documentElement.lang = language === 'zh' ? 'zh-Hans' : 'en';
  }, [language]);

  const t = useMemo(() => {
    return (path: string) => {
      return getByPath(messages[language], path) ?? getByPath(messages.en, path) ?? path;
    };
  }, [language]);

  const value = useMemo(() => ({ language, setLanguage, t }), [language, t]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
};

export const useLanguage = () => {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error('useLanguage must be used within LanguageProvider');
  }
  return context;
};
