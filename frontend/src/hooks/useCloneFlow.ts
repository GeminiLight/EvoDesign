import { type Dispatch, type SetStateAction, useCallback, useEffect, useState } from 'react';
import type { CabinId, CloneCandidate, CloneStatus, CloneStep, Rule } from '../types/dna';
import { analyzeDnaImage } from '../services/backendApi';

export interface CabinConfig {
  id: CabinId;
  name: string;
  tag: string;
}

type CloneCandidateErrors = Record<number, { title: boolean; preview: boolean }>;

const buildCloneCandidateErrors = (candidates: CloneCandidate[]): CloneCandidateErrors => {
  const errors: CloneCandidateErrors = {};

  candidates.forEach((candidate) => {
    if (!candidate.selected) return;

    const title = candidate.title.trim().length === 0;
    const preview = candidate.preview.trim().length === 0;
    if (title || preview) {
      errors[candidate.tempId] = { title, preview };
    }
  });

  return errors;
};

export function useCloneFlow(
  ruleLibrary: Record<CabinId, Rule[]>,
  setRuleLibrary: Dispatch<SetStateAction<Record<CabinId, Rule[]>>>,
  cabins: CabinConfig[],
  t: (key: string) => string,
  isZh: boolean,
  onImported?: (message: string) => void,
  resetKey?: string,
) {
  const [showCloneModal, setShowCloneModal] = useState(false);
  const [cloneFileName, setCloneFileName] = useState('');
  const [cloneFile, setCloneFile] = useState<File | null>(null);
  const [cloneCandidates, setCloneCandidates] = useState<CloneCandidate[]>([]);
  const [cloneMessage, setCloneMessage] = useState('');
  const [cloneStep, setCloneStep] = useState<CloneStep>('upload');
  const [cloneStatus, setCloneStatus] = useState<CloneStatus>('idle');
  const cloneCandidateErrors = buildCloneCandidateErrors(cloneCandidates);
  const hasCloneCandidateErrors = Object.keys(cloneCandidateErrors).length > 0;

  const resetCloneFlow = useCallback(() => {
    setShowCloneModal(false);
    setCloneFileName('');
    setCloneFile(null);
    setCloneCandidates([]);
    setCloneMessage('');
    setCloneStep('upload');
    setCloneStatus('idle');
  }, []);

  useEffect(() => {
    resetCloneFlow();
  }, [resetCloneFlow, resetKey]);

  const runCloneExtraction = async () => {
    if (!cloneFile) {
      setCloneMessage(t('dna.page.cloneNoSource'));
      setCloneStatus('missing-source');
      return;
    }

    setCloneStep('parse');
    setCloneStatus('parsing');
    setCloneMessage(t('dna.page.cloneParsing'));

    try {
      const results = await analyzeDnaImage(cloneFile);

      if (results.length === 0) {
        setCloneMessage(
          isZh
            ? '未识别到设计规则，请尝试上传其他图片'
            : 'No design rules identified. Try uploading a different image.',
        );
        setCloneStatus('error');
        setCloneStep('upload');
        return;
      }

      const candidates: CloneCandidate[] = results.map((r) => ({
        tempId: r.tempId,
        title: r.title,
        preview: r.preview,
        cabinId: r.cabinId,
        selected: true,
      }));

      setCloneCandidates(candidates);
      setCloneMessage(t('dna.page.cloneCandidateReady').replace('{count}', String(candidates.length)));
      setCloneStep('candidate');
      setCloneStatus('candidates');
    } catch {
      setCloneMessage(
        isZh
          ? '提取失败，请稍后重试'
          : 'Extraction failed. Please try again.',
      );
      setCloneStatus('error');
      setCloneStep('upload');
    }
  };

  const updateCloneCandidate = (tempId: number, patch: Partial<CloneCandidate>) => {
    setCloneCandidates((prev) => prev.map((item) => (item.tempId === tempId ? { ...item, ...patch } : item)));
    if (cloneStatus === 'error' && cloneCandidates.length > 0) {
      setCloneMessage('');
      setCloneStatus('candidates');
    }
  };

  const applyCloneCandidates = () => {
    const selectedCandidates = cloneCandidates
      .filter((item) => item.selected)
      .map((item) => ({
        ...item,
        title: item.title.trim(),
        preview: item.preview.trim(),
      }));
    if (selectedCandidates.length === 0) {
      setCloneMessage(t('dna.page.cloneNoCandidate'));
      setCloneStatus('error');
      return;
    }

    if (Object.keys(buildCloneCandidateErrors(selectedCandidates)).length > 0) {
      setCloneMessage(t('dna.page.cloneCandidateInvalid'));
      setCloneStatus('error');
      return;
    }

    let nextId = Math.max(
      ...(['structure', 'style', 'layout'] as CabinId[]).flatMap((cabinId) => ruleLibrary[cabinId].map((rule) => rule.id)),
      0,
    ) + 1;

    const appendRules: Record<CabinId, Rule[]> = { structure: [], style: [], layout: [] };

    selectedCandidates.forEach((candidate) => {
      appendRules[candidate.cabinId].push({
        id: nextId,
        title: candidate.title,
        preview: candidate.preview,
        source: 'ai',
        enabled: true,
        pinned: true,
        usageCount: 0,
        updatedAt: isZh ? '刚刚' : 'just now',
      });
      nextId += 1;
    });

    setRuleLibrary((prev) => ({
      structure: [...appendRules.structure, ...prev.structure],
      style: [...appendRules.style, ...prev.style],
      layout: [...appendRules.layout, ...prev.layout],
    }));

    const usedCabins = Array.from(new Set(selectedCandidates.map((item) => item.cabinId))).map((cabinId) => {
      const targetCabin = cabins.find((cabin) => cabin.id === cabinId);
      return targetCabin?.tag ?? cabinId;
    });

    setCloneMessage(t('dna.page.cloneApplied'));
    setCloneStep('imported');
    setCloneStatus('imported');
    onImported?.(
      t('dna.page.cloneImportedToast')
        .replace('{count}', String(selectedCandidates.length))
        .replace('{cabins}', usedCabins.join(' / ')),
    );
    setCloneCandidates([]);
    setCloneFileName('');
    setShowCloneModal(false);
  };

  const cloneStepList: Array<{ key: CloneStep; label: string }> = [
    { key: 'upload', label: t('dna.page.cloneStepUpload') },
    { key: 'parse', label: t('dna.page.cloneStepParse') },
    { key: 'candidate', label: t('dna.page.cloneStepCandidate') },
    { key: 'imported', label: t('dna.page.cloneStepImport') },
  ];
  const cloneCurrentStepIndex = cloneStepList.findIndex((item) => item.key === cloneStep);

  const openCloneModal = () => {
    resetCloneFlow();
    setShowCloneModal(true);
  };

  const selectedCandidateCount = cloneCandidates.filter((item) => item.selected).length;
  const canApplyCloneCandidates = selectedCandidateCount > 0 && cloneStatus !== 'parsing' && !hasCloneCandidateErrors;

  return {
    showCloneModal,
    setShowCloneModal,
    cloneFileName,
    setCloneFileName,
    cloneFile,
    setCloneFile,
    cloneCandidates,
    cloneMessage,
    cloneStep,
    setCloneStep,
    cloneStatus,
    resetCloneFlow,
    openCloneModal,
    runCloneExtraction,
    updateCloneCandidate,
    applyCloneCandidates,
    cloneCandidateErrors,
    hasCloneCandidateErrors,
    selectedCandidateCount,
    canApplyCloneCandidates,
    cloneStepList,
    cloneCurrentStepIndex,
  };
}
