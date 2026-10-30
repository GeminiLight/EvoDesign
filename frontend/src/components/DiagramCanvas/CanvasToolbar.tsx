import { ChevronDown, Download, Loader2, Maximize2 } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { getSnapshot, type Editor } from '@tldraw/tldraw';
import type { ExcalidrawImperativeAPI } from '@excalidraw/excalidraw/types';
import { useLanguage } from '../../i18n/LanguageProvider';
import { useToast } from '../toastContext';
import { GenerationReport } from '../GenerationReport';
import type { GenerationReport as Report } from '../../utils/generationReport';
import { documentAppState, sceneFiles } from '../../utils/excalidrawScene';

type Props = { projectNavigation?: ReactNode; saveIndicator?: ReactNode; api: ExcalidrawImperativeAPI | null; tldrawEditor?: Editor | null; toolbarTarget?: HTMLElement | null; name: string; disabled?: boolean; report?: Report; onToggleFullscreen?: () => void };

/** Export the live editor scene, including unsaved edits and embedded icons. */
export function CanvasToolbar({ projectNavigation, saveIndicator, api, tldrawEditor, toolbarTarget, name, disabled = false, report, onToggleFullscreen }: Props) {
  const { t } = useLanguage();
  const { showToast } = useToast();
  const [open, setOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const unavailable = (!api && !tldrawEditor) || disabled || exporting;

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
    if ((!api && !tldrawEditor) || unavailable) return;
    setOpen(false);
    const elements = api?.getSceneElements() ?? [];
    if (api ? !elements.length : !tldrawEditor!.getCurrentPageShapes().length) {
      showToast(t('workspace.exportEmpty'), 'info');
      requestAnimationFrame(() => triggerRef.current?.focus());
      return;
    }
    setExporting(true);
    try {
      // Capture all parts together before an asynchronous renderer import.
      let blob: Blob;
      if (!api && tldrawEditor) {
        const shapes = tldrawEditor.getCurrentPageShapeIds();
        if (format === 'excalidraw') {
          blob = new Blob([JSON.stringify(getSnapshot(tldrawEditor.store), null, 2)], { type: 'application/json' });
        } else if (format === 'svg') {
          const exported = await tldrawEditor.getSvgString([...shapes], { background: true });
          if (!exported) throw new Error('Empty SVG export');
          blob = new Blob([exported.svg], { type: 'image/svg+xml;charset=utf-8' });
        } else blob = (await tldrawEditor.toImage([...shapes], { format: 'png', background: true, scale: 2 })).blob;
      } else if (api) {
        const files = sceneFiles(elements, api.getFiles());
        const appState = { ...api.getAppState(), exportScale: 2, exportBackground: true, exportWithDarkMode: false };
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
      } else return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      const extension = tldrawEditor && !api && format === 'excalidraw' ? 'json' : format;
      anchor.download = `${(name || 'EvoDesign').replace(/[\\/:*?"<>|\p{Cc}]/gu, '-').slice(0, 100)}.${extension}`;
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

  const toolbar = (
    <div className={toolbarTarget ? 'workspace-top-controls' : 'canvas-toolbar'}>
      {projectNavigation}
      {!toolbarTarget && <p className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-800 dark:text-slate-100" title={name}>{name}</p>}
      {saveIndicator}
      {!toolbarTarget && report && <GenerationReport report={report} t={t} compact compactLabel={toolbarTarget ? t('workspace.reportTitle') : undefined} />}
      {onToggleFullscreen && <button type="button" disabled={unavailable} className="tool-button" onClick={onToggleFullscreen}
        aria-label={t('workspace.enterFullscreen')} title={t('workspace.enterFullscreen')}>
        <Maximize2 size={16} aria-hidden="true" />
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
  return toolbarTarget ? createPortal(toolbar, toolbarTarget) : toolbar;
}
