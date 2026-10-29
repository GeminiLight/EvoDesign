import type { CabinId } from '../types/dna';

const examples = {
  structure: {
    zh: ['按职责分组', '将相同职责的节点分组，连接线注明数据流向。'],
    en: ['Group by responsibility', 'Group related nodes and label the direction of data flows.'],
  },
  style: {
    zh: ['青紫配色', '使用柔和的青色与紫色，文字保持清晰易读。'],
    en: ['Cyan and violet palette', 'Use pale cyan and violet fills with clearly readable labels.'],
  },
  layout: {
    zh: ['从左到右', '从左到右排列，同层节点等距对齐。'],
    en: ['Left to right', 'Arrange left to right and align nodes evenly within each layer.'],
  },
} as const;

/** Examples only prefill a draft; they are never enabled or saved automatically. */
export function dnaPreferenceExample(category: CabinId, language: 'zh' | 'en') {
  const [title, description] = examples[category][language];
  return { title, description };
}
