import { createContext, useContext } from 'react';

export type Language = 'zh' | 'en';

type LanguageContextValue = {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (path: string) => string;
};

// Keep context identity independent of dictionaries updated during development.
export const LanguageContext = createContext<LanguageContextValue | null>(null);

export const useLanguage = () => {
  const context = useContext(LanguageContext);
  if (!context) throw new Error('useLanguage must be used within LanguageProvider');
  return context;
};
