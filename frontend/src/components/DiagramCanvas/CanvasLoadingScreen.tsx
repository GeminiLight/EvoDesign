import type { ReactNode } from 'react';
import { useLanguage } from '../../i18n/LanguageProvider';

type CanvasLoadingScreenProps = {
  children?: ReactNode;
};

export function CanvasLoadingScreen({ children }: CanvasLoadingScreenProps) {
  const { t } = useLanguage();

  return (
    <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-slate-50 via-blue-50 to-indigo-50">
      <div className="rounded-2xl border border-white/70 bg-white/75 px-7 py-6 text-center shadow-lg shadow-slate-200/50 backdrop-blur-sm">
        <div className="mx-auto mb-3 h-10 w-10 rounded-full border-[3px] border-slate-200 border-t-brand-500 animate-spin" />
        <p className="text-sm font-semibold text-slate-700">{children ?? t('common.loading')}</p>
        <p className="mt-1 text-xs text-slate-500">EvoDesign Canvas</p>
      </div>
    </div>
  );
}

export default CanvasLoadingScreen;
