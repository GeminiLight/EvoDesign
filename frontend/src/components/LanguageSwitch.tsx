import { Languages } from 'lucide-react';
import { useLanguage } from '../i18n/LanguageProvider';

export const LanguageSwitch = () => {
  const { language, setLanguage } = useLanguage();

  const toggleLanguage = () => {
    setLanguage(language === 'zh' ? 'en' : 'zh');
  };

  const label = language === 'zh' ? 'Switch to English' : '切换到中文';

  return (
    <button
      type="button"
      onClick={toggleLanguage}
      className="tap-target flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 dark:border-white/10 bg-slate-100/50 dark:bg-white/5 text-slate-600 dark:text-slate-300 transition-all hover:bg-slate-200 dark:hover:bg-white/10 hover:text-slate-900 dark:hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950"
      aria-label={label}
      title={label}
    >
      <Languages className="h-4.5 w-4.5" />
    </button>
  );
};
