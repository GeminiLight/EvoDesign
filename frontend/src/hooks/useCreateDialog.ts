import { BROWSER_MODE } from '../services/browser/runtime';
import { useMemo, useState } from 'react';
import type { DiagramRequest, DiagramType } from '../types/api';
import type { PromptOption, PromptPill } from '../components/DiagramPromptComposer';
import type { CanvasMode } from '../components/DiagramCanvas/CanvasModeSelector';
import { defaultConfigs, diagramTypeToPillId, pillIdToDiagramType } from '../constants/app';

export function useCreateDialog(
  request: DiagramRequest,
  canvasMode: CanvasMode,
  t: (key: string) => string,
) {
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [createPrompt, setCreatePrompt] = useState('');
  const [createSelectedPillId, setCreateSelectedPillId] = useState('adaptive');
  const [createModelIndex, setCreateModelIndex] = useState(0);
  const [createCanvasIndex, setCreateCanvasIndex] = useState(0);

  const createPills = useMemo<PromptPill[]>(() => [
    { id: 'adaptive', label: t('home.pillAdaptiveLabel'), prefix: t('home.pillAdaptivePrefix'), icon: '✨' },
    { id: 'flow', label: t('home.pillFlowLabel'), prefix: t('home.pillFlowPrefix'), icon: '🔄' },
    { id: 'architecture', label: t('home.pillArchitectureLabel'), prefix: t('home.pillArchitecturePrefix'), icon: '🏗️' },
    { id: 'sequence', label: t('home.pillSequenceLabel'), prefix: t('home.pillSequencePrefix'), icon: '⏱️' },
    { id: 'mindmap', label: t('home.pillMindMapLabel'), prefix: t('home.pillMindMapPrefix'), icon: '🧠' },
  ], [t]);

  const createMorePills = useMemo<PromptPill[]>(() => [
    { id: 'entity', label: t('home.pillEntityLabel'), prefix: t('home.pillEntityPrefix'), icon: '🗄️' },
    { id: 'state', label: t('home.pillStateLabel'), prefix: t('home.pillStatePrefix'), icon: '🚦' },
    { id: 'gantt', label: t('home.pillGanttLabel'), prefix: t('home.pillGanttPrefix'), icon: '📊' },
    { id: 'class', label: t('home.pillClassLabel'), prefix: t('home.pillClassPrefix'), icon: '📦' },
  ], [t]);

  const createModelOptions = useMemo<PromptOption[]>(() => defaultConfigs.map((cfg) => ({
    id: cfg.id,
    label: BROWSER_MODE ? t('browser.yourModel') : t('home.serverModel'),
  })), [t]);

  const createCanvasOptions = useMemo<PromptOption[]>(() => [
    { id: 'excalidraw', label: t('home.canvasExcalidraw') },
    ...(!BROWSER_MODE ? [{ id: 'tldraw' as const, label: t('home.canvasTldraw') }] : []),
  ], [t]);

  const selectedCreatePillLabel = useMemo(
    () => [...createPills, ...createMorePills].find((pill) => pill.id === createSelectedPillId)?.label ?? t('home.pillAdaptiveLabel'),
    [createMorePills, createPills, createSelectedPillId, t],
  );

  const selectedCreateDiagramType = useMemo<DiagramType>(
    () => pillIdToDiagramType[createSelectedPillId] ?? 'automated',
    [createSelectedPillId],
  );

  const handleOpenCreateDialog = () => {
    setCreatePrompt('');
    setCreateSelectedPillId(diagramTypeToPillId[request.diagramType] ?? 'adaptive');
    setCreateModelIndex(Math.max(0, defaultConfigs.findIndex((cfg) => cfg.id === request.llmConfigId)));
    setCreateCanvasIndex(canvasMode === 'tldraw' ? 1 : 0);
    setShowCreateDialog(true);
  };

  return {
    showCreateDialog,
    setShowCreateDialog,
    createPrompt,
    setCreatePrompt,
    createSelectedPillId,
    setCreateSelectedPillId,
    createModelIndex,
    setCreateModelIndex,
    createCanvasIndex,
    setCreateCanvasIndex,
    createPills,
    createMorePills,
    createModelOptions,
    createCanvasOptions,
    selectedCreatePillLabel,
    selectedCreateDiagramType,
    handleOpenCreateDialog,
  };
}
