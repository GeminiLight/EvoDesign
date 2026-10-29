import { useEffect, useRef, useState } from 'react';
import { BrainCircuit, LayoutTemplate, Palette, X } from 'lucide-react';
import { useLanguage } from '../../i18n/LanguageProvider';
import type { CabinId } from '../../types/dna';
import { ChoiceSelect } from '../ChoiceSelect';
import { dnaPreferenceExample } from '../../utils/dnaPreferenceExamples';

export function BrowserPreferenceDialog({ onSave, onClose, initialCategory = 'style', initialDraft }: {
  onSave: (category: CabinId, title: string, description: string) => void;
  onClose: () => void;
  initialCategory?: CabinId;
  initialDraft?: { title: string; description: string };
}) {
  const { language } = useLanguage(); const zh = language === 'zh';
  const dialog = useRef<HTMLDialogElement>(null);
  const nameInput = useRef<HTMLInputElement>(null);
  const [category, setCategory] = useState<CabinId>(initialCategory);
  const [title, setTitle] = useState(initialDraft?.title ?? '');
  const [description, setDescription] = useState(initialDraft?.description ?? '');
  const example = dnaPreferenceExample(category, language);
  useEffect(() => { const el = dialog.current!; el.showModal(); nameInput.current?.focus(); return () => el.close(); }, []);
  const field = 'studio-form-input mt-2';
  return <dialog ref={dialog} className="studio-dialog workspace-settings-dialog w-[min(480px,calc(100vw-24px))]" aria-labelledby="preference-title" onCancel={onClose}>
    <form className="space-y-4 p-6" onSubmit={e => { e.preventDefault(); if (title.trim() && description.trim()) onSave(category, title.trim(), description.trim()); }}>
      <div className="flex items-center justify-between gap-3"><h2 id="preference-title" className="text-base font-semibold">{zh ? '添加设计偏好' : 'Add a design preference'}</h2><button type="button" className="studio-icon-button" onClick={onClose} aria-label={zh ? '关闭' : 'Close'}><X size={18} /></button></div>
      <p className="text-xs leading-6 text-slate-500 dark:text-slate-400">{zh ? '保存在此浏览器，供下次生成参考。' : 'Saved in this browser for your next generation.'}</p>
      <div className="text-sm"><label htmlFor="preference-category">{zh ? '类别' : 'Category'}</label>
        <ChoiceSelect id="preference-category" className="choice-select-field mt-2" label={zh ? '类别' : 'Category'} value={category} menuWidth="anchor"
          options={[{ value: 'structure', label: zh ? '结构' : 'Structure', Icon: BrainCircuit }, { value: 'style', label: zh ? '样式' : 'Style', Icon: Palette }, { value: 'layout', label: zh ? '布局' : 'Layout', Icon: LayoutTemplate }]}
          onChange={value => setCategory(value as CabinId)} />
      </div>
      <label className="block text-sm">{zh ? '名称' : 'Name'}<input ref={nameInput} className={field} required maxLength={100} value={title} onChange={e => setTitle(e.target.value)} placeholder={`${zh ? '例如：' : 'e.g. '}${example.title}`} /></label>
      <label className="block text-sm">{zh ? '具体偏好' : 'Preference'}<textarea className={field} required maxLength={1500} rows={4} value={description} onChange={e => setDescription(e.target.value)} placeholder={example.description} /></label>
      <div className="flex justify-end gap-2 border-t border-slate-200/70 pt-4 dark:border-white/10"><button type="button" className="studio-secondary" onClick={onClose}>{zh ? '取消' : 'Cancel'}</button><button type="submit" className="studio-primary" disabled={!title.trim() || !description.trim()}>{zh ? '添加偏好' : 'Add preference'}</button></div>
    </form>
  </dialog>;
}
