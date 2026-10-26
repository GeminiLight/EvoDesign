import { useEffect, useRef } from 'react';
import { Settings } from 'lucide-react';
import type { LLMProviderConfig } from '../types/api';
import { useLanguage } from '../i18n/LanguageProvider';

type SettingsPopoverProps = {
  showSettings: boolean;
  onToggleSettings: () => void;
  onCloseSettings: () => void;
  selectedModelLabel: string;
  llmConfigId: string;
  modelConfigs: LLMProviderConfig[];
  onSelectModel: (id: string) => void;
};

export const SettingsPopover = ({
  showSettings,
  onToggleSettings,
  onCloseSettings,
  selectedModelLabel,
  llmConfigId,
  modelConfigs,
  onSelectModel,
}: SettingsPopoverProps) => {
  const settingsRef = useRef<HTMLDivElement | null>(null);
  const { t } = useLanguage();

  useEffect(() => {
    if (!showSettings) return;

    const handleClickOutside = (event: MouseEvent) => {
      if (!settingsRef.current) return;
      if (!settingsRef.current.contains(event.target as Node)) {
        onCloseSettings();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showSettings, onCloseSettings]);

  return (
    <div className="relative" ref={settingsRef}>
      <button
        type="button"
        onClick={() => {
          onToggleSettings();
        }}
        className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-50 text-slate-600 hover:bg-slate-100 transition-colors border border-slate-200"
      >
        <Settings className="h-4.5 w-4.5" />
      </button>

      {showSettings && (
        <div className="absolute right-0 top-full z-40 mt-2 w-80 rounded-2xl border border-slate-200 bg-white p-4 shadow-xl">
          <div className="space-y-4">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">{t('settings.model')}</p>
              <p className="mt-1 text-xs text-slate-500">{t('settings.current')}：{selectedModelLabel}</p>
              <div className="mt-2 space-y-2">
                {modelConfigs.map((config) => {
                  const selected = llmConfigId === config.id;
                  return (
                    <button
                      key={config.id}
                      type="button"
                      onClick={() => onSelectModel(config.id)}
                      className={`w-full rounded-xl border px-3 py-2 text-left text-xs transition-all ${
                        selected
                          ? 'border-brand-200 bg-brand-50/60 text-brand-700 ring-1 ring-brand-200'
                          : 'border-slate-200 bg-white text-slate-600 hover:border-brand-100 hover:bg-slate-50'
                      }`}
                    >
                      <p className="font-semibold">{config.label}</p>
                      <p className="mt-0.5 text-[11px] opacity-80">{config.model}</p>
                    </button>
                  );
                })}
              </div>
            </div>

          </div>
        </div>
      )}
    </div>
  );
};
