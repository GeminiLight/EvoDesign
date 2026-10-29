import { useCallback, useMemo, useState, type ReactNode } from 'react';
import type { DiagramResponse } from '../../types/api';
import { ExcalidrawCanvas } from '../ExcalidrawCanvas';
import { TldrawCanvas } from '../TldrawCanvas/TldrawCanvas';
import type { CanvasMode } from './CanvasModeSelector';
import type { Editor, TLEditorSnapshot } from '@tldraw/tldraw';
import { CanvasToolbar } from './CanvasToolbar';
import type { CanvasViewState } from '../../utils/workspaceDocuments';
import { inspectCanvasPayload, isExcalidrawPayload, isTldrawPayload, parseJsonObject } from '../../utils/app';
import { CanvasStateOverlay, type CanvasStateOverlayKind } from './CanvasStateOverlay';
import { CanvasRenderBoundary } from './CanvasRenderBoundary';

export type CanvasBusyKind = 'generation' | 'local-edit' | 'save-recovery' | 'history-switch';

type DiagramCanvasPanelProps = {
  canvasMode: CanvasMode;
  preview: DiagramResponse | null;
  projectName?: string;
  projectNavigation?: ReactNode;
  saveIndicator?: ReactNode;
  onToggleFullscreen?: () => void;
  isGenerating?: boolean;
  canvasBusyKind?: CanvasBusyKind | null;
  generationMessage?: string | null;
  onTldrawSnapshotChange?: (snapshot: TLEditorSnapshot) => void;
  onExcalidrawSceneChange?: (scene: Record<string, unknown>, loadedScene?: Record<string, unknown>) => void;
  onSelectionChange?: (selectedIds: string[]) => void;
  toolbarTarget?: HTMLElement | null;
  initialView?: CanvasViewState | null;
  onViewReader?: (reader: (() => CanvasViewState) | null) => void;
};

export const DiagramCanvasPanel = ({
  canvasMode,
  preview,
  projectName,
  projectNavigation,
  saveIndicator,
  onToggleFullscreen,
  isGenerating = false,
  canvasBusyKind = null,
  generationMessage = null,
  onTldrawSnapshotChange,
  onExcalidrawSceneChange,
  onSelectionChange,
  toolbarTarget,
  initialView,
  onViewReader,
}: DiagramCanvasPanelProps) => {
  const [renderError, setRenderError] = useState<{ resetKey: string; error: Error } | null>(null);
  const [tldrawEditor, setTldrawEditor] = useState<Editor | null>(null);
  const handleTldrawReady = useCallback((editor: Editor | null) => {
    setTldrawEditor(editor);
    onViewReader?.(editor ? () => ({ kind: 'tldraw', camera: { ...editor.getCamera() }, selectedIds: [...editor.getSelectedShapeIds()] }) : null);
  }, [onViewReader]);

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
    // Saved documents may be deliberately blank or cleared by their owner.
    // Generated empty output is still rejected by the generation workflow.
    if (payloadInspection.status === 'empty' && preview.projectId) return null;

    return payloadInspection.status;
  }, [activeRenderError, canvasBusyKind, isGenerating, payloadInspection, preview]);

  return (
    <section className="flex h-full min-h-0 flex-col">
      <div className="canvas-embed relative min-h-0 flex-1 overflow-hidden rounded-xl border border-slate-200/80 bg-white dark:border-white/10 dark:bg-[#101524]">
        <CanvasRenderBoundary resetKey={canvasResetKey} onRenderError={handleRenderError}>
          {canvasMode === 'tldraw' ? (
            <div className="flex h-full min-h-0 flex-col">
              <CanvasToolbar api={null} tldrawEditor={tldrawEditor} toolbarTarget={toolbarTarget}
                projectNavigation={projectNavigation} saveIndicator={saveIndicator} name={projectName ?? 'EvoDesign'}
                disabled={Boolean(overlayKind) || !preview} report={!isGenerating ? preview?.generationReport : undefined}
                onToggleFullscreen={onToggleFullscreen} />
              <div className="relative min-h-0 flex-1">
            <TldrawCanvas
              key={canvasResetKey}
              snapshot={tldrawSnapshot}
              initialView={initialView}
              onEditorReady={handleTldrawReady}
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
              saveIndicator={saveIndicator}
              generationReport={!isGenerating ? preview?.generationReport : undefined}
              onToggleFullscreen={onToggleFullscreen}
              controlsDisabled={Boolean(overlayKind) || !preview}
              toolbarTarget={toolbarTarget}
              initialView={initialView}
              onViewReader={onViewReader}
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
