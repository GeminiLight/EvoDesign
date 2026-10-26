import { useLanguage } from '../i18n/LanguageProvider';

export const SkipLink = () => {
  const { t } = useLanguage();

  return (
    <a href="#main-content" className="skip-link">
      {t('common.skipToContent')}
    </a>
  );
};
