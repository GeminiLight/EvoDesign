import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { useLanguage } from '../../i18n/LanguageProvider';
import type { CabinId } from '../../types/dna';

export function BrowserPreferenceDialog({ onSave, onClose }: {
  onSave: (category: CabinId, title: string, description: string) => void;
  onClose: () => void;
}) {
  const { language } = useLanguage(); const zh = language === 'zh';
  const dialog = useRef<HTMLDialogElement>(null);
  const nameInput = useRef<HTMLInputElement>(null);
  const [category, setCategory] = useState<CabinId>('style');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  useEffect(() => { const el = dialog.current!; el.showModal(); nameInput.current?.focus(); return () => el.close(); }, []);
  const field = 'mt-2 w-full rounded-xl border border-slate-200 bg-white p-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-white';
  return <dialog ref={dialog} className="workspace-settings-dialog w-[min(480px,calc(100vw-24px))]" aria-labelledby="preference-title" onCancel={onClose}>
    <form className="space-y-4 p-6" onSubmit={e => { e.preventDefault(); if (title.trim() && description.trim()) onSave(category, title.trim(), description.trim()); }}>
      <div className="flex items-center justify-between"><h2 id="preference-title" className="text-lg font-semibold">{zh ? '添加设计偏好' : 'Add a design preference'}</h2><button type="button" className="tool-button" onClick={onClose} aria-label={zh ? '关闭' : 'Close'}><X size={18} /></button></div>
      <p className="text-sm leading-6 text-slate-500">{zh ? '保存在此浏览器，下次生成时供模型参考。你随时可以修改或停用。' : 'Saved in this browser and included in your next generation. Edit or disable it at any time.'}</p>
      <label className="block text-sm">{zh ? '类别' : 'Category'}<select className={field} value={category} onChange={e => setCategory(e.target.value as CabinId)}><option value="structure">{zh ? '结构' : 'Structure'}</option><option value="style">{zh ? '样式' : 'Style'}</option><option value="layout">{zh ? '布局' : 'Layout'}</option></select></label>
      <label className="block text-sm">{zh ? '名称' : 'Name'}<input ref={nameInput} className={field} required maxLength={100} value={title} onChange={e => setTitle(e.target.value)} placeholder={zh ? '例如：青紫配色' : 'e.g. Cyan and violet palette'} /></label>
      <label className="block text-sm">{zh ? '具体偏好' : 'Preference'}<textarea className={field} required maxLength={1500} rows={4} value={description} onChange={e => setDescription(e.target.value)} placeholder={zh ? '使用柔和的青色与紫色，文字保持深色。' : 'Use pale cyan and violet fills with dark, readable labels.'} /></label>
      <div className="flex justify-end gap-2"><button type="button" className="tool-button" onClick={onClose}>{zh ? '取消' : 'Cancel'}</button><button type="submit" className="rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white">{zh ? '添加偏好' : 'Add preference'}</button></div>
    </form>
  </dialog>;
}
