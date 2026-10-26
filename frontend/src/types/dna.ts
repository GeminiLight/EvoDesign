export type CabinId = 'structure' | 'style' | 'layout';
export type RuleSource = 'ai' | 'manual';

export type Rule = {
  id: number;
  /**
   * Backend-assigned stable identity (`dna_rules.rule_id`). Present only for
   * rules loaded from a backend that returns the field; locally seeded rules
   * derive one on save. Keeping it across title edits lets the backend update
   * the row in place instead of delete + re-create.
   */
  ruleId?: string;
  title: string;
  preview: string;
  source: RuleSource;
  enabled: boolean;
  pinned: boolean;
  usageCount: number;
  updatedAt: string;
};

export type CloneCandidate = {
  tempId: number;
  title: string;
  preview: string;
  cabinId: CabinId;
  selected: boolean;
};

export type CloneStep = 'upload' | 'parse' | 'candidate' | 'imported';
export type CloneStatus = 'idle' | 'missing-source' | 'parsing' | 'candidates' | 'imported' | 'error';
