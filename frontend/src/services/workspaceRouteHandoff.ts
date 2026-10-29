import type { CanvasMode } from '../components/DiagramCanvas/CanvasModeSelector';
import type { CreateDiagramDialogHandoff } from '../components/Workspace/CreateDiagramDialog';
import { defaultConfigs, diagramTypeToPillId, getDiagramTypeLabel, initialRequest } from '../constants/app';
import type { DiagramType } from '../types/api';
import type { CabinId } from '../types/dna';
import { isCanvasLibrary } from '../contracts/canvas';
import {
  loadStartupGenerationDraft,
  type StartupGenerationDraft,
  type StartupGenerationDraftSource,
} from './startupGenerationDraft';
import {
  loadWorkspacePreflightDraft,
  type WorkspacePreflightGeneration,
  type WorkspacePreflightKind,
  type WorkspacePreflightRule,
  type WorkspacePreflightSource,
} from './workspacePreflightDraft';

export const isWorkspaceDiagramType = (value: unknown): value is DiagramType => (
  typeof value === 'string' && Object.prototype.hasOwnProperty.call(diagramTypeToPillId, value)
);

const isWorkspacePreflightKind = (value: unknown): value is WorkspacePreflightKind => (
  value === 'gallery' || value === 'dna' || value === 'startup'
);

const getRouteStartupGenerationSource = (value: unknown): StartupGenerationDraftSource => (
  value === 'landing'
    || value === 'home'
    || value === 'dashboard'
    || value === 'gallery'
    || value === 'workspace'
    ? value
    : 'workspace'
);

const getRoutePreflightSource = (value: unknown): WorkspacePreflightSource => (
  value === 'dna' ? 'dna' : getRouteStartupGenerationSource(value)
);

const isCabinId = (value: unknown): value is CabinId => (
  value === 'structure' || value === 'style' || value === 'layout'
);

const isRouteStateObject = (state: unknown): state is Record<string, unknown> => (
  Boolean(state && typeof state === 'object' && !Array.isArray(state))
);

const hasRoutePreflightGeneration = (state: unknown): boolean => (
  Boolean(
    state
      && typeof state === 'object'
      && !Array.isArray(state)
      && (state as Record<string, unknown>).preflightGeneration === true,
  )
);

const getRoutePreflightRules = (value: unknown): WorkspacePreflightRule[] => {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.flatMap((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      return [];
    }

    const rule = item as Record<string, unknown>;
    const title = typeof rule.title === 'string' ? rule.title.trim() : '';
    const preview = typeof rule.preview === 'string' ? rule.preview.trim() : '';
    if (!title || !preview || !isCabinId(rule.cabinId)) {
      return [];
    }

    return [{
      cabinId: rule.cabinId,
      title,
      preview,
    }];
  });
};

const getRoutePreflightGeneration = (state: unknown): WorkspacePreflightGeneration | null => {
  if (!hasRoutePreflightGeneration(state)) {
    return null;
  }

  const routeState = state as Record<string, unknown>;
  const kind = isWorkspacePreflightKind(routeState.preflightKind)
    ? routeState.preflightKind
    : 'gallery';
  const promptText = typeof routeState.initialPrompt === 'string' ? routeState.initialPrompt.trim() : '';
  const diagramType = isWorkspaceDiagramType(routeState.initialDiagramType)
    ? routeState.initialDiagramType
    : initialRequest.diagramType;
  const llmConfigId = typeof routeState.initialLlmConfigId === 'string'
    && defaultConfigs.some((config) => config.id === routeState.initialLlmConfigId)
    ? routeState.initialLlmConfigId
    : defaultConfigs[0]?.id ?? initialRequest.llmConfigId;
  const canvasMode = isCanvasLibrary(routeState.initialCanvasMode)
    ? routeState.initialCanvasMode
    : 'excalidraw';
  const rules = getRoutePreflightRules(routeState.preflightRules);
  const routeRuleCount = typeof routeState.preflightRuleCount === 'number' && Number.isFinite(routeState.preflightRuleCount)
    ? Math.max(0, routeState.preflightRuleCount)
    : rules.length;
  const now = Date.now();

  return {
    kind,
    promptText,
    diagramType,
    llmConfigId,
    canvasMode,
    source: getRoutePreflightSource(routeState.initialSource),
    sourceName: typeof routeState.preflightSourceName === 'string'
      ? routeState.preflightSourceName.trim()
      : undefined,
    sourceDescription: typeof routeState.preflightSourceDescription === 'string'
      ? routeState.preflightSourceDescription.trim()
      : undefined,
    rules,
    ruleCount: Math.max(routeRuleCount, rules.length),
    createdAt: now,
    updatedAt: now,
  };
};

const getPreflightCabinLabel = (cabinId: CabinId, t: (key: string) => string): string => {
  if (cabinId === 'structure') return t('workspace.handoffCabinStructure');
  if (cabinId === 'style') return t('workspace.handoffCabinStyle');
  return t('workspace.handoffCabinLayout');
};

const getStartupPreflightSourceLabel = (
  source: WorkspacePreflightSource,
  t: (key: string) => string,
): string => {
  if (source === 'landing') return t('workspace.handoffSourceLanding');
  if (source === 'home') return t('workspace.handoffSourceHome');
  if (source === 'dashboard') return t('workspace.handoffSourceDashboard');
  if (source === 'gallery') return t('workspace.handoffSourceGallery');
  if (source === 'dna') return t('workspace.handoffSourceDna');
  return t('workspace.handoffSourceWorkspace');
};

export const buildCreateHandoff = (
  preflight: WorkspacePreflightGeneration | null,
  t: (key: string) => string,
): CreateDiagramDialogHandoff | null => {
  if (!preflight) {
    return null;
  }

  if (preflight.kind === 'dna') {
    const visibleRules = preflight.rules.slice(0, 2).map((rule) => ({
      cabinLabel: getPreflightCabinLabel(rule.cabinId, t),
      title: rule.title,
      preview: rule.preview,
    }));
    const hiddenRuleCount = Math.max(0, preflight.ruleCount - visibleRules.length);

    return {
      title: t('workspace.handoffDnaTitle'),
      description: t('workspace.handoffDnaDescription'),
      rulesLabel: t('workspace.handoffRulesLabel'),
      emptyRulesLabel: t('workspace.handoffNoRules'),
      rules: visibleRules,
      moreRulesLabel: hiddenRuleCount > 0
        ? t('workspace.handoffMoreRules').replace('{count}', String(hiddenRuleCount))
        : undefined,
      badges: [
        t('workspace.handoffSourceDna'),
        t('workspace.handoffRuleCount').replace('{count}', String(preflight.ruleCount)),
      ],
    };
  }

  if (preflight.kind === 'startup') {
    const sourceLabel = getStartupPreflightSourceLabel(preflight.source, t);

    return {
      title: t('workspace.handoffStartupTitle'),
      description: t('workspace.handoffStartupDescription'),
      sourceLabel: t('workspace.handoffSourceLabel'),
      sourceValue: sourceLabel,
      badges: [
        sourceLabel,
        getDiagramTypeLabel(preflight.diagramType, t),
      ],
    };
  }

  return {
    title: t('workspace.handoffGalleryTitle'),
    description: t('workspace.handoffGalleryDescription'),
    sourceLabel: t('workspace.handoffSourceLabel'),
    sourceValue: preflight.sourceName || t('workspace.handoffSourceGallery'),
    badges: [
      t('workspace.handoffSourceGallery'),
      getDiagramTypeLabel(preflight.diagramType, t),
    ],
  };
};

const getRouteStartupGenerationDraft = (state: unknown): StartupGenerationDraft | null => {
  if (!state || typeof state !== 'object' || Array.isArray(state)) {
    return null;
  }

  const routeState = state as Record<string, unknown>;
  const promptText = typeof routeState.initialPrompt === 'string' ? routeState.initialPrompt.trim() : '';
  if (!routeState.pendingGeneration || !promptText) {
    return null;
  }

  const diagramType = isWorkspaceDiagramType(routeState.initialDiagramType)
    ? routeState.initialDiagramType
    : initialRequest.diagramType;
  const llmConfigId = typeof routeState.initialLlmConfigId === 'string'
    && defaultConfigs.some((config) => config.id === routeState.initialLlmConfigId)
    ? routeState.initialLlmConfigId
    : defaultConfigs[0]?.id ?? initialRequest.llmConfigId;
  const canvasMode: CanvasMode = routeState.initialCanvasMode === 'tldraw' ? 'tldraw' : 'excalidraw';

  return {
    promptText,
    diagramType,
    llmConfigId,
    canvasMode,
    metadata: { canvasLibrary: canvasMode, ...(typeof routeState.initialUseIcons === 'boolean'
      ? { useIcons: String(routeState.initialUseIcons && canvasMode === 'excalidraw') } : {}) },
    status: 'pending',
    source: getRouteStartupGenerationSource(routeState.initialSource),
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };
};

const normalizeStartupDraftForWorkspace = (
  draft: StartupGenerationDraft | null,
): StartupGenerationDraft | null => {
  if (!draft) {
    return null;
  }

  const llmConfigId = defaultConfigs.some((config) => config.id === draft.llmConfigId)
    ? draft.llmConfigId
    : defaultConfigs[0]?.id ?? initialRequest.llmConfigId;
  const diagramType = isWorkspaceDiagramType(draft.diagramType)
    ? draft.diagramType
    : initialRequest.diagramType;
  const canvasMode: CanvasMode = draft.canvasMode === 'tldraw' ? 'tldraw' : 'excalidraw';

  return {
    ...draft,
    diagramType,
    llmConfigId,
    canvasMode,
    metadata: {
      ...(draft.metadata ?? {}),
      canvasLibrary: canvasMode,
    },
  };
};

const normalizePreflightForWorkspace = (
  preflight: WorkspacePreflightGeneration | null,
): WorkspacePreflightGeneration | null => {
  if (!preflight) {
    return null;
  }

  const llmConfigId = defaultConfigs.some((config) => config.id === preflight.llmConfigId)
    ? preflight.llmConfigId
    : defaultConfigs[0]?.id ?? initialRequest.llmConfigId;
  const diagramType = isWorkspaceDiagramType(preflight.diagramType)
    ? preflight.diagramType
    : initialRequest.diagramType;
  const canvasMode: CanvasMode = preflight.canvasMode === 'tldraw' ? 'tldraw' : 'excalidraw';
  const now = Date.now();

  return {
    ...preflight,
    diagramType,
    llmConfigId,
    canvasMode,
    ruleCount: Math.max(preflight.ruleCount, preflight.rules.length),
    createdAt: preflight.createdAt || now,
    updatedAt: preflight.updatedAt || now,
  };
};

export const getInitialPreflightGeneration = (state: unknown): WorkspacePreflightGeneration | null => {
  const routePreflight = getRoutePreflightGeneration(state);
  if (routePreflight) {
    return normalizePreflightForWorkspace(routePreflight);
  }

  if (isRouteStateObject(state) && Object.keys(state).length > 0) {
    return null;
  }

  if (loadStartupGenerationDraft()) {
    return null;
  }

  return normalizePreflightForWorkspace(loadWorkspacePreflightDraft());
};

export const getInitialStartupGenerationDraft = (state: unknown): StartupGenerationDraft | null => {
  if (hasRoutePreflightGeneration(state)) {
    return null;
  }

  const routeDraft = getRouteStartupGenerationDraft(state);
  const storedDraft = loadStartupGenerationDraft();

  if (routeDraft && storedDraft && routeDraft.promptText === storedDraft.promptText) {
    return normalizeStartupDraftForWorkspace({
      ...routeDraft,
      metadata: {
        ...(storedDraft.metadata ?? {}),
        ...(routeDraft.metadata ?? {}),
      },
      source: storedDraft.source,
      createdAt: storedDraft.createdAt,
      updatedAt: Math.max(storedDraft.updatedAt, routeDraft.updatedAt),
    });
  }

  return normalizeStartupDraftForWorkspace(routeDraft ?? storedDraft);
};
