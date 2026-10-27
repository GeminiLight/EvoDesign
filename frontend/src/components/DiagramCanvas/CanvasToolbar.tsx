import { ChevronDown, Download, Loader2, Maximize2, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { ExcalidrawImperativeAPI } from '@excalidraw/excalidraw/types';
import { useLanguage } from '../../i18n/LanguageProvider';
import { useToast } from '../toastContext';
import { GenerationReport } from '../GenerationReport';
import type { GenerationReport as Report } from '../../utils/generationReport';
import { documentAppState, sceneFiles } from '../../utils/excalidrawScene';
import { fitExcalidraw } from '../../utils/fitExcalidraw';

type Props = { projectNavigation?: ReactNode; saveIndicator?: ReactNode; api: ExcalidrawImperativeAPI | null; name: string; disabled?: boolean; report?: Report; isFocusMode?: boolean; onToggleFocus?: () => void };

/** Export the live editor scene, including unsaved edits and embedded icons. */
export function CanvasToolbar({ projectNavigation, saveIndicator, api, name, disabled = false, report, isFocusMode, onToggleFocus }: Props) {
  const { t } = useLanguage();
  const { showToast } = useToast();
  const [open, setOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const unavailable = !api || disabled || exporting;

  useEffect(() => {
    if (!open) return;
    menuRef.current?.querySelector<HTMLElement>('#canvas-export-options button')?.focus();
    const closeOutside = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener('mousedown', closeOutside);
    document.addEventListener('keydown', closeEscape);
    return () => {
      document.removeEventListener('mousedown', closeOutside);
      document.removeEventListener('keydown', closeEscape);
    };
  }, [open]);

  const exportScene = async (format: 'svg' | 'png' | 'excalidraw') => {
    if (!api || unavailable) return;
    setOpen(false);
    const elements = api.getSceneElements();
    if (!elements.length) {
      showToast(t('workspace.exportEmpty'), 'info');
      requestAnimationFrame(() => triggerRef.current?.focus());
      return;
    }
    setExporting(true);
    try {
      // Capture all parts together before an asynchronous renderer import.
      const files = sceneFiles(elements, api.getFiles());
      const appState = { ...api.getAppState(), exportScale: 2, exportBackground: true, exportWithDarkMode: false };
      let blob: Blob;
      if (format === 'excalidraw') {
        blob = new Blob([JSON.stringify({ type: 'excalidraw', version: 2, source: 'EvoDesign',
          elements, appState: documentAppState(appState), files }, null, 2)], { type: 'application/json' });
      } else {
        const { exportToBlob, exportToSvg } = await import('@excalidraw/excalidraw');
        blob = format === 'png'
          ? await exportToBlob({ elements, appState, files, mimeType: 'image/png',
            getDimensions: (width: number, height: number) => {
              const scale = Math.min(2, 8192 / Math.max(width, height));
              return { width: Math.round(width * scale), height: Math.round(height * scale), scale };
            } })
          : new Blob([(await exportToSvg({ elements, appState, files })).outerHTML], { type: 'image/svg+xml;charset=utf-8' });
      }
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${(name || 'EvoDesign').replace(/[\\/:*?"<>|\p{Cc}]/gu, '-').slice(0, 100)}.${format}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 30000);
      showToast(t('workspace.exportReady'), 'success');
    } catch (error) {
      console.error('Diagram export failed:', error);
      showToast(t('workspace.exportFailed'), 'error');
    } finally {
      setExporting(false);
      requestAnimationFrame(() => triggerRef.current?.focus());
    }
  };

  return (
    <div className="canvas-toolbar">
      {projectNavigation}
      <p className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-800 dark:text-slate-100" title={name}>{name}</p>
      {saveIndicator}
      {report && <GenerationReport report={report} t={t} compact />}
      <button type="button" disabled={unavailable} className="tool-button" title={t('workspace.fitCanvas')}
        onClick={() => { if (api) void fitExcalidraw(api, api.getSceneElements()).catch(() => showToast(t('workspace.fitFailed'), 'error')); }}>
        <Maximize2 size={15} aria-hidden="true" /><span className="canvas-fit-label">{t('workspace.fitCanvas')}</span>
      </button>
      {onToggleFocus && <button type="button" className="tool-button canvas-focus-button" onClick={onToggleFocus}
        aria-pressed={isFocusMode} aria-label={t(isFocusMode ? 'workspace.exitFocus' : 'workspace.enterFocus')}
        title={t(isFocusMode ? 'workspace.exitFocus' : 'workspace.enterFocus')}>
        {isFocusMode ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
        {isFocusMode && <span>{t('workspace.exitFocus')}</span>}
      </button>}
      <div className="relative" ref={menuRef}>
        <button ref={triggerRef} type="button" disabled={unavailable} className="tool-button tool-button-accent"
          aria-expanded={open} aria-controls="canvas-export-options" onClick={() => setOpen(value => !value)}>
          {exporting ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} aria-hidden="true" />}
          {t('workspace.exportDiagram')}<ChevronDown size={13} aria-hidden="true" />
        </button>
        {open && <div id="canvas-export-options" className="surface-overlay absolute right-0 top-full z-30 mt-2 w-56 rounded-xl p-1.5 shadow-e3" role="group" aria-label={t('workspace.exportDiagram')}>
          {(['svg', 'png', 'excalidraw'] as const).map(format => (
            <button key={format} type="button" onClick={() => { void exportScene(format); }} className="flex min-h-11 w-full flex-col items-start rounded-lg px-3 py-2 text-left hover:bg-slate-100 dark:hover:bg-slate-800">
              <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">{format === 'excalidraw' ? t('workspace.editableFile') : format.toUpperCase()}</span>
              <span className="text-xs text-slate-500 dark:text-slate-400">{t(`workspace.exportHint_${format}`)}</span>
            </button>
          ))}
        </div>}
      </div>
    </div>
  );
}
