import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import '@excalidraw/excalidraw/index.css';
import { CanvasFallback } from './CanvasFallback';
import type { AppState, BinaryFiles, ExcalidrawImperativeAPI } from '@excalidraw/excalidraw/types';
import type { OrderedExcalidrawElement } from '@excalidraw/excalidraw/element/types';
import { getNodeIcon, getIconHost, nodeIconNames, reconcileNodeIcons, type IconSceneElement } from '../utils/nodeIcons';
import { useLanguage } from '../i18n/LanguageProvider';
import { normalizeLegacyOrder } from '../utils/excalidrawOrder';
import type { GenerationReport } from '../utils/generationReport';
import { CanvasToolbar } from './DiagramCanvas/CanvasToolbar';
import { fitExcalidraw } from '../utils/fitExcalidraw';
import { documentAppState, inPlaceAppState, retainedSelection, sceneFiles } from '../utils/excalidrawScene';

const LazyExcalidraw = lazy(async () => {
  const mod = await import('@excalidraw/excalidraw');
  return { default: mod.Excalidraw };
});

export type MinimalElement = {
  id: string;
  x: number;
  y: number;
  width?: number;
  height?: number;
  [key: string]: unknown;
};

export type ExcalidrawCanvasProps = {
  sceneData?: Record<string, unknown> | null;
  sceneIdentity?: string;
  onSceneChange?: (scene: Record<string, unknown>, loadedScene?: Record<string, unknown>) => void;
  onSelectionChange?: (selectedIds: string[]) => void;
  onRenderError?: (error: Error) => void;
  backgroundColor?: string;
  exportName?: string;
  projectNavigation?: ReactNode;
  saveIndicator?: ReactNode;
  controlsDisabled?: boolean;
  generationReport?: GenerationReport;
  isFocusMode?: boolean;
  onToggleFocus?: () => void;
};

type ExcalidrawSceneRecord = Record<string, unknown> & {
  elements?: unknown;
  files?: unknown;
  appState?: unknown;
};

type ExcalidrawUpdateSceneArgs = Parameters<ExcalidrawImperativeAPI['updateScene']>[0];

export function ExcalidrawCanvas({ sceneData, sceneIdentity, onSceneChange, onSelectionChange, onRenderError, backgroundColor = '#ffffff', exportName = 'EvoDesign', projectNavigation, saveIndicator, controlsDisabled = false, generationReport, isFocusMode, onToggleFocus }: ExcalidrawCanvasProps) {
  const { language, t } = useLanguage();
  const [theme, setTheme] = useState<'light' | 'dark'>(() => document.documentElement.classList.contains('dark') ? 'dark' : 'light');
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(document.documentElement.classList.contains('dark') ? 'dark' : 'light'));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);
  const [selectedIcon, setSelectedIcon] = useState<{ id: string; name: string } | null>(null);
  const apiRef = useRef<ExcalidrawImperativeAPI | null>(null);
  const [canvasReady, setCanvasReady] = useState(false);
  const viewportRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!canvasReady || !viewport) return;
    let previous = { width: viewport.clientWidth, height: viewport.clientHeight };
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      // Hidden mobile panes have no size. Retain the last visible viewport so
      // returning to the canvas preserves its center, zoom, selection and undo.
      if (!width || !height) return;
      const api = apiRef.current;
      if (api && previous.width && previous.height && !shouldFitSceneRef.current) {
        const state = api.getAppState();
        api.updateScene({ appState: {
          scrollX: state.scrollX + (width - previous.width) / (2 * state.zoom.value),
          scrollY: state.scrollY + (height - previous.height) / (2 * state.zoom.value),
        }, captureUpdate: 'NEVER' });
      }
      previous = { width, height };
    });
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [canvasReady]);
  const isApplyingExternalSceneRef = useRef(false);
  const userInteractedRef = useRef(false);
  const onSceneChangeRef = useRef<typeof onSceneChange>(onSceneChange);
  const onSelectionChangeRef = useRef<typeof onSelectionChange>(onSelectionChange);
  const onRenderErrorRef = useRef<typeof onRenderError>(onRenderError);
  const previousSelectionRef = useRef<string[]>([]);
  const iconRepairFrameRef = useRef<number | null>(null);
  const keyboardNudgeRef = useRef<readonly OrderedExcalidrawElement[] | null>(null);
  const keyboardCommitFrameRef = useRef<number | null>(null);
  const sceneApplyTimerRef = useRef<number | null>(null);
  const appliedIdentityRef = useRef<string | undefined>(undefined);
  const shouldFitSceneRef = useRef(true);

  useEffect(() => () => {
    if (iconRepairFrameRef.current !== null) cancelAnimationFrame(iconRepairFrameRef.current);
    if (keyboardCommitFrameRef.current !== null) cancelAnimationFrame(keyboardCommitFrameRef.current);
    if (sceneApplyTimerRef.current !== null) window.clearTimeout(sceneApplyTimerRef.current);
  }, []);

  useEffect(() => {
    if (!canvasReady) return;
    const commitNudge = () => {
      if (!keyboardNudgeRef.current) return;
      if (keyboardCommitFrameRef.current !== null) cancelAnimationFrame(keyboardCommitFrameRef.current);
      // Excalidraw 0.18 listens on document and moves elements on arrow keys
      // without committing history. Capture after its native binding updates.
      keyboardCommitFrameRef.current = requestAnimationFrame(() => {
        keyboardCommitFrameRef.current = null;
        const api = apiRef.current;
        const before = keyboardNudgeRef.current;
        if (api && before && !isApplyingExternalSceneRef.current) {
          const repaired = reconcileNodeIcons(api.getSceneElementsIncludingDeleted() as unknown as IconSceneElement[], api.getFiles());
          if (repaired.assets.length) api.addFiles(repaired.assets as unknown as Parameters<typeof api.addFiles>[0]);
          // updateScene filters pending native mutations out of history. Rebase
          // those elements first, then apply the completed native move as one
          // explicit edit. No intermediate scene crosses the save boundary.
          isApplyingExternalSceneRef.current = true;
          try {
            api.updateScene({ elements: before, captureUpdate: 'EVENTUALLY' });
            api.updateScene({ elements: repaired.elements as unknown as OrderedExcalidrawElement[], captureUpdate: 'IMMEDIATELY' });
          } finally {
            isApplyingExternalSceneRef.current = false;
          }
        }
        keyboardNudgeRef.current = null;
      });
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      const state = apiRef.current?.getAppState();
      if (event.key.startsWith('Arrow') && !event.altKey && !event.metaKey && !event.ctrlKey && !event.isComposing
        && target instanceof HTMLElement && (target === document.body || target.closest('.excalidraw'))
        && !target.closest('input, textarea, select, button, [contenteditable="true"]')
        && viewportRef.current?.offsetWidth && state && !state.viewModeEnabled && !state.editingTextElement && !state.editingLinearElement
        && Object.values(state.selectedElementIds).some(Boolean)) {
        keyboardNudgeRef.current ??= structuredClone(apiRef.current!.getSceneElementsIncludingDeleted());
        userInteractedRef.current = true;
      }
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.key.startsWith('Arrow')) commitNudge();
    };
    document.addEventListener('keydown', onKeyDown, true);
    document.addEventListener('keyup', onKeyUp, true);
    window.addEventListener('blur', commitNudge);
    return () => {
      document.removeEventListener('keydown', onKeyDown, true);
      document.removeEventListener('keyup', onKeyUp, true);
      window.removeEventListener('blur', commitNudge);
    };
  }, [canvasReady]);

  useEffect(() => {
    onSceneChangeRef.current = onSceneChange;
  }, [onSceneChange]);

  useEffect(() => {
    onSelectionChangeRef.current = onSelectionChange;
  }, [onSelectionChange]);

  useEffect(() => {
    onRenderErrorRef.current = onRenderError;
  }, [onRenderError]);

  const normalizeScene = useCallback((scene: Record<string, unknown> | null | undefined) => {
    const payload: ExcalidrawSceneRecord = scene && typeof scene === 'object' ? scene : {};
    const elements = Array.isArray(payload.elements)
      ? normalizeLegacyOrder(payload.elements as unknown as readonly OrderedExcalidrawElement[])
      : [];
    const files = payload.files && typeof payload.files === 'object'
      ? payload.files as BinaryFiles
      : {};
    const appState: Partial<AppState> = {
      viewBackgroundColor: backgroundColor,
      currentItemFontFamily: 1,
      gridSize: 20,
      gridModeEnabled: false,
      ...documentAppState(payload.appState),
      selectedElementIds: {},
      collaborators: new Map(),
      openDialog: null,
    };

    const icons = reconcileNodeIcons(elements as unknown as IconSceneElement[], files);
    const usedFiles = new Set(icons.elements.filter(element => element.type === 'image').map(element => element.fileId));
    const mergedFiles = { ...files, ...Object.fromEntries(icons.assets.map(asset => [asset.id, asset])) };
    return {
      elements: icons.elements as unknown as readonly OrderedExcalidrawElement[],
      appState,
      files: Object.fromEntries(Object.entries(mergedFiles).filter(([id]) => usedFiles.has(id))) as BinaryFiles,
    };
  }, [backgroundColor]);

  const initialData = useMemo(() => {
    const normalized = normalizeScene(sceneData);
    return {
      ...normalized,
      scrollToContent: true,
    };
  }, [normalizeScene, sceneData]);

  const applyScene = useCallback((scene: Record<string, unknown> | null | undefined) => {
    if (!apiRef.current) return;
    keyboardNudgeRef.current = null;
    if (keyboardCommitFrameRef.current !== null) {
      cancelAnimationFrame(keyboardCommitFrameRef.current);
      keyboardCommitFrameRef.current = null;
    }
    if (sceneApplyTimerRef.current !== null) window.clearTimeout(sceneApplyTimerRef.current);

    const normalized = normalizeScene(scene);
    const sameDocument = Boolean(sceneIdentity && appliedIdentityRef.current === sceneIdentity);
    shouldFitSceneRef.current = !sameDocument;
    if (sameDocument) {
      const liveState = apiRef.current.getAppState();
      Object.assign(normalized.appState,
        inPlaceAppState(liveState as unknown as Record<string, unknown>, scene?.appState),
        retainedSelection(liveState, normalized.elements));
    }
    let applied = false;
    try {
      isApplyingExternalSceneRef.current = true;
      userInteractedRef.current = false;
      setSelectedIcon(null);
      const files = Object.values(normalized.files);
      if (files.length > 0) {
        apiRef.current.addFiles(files);
      }
      const updateScenePayload: ExcalidrawUpdateSceneArgs = {
        elements: normalized.elements,
        appState: normalized.appState as ExcalidrawUpdateSceneArgs['appState'],
        captureUpdate: sameDocument ? 'IMMEDIATELY' : 'NEVER',
      };
      apiRef.current.updateScene(updateScenePayload);
      appliedIdentityRef.current = sceneIdentity;
      applied = true;
    } catch (error) {
      const normalizedError = error instanceof Error ? error : new Error('Excalidraw scene update failed');
      console.error('Failed to update Excalidraw scene:', normalizedError);
      onRenderErrorRef.current?.(normalizedError);
    } finally {
      sceneApplyTimerRef.current = window.setTimeout(() => {
        sceneApplyTimerRef.current = null;
        isApplyingExternalSceneRef.current = false;
        const api = apiRef.current;
        if (!api || !applied || userInteractedRef.current) return;
        // Restoration can repair legacy icon assets without another native
        // onChange. Acknowledge that baseline before the first user selection.
        onSceneChangeRef.current?.({
          elements: api.getSceneElementsIncludingDeleted(),
          appState: documentAppState(api.getAppState()),
          files: sceneFiles(api.getSceneElementsIncludingDeleted(), api.getFiles()),
        }, scene ?? undefined);
      }, 0);
    }
  }, [normalizeScene, sceneIdentity]);

  useEffect(() => {
    if (canvasReady) applyScene(sceneData);
  }, [applyScene, canvasReady, sceneData]);

  useEffect(() => {
    // The generation progress card is taller than the final report. Wait for
    // that busy layout to settle before fitting the delivered diagram.
    if (!shouldFitSceneRef.current || controlsDisabled) return;
    const normalized = normalizeScene(sceneData);
    if (apiRef.current && normalized.elements.length > 0) {
      const timer = window.setTimeout(async () => {
        try {
          if (apiRef.current) await fitExcalidraw(apiRef.current, normalized.elements, 320);
          shouldFitSceneRef.current = false;
        } catch (error) {
          const normalizedError = error instanceof Error ? error : new Error('Excalidraw scroll failed');
          console.error('Failed to scroll Excalidraw scene:', normalizedError);
          onRenderErrorRef.current?.(normalizedError);
        }
      }, 100);

      return () => window.clearTimeout(timer);
    }

    return undefined;
  }, [canvasReady, controlsDisabled, normalizeScene, sceneData]);

  const changeSelectedIcon = (name: string) => {
    const api = apiRef.current;
    if (!api || !selectedIcon) return;
    const elements = api.getSceneElementsIncludingDeleted() as unknown as IconSceneElement[];
    const next = elements.map(element => element.id === selectedIcon.id ? {
      ...element,
      ...(name ? { customData: { ...element.customData, evoDesignIcon: { ...getNodeIcon(element), name } } }
        : { isDeleted: true }),
      version: (element.version ?? 1) + 1,
      versionNonce: Math.floor(Math.random() * 0x7fffffff),
      updated: Date.now(),
    } : element);
    const repaired = reconcileNodeIcons(next, api.getFiles());
    if (repaired.assets.length) api.addFiles(repaired.assets as unknown as Parameters<typeof api.addFiles>[0]);
    api.updateScene({ elements: repaired.elements as unknown as OrderedExcalidrawElement[], captureUpdate: 'IMMEDIATELY' });
    setSelectedIcon(name ? { ...selectedIcon, name } : null);
  };

  return (
    <div className="relative flex h-full min-h-0 w-full flex-col bg-white"
      onPointerDownCapture={() => { userInteractedRef.current = true; }}
      onKeyDownCapture={() => { userInteractedRef.current = true; }}>
      <CanvasToolbar projectNavigation={projectNavigation} saveIndicator={saveIndicator} api={canvasReady ? apiRef.current : null} name={exportName} disabled={controlsDisabled} report={generationReport} isFocusMode={isFocusMode} onToggleFocus={onToggleFocus} />
      <div ref={viewportRef} className="relative min-h-0 flex-1">
      <Suspense fallback={<CanvasFallback label="Excalidraw" />}>
        <LazyExcalidraw
          theme={theme}
          langCode={language === 'zh' ? 'zh-CN' : 'en'}
          UIOptions={{ canvasActions: { export: false, saveAsImage: false, loadScene: false, clearCanvas: false, saveToActiveFile: false, toggleTheme: false } }}
          excalidrawAPI={(api: ExcalidrawImperativeAPI) => {
            apiRef.current = api;
            setCanvasReady(true);
          }}
          initialData={initialData as never}
          onChange={(elements: readonly OrderedExcalidrawElement[], appState: AppState, files: BinaryFiles) => {
            if (isApplyingExternalSceneRef.current) {
              return;
            }
            const iconElements = elements as unknown as IconSceneElement[];
            const repaired = reconcileNodeIcons(iconElements, files);
            if (repaired.changed && apiRef.current) {
              // Finish the native action first. Synchronous updateScene here
              // can replace the scene halfway through duplication or undo.
              if (iconRepairFrameRef.current === null) {
                iconRepairFrameRef.current = requestAnimationFrame(() => {
                  iconRepairFrameRef.current = null;
                  const api = apiRef.current;
                  if (!api || isApplyingExternalSceneRef.current) return;
                  const latest = reconcileNodeIcons(
                    api.getSceneElementsIncludingDeleted() as unknown as IconSceneElement[], api.getFiles(),
                  );
                  if (!latest.changed) return;
                  if (latest.assets.length) api.addFiles(latest.assets as unknown as Parameters<typeof api.addFiles>[0]);
                  api.updateScene({
                    elements: latest.elements as unknown as OrderedExcalidrawElement[],
                    // Companion geometry is derived state. Keep it out of the
                    // undo stack and commit it before the next explicit edit.
                    captureUpdate: keyboardNudgeRef.current ? 'EVENTUALLY' : 'NEVER',
                  });
                });
              }
              return;
            }

            // Only fire selection change when selection actually changes
            const selIds = appState.selectedElementIds ?? {};
            const selectedIds = Object.keys(selIds).filter((id) => selIds[id]).sort();
            const selectedIcons = iconElements.filter(element => !element.isDeleted && getNodeIcon(element)
              && (selIds[element.id] || selIds[getIconHost(element, iconElements)?.id ?? '']));
            const nextIcon = selectedIcons.length === 1 ? selectedIcons[0] : null;
            const nextName = nextIcon ? getNodeIcon(nextIcon)?.name ?? '' : '';
            setSelectedIcon(previous => previous?.id === nextIcon?.id && previous?.name === nextName
              ? previous : nextIcon ? { id: nextIcon.id, name: nextName } : null);
            const prevSel = previousSelectionRef.current;
            if (!prevSel || selectedIds.length !== prevSel.length || selectedIds.some((id, i) => id !== prevSel[i])) {
              previousSelectionRef.current = selectedIds;
              onSelectionChangeRef.current?.(selectedIds);
            }

            onSceneChangeRef.current?.({
              elements: elements as unknown as Record<string, unknown>[],
              appState: documentAppState(appState),
              files: sceneFiles(elements, files) as unknown as Record<string, unknown>,
            }, userInteractedRef.current ? undefined : sceneData ?? undefined);
          }}
        />
      </Suspense>

      </div>
      {selectedIcon && (
        <label className="absolute right-3 top-14 z-10 flex max-w-[65%] items-center gap-2 rounded-xl border border-indigo-100 bg-white/95 px-3 py-2 text-xs text-slate-600 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
          <span className="shrink-0">{t('workspace.nodeIcon')}</span>
          <select aria-label={t('workspace.nodeIcon')} value={selectedIcon.name} onChange={event => changeSelectedIcon(event.target.value)}
            className="min-w-0 rounded-lg border-slate-200 py-1 pr-7 text-xs focus:border-indigo-400 focus:ring-indigo-400 dark:border-slate-700 dark:bg-slate-800">
            <option value="">{t('workspace.removeIcon')}</option>
            {nodeIconNames.map(name => <option key={name} value={name}>{name.replaceAll('_', ' ')}</option>)}
          </select>
        </label>
      )}
    </div>
  );
}

export default ExcalidrawCanvas;
