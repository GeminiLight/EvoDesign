import React from 'react';
import { useLanguage } from '../../i18n/LanguageProvider';
import { useBackendAuth } from '../../features/auth/BackendAuthProvider';
import { BillingPanel } from '../../features/billing/BillingPanel';
import type { DiagramRequest, DiagramResponse, ProjectSnapshotItem, UploadedAsset, DiagramType } from '../../types/api';
import type { InputMode, SubmitStatus, RecentDiagram, MoreDiagramOption, GenerationProgress } from '../../types/app';
import type { StreamStage } from '../../types/api';
import { diagramOptions, moreDiagramOptions } from '../../constants/app';

const ENABLE_BILLING = import.meta.env.VITE_ENABLE_BILLING === 'true';

const STAGES: { key: StreamStage; labelKey: string }[] = [
  { key: 'structure', labelKey: 'landing.workflowExtract' },
  { key: 'styling', labelKey: 'landing.workflowIntent' },
  { key: 'layout', labelKey: 'landing.workflowLayout' },
  { key: 'render', labelKey: 'landing.workflowRender' },
];

function StageProgressIndicator({ progress, t }: { progress: GenerationProgress; t: (key: string) => string }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-slate-200 bg-white/80 px-3 py-2.5">
      {STAGES.map((stage, idx) => {
        const stageNum = idx + 1;
        const isCompleted = progress.completedStages.includes(stage.key);
        const isActive = progress.currentStage === stage.key && !isCompleted;

        return (
          <div key={stage.key} className="flex items-center gap-2.5">
            {/* Status icon */}
            <div className="flex h-5 w-5 shrink-0 items-center justify-center">
              {isCompleted ? (
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                  <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                </span>
              ) : isActive ? (
                <span className="flex h-5 w-5 items-center justify-center">
                  <svg className="h-4 w-4 animate-spin text-brand-500" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                </span>
              ) : (
                <span className="flex h-5 w-5 items-center justify-center rounded-full border-2 border-slate-200">
                  <span className="text-[9px] font-bold text-slate-400">{stageNum}</span>
                </span>
              )}
            </div>
            {/* Label */}
            <span className={`text-xs font-medium ${isCompleted ? 'text-emerald-700' : isActive ? 'text-brand-600' : 'text-slate-400'}`}>
              {t(stage.labelKey)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

interface DiagramSidebarProps {
  request: DiagramRequest;
  updateRequest: <K extends keyof DiagramRequest>(key: K, value: DiagramRequest[K]) => void;
  inputMode: InputMode;
  setInputMode: (mode: InputMode) => void;
  assets: UploadedAsset[];
  handleFiles: (files: FileList | null) => void;
  removeAsset: (assetId: string) => void;
  selectedMoreOptionId: string | null;
  setSelectedMoreOptionId: (id: string | null) => void;
  showMoreOptionsDrawer: boolean;
  setShowMoreOptionsDrawer: React.Dispatch<React.SetStateAction<boolean>>;
  handleSelectMoreOption: (option: MoreDiagramOption) => void;
  getDiagramOptionLabel: (value: DiagramType) => string;
  getMoreOptionLabel: (id: string) => string;
  status: SubmitStatus;
  handleGenerate: () => void;
  handleManualSaveSnapshot: () => void;
  manualSaveStatus: 'idle' | 'saving';
  preview: DiagramResponse | null;
  isViewingProjectHistory: boolean;
  handleBackToRecentHistory: () => void;
  displayedProjectSnapshots: ProjectSnapshotItem[];
  displayedRecentDiagrams: RecentDiagram[];
  handleSelectSnapshot: (snapshot: ProjectSnapshotItem) => void;
  handleSelectRecentDiagram: (item: RecentDiagram) => void;
  progress?: GenerationProgress | null;
}

export function DiagramSidebar({
  request,
  updateRequest,
  inputMode,
  setInputMode,
  assets,
  handleFiles,
  removeAsset,
  selectedMoreOptionId,
  setSelectedMoreOptionId,
  showMoreOptionsDrawer,
  setShowMoreOptionsDrawer,
  handleSelectMoreOption,
  getDiagramOptionLabel,
  getMoreOptionLabel,
  status,
  handleGenerate,
  handleManualSaveSnapshot,
  manualSaveStatus,
  preview,
  isViewingProjectHistory,
  handleBackToRecentHistory,
  displayedProjectSnapshots,
  displayedRecentDiagrams,
  handleSelectSnapshot,
  handleSelectRecentDiagram,
  progress,
}: DiagramSidebarProps) {
  const { t } = useLanguage();
  const { user } = useBackendAuth();

  return (
    <section className="card-glass flex flex-col gap-6 p-5 sm:p-6 h-full overflow-y-auto">
      {user && ENABLE_BILLING && <BillingPanel />}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">{t('app.uploadContent')}</p>
          <h2 className="text-lg font-bold text-slate-900">{t('app.content')}</h2>
        </div>
        <div className="flex rounded-lg bg-slate-100 p-1">
          {(['text', 'file'] as InputMode[]).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setInputMode(mode)}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-all ${
                inputMode === mode ? 'bg-white text-brand-600 shadow-sm' : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              {mode === 'text' ? t('app.describe') : t('app.upload')}
            </button>
          ))}
        </div>
      </div>

      {inputMode === 'text' ? (
        <div className="relative group">
          <p className="mb-2 text-xs font-semibold text-slate-600">{t('app.specificRequirements')}</p>
          <textarea
            value={request.prompt}
            onChange={(event) => updateRequest('prompt', event.target.value)}
            rows={6}
            className="w-full resize-none rounded-2xl border-0 bg-slate-50 px-4 py-4 text-sm text-slate-700 placeholder:text-slate-400 focus:ring-2 focus:ring-brand-200 group-hover:bg-slate-50/80 transition-colors"
            placeholder={t('app.describePlaceholder')}
          />
          <div className="absolute bottom-3 right-3 text-[10px] text-slate-400">
            {request.prompt.length} {t('app.chars')}
          </div>
        </div>
      ) : (
        <label
          htmlFor="asset-upload"
          className="group flex min-h-[180px] cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50/50 transition-all hover:border-brand-300 hover:bg-brand-50/30"
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white shadow-sm ring-1 ring-slate-100 transition-transform group-hover:scale-110">
            <span className="text-xl">📂</span>
          </div>
          <p className="mt-3 text-sm font-medium text-slate-700 group-hover:text-brand-600">{t('app.clickOrDrag')}</p>
          <p className="mt-1 text-xs text-slate-400">{t('app.supports')}</p>
          <input
            id="asset-upload"
            type="file"
            multiple
            className="hidden"
            onChange={(event) => {
              handleFiles(event.target.files);
              event.target.value = '';
            }}
          />
        </label>
      )}

      {assets.length > 0 && (
        <div className="flex flex-col gap-2">
          {assets.map((asset) => (
            <div key={asset.id} className="group flex items-center justify-between rounded-xl border border-slate-100 bg-white p-2 pl-3 shadow-sm transition-all hover:border-brand-200 hover:shadow-md">
              <div className="flex items-center gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-500">
                  <span className="text-xs font-bold uppercase">{asset.type.slice(0, 3)}</span>
                </div>
                <div>
                  <p className="text-xs font-medium text-slate-700 line-clamp-1">{asset.name}</p>
                  <p className="text-[10px] text-slate-400">{asset.sizeKB}KB</p>
                </div>
              </div>
              <button
                className="mr-1 rounded-full p-1 text-slate-300 opacity-0 transition-all hover:bg-red-50 hover:text-red-500 group-hover:opacity-100"
                onClick={() => removeAsset(asset.id)}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-3 pt-2">
        <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">{t('app.customRequirements')}</p>
        <div className="grid grid-cols-2 gap-3">
          {diagramOptions.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => {
                setSelectedMoreOptionId(null);
                updateRequest('diagramType', option.value);
              }}
              className={`flex items-center gap-3 rounded-2xl border px-4 py-3.5 text-left transition-all ${
                request.diagramType === option.value && !selectedMoreOptionId
                  ? 'border-brand-200 bg-brand-50/50 text-brand-700 ring-1 ring-brand-200 shadow-sm'
                  : 'border-slate-100 bg-white text-slate-600 hover:border-brand-100 hover:bg-slate-50 hover:shadow-sm'
              }`}
            >
              <span className="text-xl">
                {option.value === 'flow' && '🔄'}
                {option.value === 'architecture' && '🏗️'}
                {option.value === 'sequence' && '⏱️'}
                {option.value === 'er' && '🔗'}
                {option.value === 'mindmap' && '🧠'}
                {option.value === 'network' && '🌐'}
                {option.value === 'automated' && '✨'}
              </span>
              <span className="text-sm font-medium">{getDiagramOptionLabel(option.value)}</span>
            </button>
          ))}
        </div>

        <div className="relative mt-3">
          <button
            type="button"
            onClick={() => setShowMoreOptionsDrawer((prev) => !prev)}
            className={`w-full rounded-full border px-4 py-2.5 text-sm font-semibold transition-all ${
              selectedMoreOptionId || showMoreOptionsDrawer
                ? 'border-brand-200 bg-brand-50/50 text-brand-700 ring-1 ring-brand-200 shadow-sm'
                : 'border-brand-200 bg-brand-50/30 text-brand-600 hover:bg-brand-50/60 hover:shadow-sm'
            }`}
          >
            {t('app.moreOptions')}
            {selectedMoreOptionId
              ? ` · ${getMoreOptionLabel(selectedMoreOptionId)}`
              : ''}
          </button>

          {showMoreOptionsDrawer && (
            <div className="absolute bottom-full left-0 right-0 z-30 mb-2 rounded-2xl border border-slate-200 bg-white p-3 shadow-xl">
              <div className="max-h-60 overflow-y-auto pr-1 custom-scrollbar">
                <div className="grid grid-cols-2 gap-2">
                  {moreDiagramOptions.map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      onClick={() => handleSelectMoreOption(option)}
                      className={`rounded-xl border px-3 py-2.5 text-left text-xs font-medium transition-all ${
                        selectedMoreOptionId === option.id
                          ? 'border-brand-200 bg-brand-50/60 text-brand-700 ring-1 ring-brand-200'
                          : 'border-slate-100 bg-white text-slate-600 hover:border-brand-100 hover:bg-slate-50'
                      }`}
                    >
                      {getMoreOptionLabel(option.id)}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="mt-auto flex flex-col gap-3">
        <button
          type="button"
          className="btn-primary group relative w-full overflow-hidden"
          onClick={handleGenerate}
          disabled={status === 'loading'}
        >
          <span className="relative z-10 flex items-center gap-2">
            {status === 'loading' ? (
              <>
                <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                <span>{progress?.message || t('app.generating')}</span>
              </>
            ) : (
              <>
                <span>{t('app.startGeneration')}</span>
              </>
            )}
          </span>
        </button>

        {status === 'loading' && progress && (
          <StageProgressIndicator progress={progress} t={t} />
        )}

        <button
          type="button"
          className="w-full rounded-full border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 transition-all hover:border-brand-200 hover:bg-brand-50/40 disabled:cursor-not-allowed disabled:opacity-50"
          onClick={handleManualSaveSnapshot}
          disabled={!user || !preview?.projectId || manualSaveStatus === 'saving' || status === 'loading'}
        >
          {manualSaveStatus === 'saving' ? t('app.savingSnapshot') : t('app.saveSnapshot')}
        </button>

        {!user && status === 'success' && (
          <div className="rounded-xl border border-amber-200 bg-amber-50/80 px-3 py-2 text-xs text-amber-700">
            {t('app.guestSaveHint')}
          </div>
        )}
      </div>

      {user && (isViewingProjectHistory || displayedRecentDiagrams.length > 0) && (
        <div className="space-y-3 pt-4">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
              {isViewingProjectHistory ? t('app.projectSnapshots') : t('app.recentDiagrams')}
            </p>
            {isViewingProjectHistory && (
              <button
                type="button"
                onClick={handleBackToRecentHistory}
                className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[10px] font-semibold text-slate-600 transition-all hover:border-brand-200 hover:text-brand-700"
              >
                ← {t('common.back')}
              </button>
            )}
          </div>
          <div className="space-y-2">
            {isViewingProjectHistory && displayedProjectSnapshots.length === 0 ? (
              <div className="rounded-xl border border-slate-200 bg-slate-50/60 px-3 py-3 text-xs text-slate-600">
                <p className="font-semibold text-slate-700">{t('app.emptyProjectSnapshots')}</p>
                <p className="mt-1 text-[11px] text-slate-500">{t('app.emptyProjectSnapshotsHint')}</p>
              </div>
            ) : isViewingProjectHistory
              ? displayedProjectSnapshots.map((item) => {
                  const isActive = preview?.snapshotId === item.snapshot_id;
                  return (
                    <button
                      key={item.snapshot_id}
                      type="button"
                      onClick={() => { void handleSelectSnapshot(item); }}
                      className={`relative w-full overflow-hidden rounded-xl border bg-white p-3 text-left text-xs transition-all ${
                        isActive
                          ? 'border-brand-300 bg-brand-50/60 ring-2 ring-brand-200'
                          : 'border-slate-100 hover:border-brand-100'
                      }`}
                    >
                      {isActive && <span className="absolute inset-y-0 left-0 w-1.5 rounded-l-xl bg-brand-500" />}
                      <div className="flex items-start justify-between gap-2">
                        <p className="font-semibold text-slate-700 line-clamp-1">{item.edit_source} · {item.snapshot_id.slice(0, 8)}</p>
                        {isActive && (
                          <span className="shrink-0 rounded-full bg-brand-500/10 px-2 py-0.5 text-[10px] font-bold text-brand-700">
                            {t('app.current')}
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-[10px] text-slate-400">{new Date(item.timestamp).toLocaleString()}</p>
                    </button>
                  );
                })
              : displayedRecentDiagrams.map((item) => (
                  (() => {
                    const isActive = preview?.diagramId === item.diagram_id;
                    return (
                      <button
                        key={item.id || item.diagram_id}
                        type="button"
                        onClick={() => { void handleSelectRecentDiagram(item); }}
                        className={`relative w-full overflow-hidden rounded-xl border p-3 text-left text-xs text-slate-600 transition-all ${
                          isActive
                            ? 'border-brand-300 bg-brand-50/60 ring-2 ring-brand-200'
                            : 'border-slate-100 bg-white hover:border-brand-100'
                        }`}
                      >
                        {isActive && <span className="absolute inset-y-0 left-0 w-1.5 rounded-l-xl bg-brand-500" />}
                        <div className="flex items-start justify-between gap-2">
                          <p className="font-semibold text-slate-700 line-clamp-1">{item.prompt}</p>
                          {isActive && (
                            <span className="shrink-0 rounded-full bg-brand-500/10 px-2 py-0.5 text-[10px] font-bold text-brand-700">
                              {t('app.current')}
                            </span>
                          )}
                        </div>
                        <p className="mt-1 text-[10px] text-slate-400">{item.diagram_type} · {new Date(item.created_at).toLocaleDateString()}</p>
                      </button>
                    );
                  })()
                ))}
          </div>
        </div>
      )}
    </section>
  );
}
