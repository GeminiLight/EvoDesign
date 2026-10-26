import { useCallback, useMemo, useState, type ReactNode } from 'react';
import type { DiagramResponse } from '../../types/api';
import { ExcalidrawCanvas } from '../ExcalidrawCanvas';
import { TldrawCanvas } from '../TldrawCanvas/TldrawCanvas';
import type { CanvasMode } from './CanvasModeSelector';
import type { TLEditorSnapshot } from '@tldraw/tldraw';
import { inspectCanvasPayload, isExcalidrawPayload, isTldrawPayload, parseJsonObject } from '../../utils/app';
import { CanvasStateOverlay, type CanvasStateOverlayKind } from './CanvasStateOverlay';
import { CanvasRenderBoundary } from './CanvasRenderBoundary';

export type CanvasBusyKind = 'generation' | 'local-edit' | 'save-recovery' | 'history-switch';

type DiagramCanvasPanelProps = {
  canvasMode: CanvasMode;
  preview: DiagramResponse | null;
  projectName?: string;
  projectNavigation?: ReactNode;
  isFocusMode?: boolean;
  onToggleFocus?: () => void;
  isGenerating?: boolean;
  canvasBusyKind?: CanvasBusyKind | null;
  generationMessage?: string | null;
  onTldrawSnapshotChange?: (snapshot: TLEditorSnapshot) => void;
  onExcalidrawSceneChange?: (scene: Record<string, unknown>, loadedScene?: Record<string, unknown>) => void;
  onSelectionChange?: (selectedIds: string[]) => void;
};

export const DiagramCanvasPanel = ({
  canvasMode,
  preview,
  projectName,
  projectNavigation,
  isFocusMode,
  onToggleFocus,
  isGenerating = false,
  canvasBusyKind = null,
  generationMessage = null,
  onTldrawSnapshotChange,
  onExcalidrawSceneChange,
  onSelectionChange,
}: DiagramCanvasPanelProps) => {
  const [renderError, setRenderError] = useState<{ resetKey: string; error: Error } | null>(null);

  const tldrawSnapshot = useMemo<Record<string, unknown> | null>(() => {
    return isTldrawPayload(preview?.tldrawSnapshot) ? preview.tldrawSnapshot : null;
  }, [preview?.tldrawSnapshot]);

  const excalidrawScene = useMemo<Record<string, unknown> | null>(() => {
    const payload = preview?.excalidrawPayload;
    if (!payload) {
      return null;
    }

    if (typeof payload === 'string') {
      try {
        const parsed = JSON.parse(payload) as Record<string, unknown>;
        return isExcalidrawPayload(parsed) ? parsed : null;
      } catch {
        return null;
      }
    }

    if (isExcalidrawPayload(payload)) {
      return payload as unknown as Record<string, unknown>;
    }

    return null;
  }, [preview?.excalidrawPayload]);

  const payloadInspection = useMemo(() => {
    if (!preview) {
      return null;
    }

    const rawPayload = preview.rawSchemaBlob;
    if (rawPayload) {
      return inspectCanvasPayload(rawPayload, canvasMode);
    }

    const currentPayload = canvasMode === 'tldraw'
      ? preview.tldrawSnapshot
      : parseJsonObject(preview.excalidrawPayload);
    return inspectCanvasPayload(currentPayload, canvasMode);
  }, [canvasMode, preview]);

  const canvasResetKey = useMemo(() => (
    [
      canvasMode,
      preview?.diagramId ?? 'no-diagram',
      preview?.requestId ?? 'no-request',
    ].join(':')
  ), [canvasMode, preview?.diagramId, preview?.requestId]);

  const activeRenderError = renderError?.resetKey === canvasResetKey
    ? renderError.error
    : null;

  const handleRenderError = useCallback((error: Error) => {
    console.error('Canvas render failed:', error);
    setRenderError({ resetKey: canvasResetKey, error });
  }, [canvasResetKey]);

  const overlayKind = useMemo<CanvasStateOverlayKind | null>(() => {
    if (canvasBusyKind === 'local-edit') {
      return 'local-edit';
    }

    if (canvasBusyKind === 'save-recovery') {
      return 'save-recovery';
    }

    if (canvasBusyKind === 'history-switch') {
      return 'history-switch';
    }

    if (canvasBusyKind === 'generation' || isGenerating) {
      return 'generating';
    }

    if (activeRenderError) {
      return 'render-error';
    }

    if (!preview || !payloadInspection) {
      return null;
    }

    if (payloadInspection.status === 'valid') {
      return null;
    }

    return payloadInspection.status;
  }, [activeRenderError, canvasBusyKind, isGenerating, payloadInspection, preview]);

  return (
    <section className="flex h-full min-h-0 flex-col">
      <div className="canvas-embed relative min-h-0 flex-1 overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-700">
        <CanvasRenderBoundary resetKey={canvasResetKey} onRenderError={handleRenderError}>
          {canvasMode === 'tldraw' ? (
            <div className="flex h-full min-h-0 flex-col">
              <div className="canvas-toolbar">{projectNavigation}<p className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-800 dark:text-slate-100">{projectName}</p></div>
              <div className="relative min-h-0 flex-1">
            <TldrawCanvas
              snapshot={tldrawSnapshot}
              onSnapshotChange={onTldrawSnapshotChange}
              onSelectionChange={onSelectionChange}
              onRenderError={handleRenderError}
            />
              </div>
            </div>
          ) : (
            <ExcalidrawCanvas
              key={canvasResetKey}
              sceneData={excalidrawScene}
              sceneIdentity={canvasResetKey}
              exportName={projectName}
              projectNavigation={projectNavigation}
              generationReport={!isGenerating ? preview?.generationReport : undefined}
              isFocusMode={isFocusMode}
              onToggleFocus={onToggleFocus}
              controlsDisabled={Boolean(overlayKind) || !preview}
              onSceneChange={onExcalidrawSceneChange}
              onSelectionChange={onSelectionChange}
              onRenderError={handleRenderError}
            />
          )}
        </CanvasRenderBoundary>
        {overlayKind && (
          <CanvasStateOverlay
            kind={overlayKind}
            canvasMode={canvasMode}
            actualCanvasMode={payloadInspection?.kind}
            nodeCount={payloadInspection?.nodeCount ?? 0}
            progressMessage={generationMessage}
            errorMessage={activeRenderError?.message ?? null}
          />
        )}
      </div>
    </section>
  );
};
