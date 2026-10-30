import '../../styles/home.css';
import { useRef, useState } from 'react';
import { Shapes, X } from 'lucide-react';
import { useLanguage } from '../../i18n/LanguageProvider';
import { DiagramPromptComposer } from '../DiagramPromptComposer';
import type { DiagramPromptComposerProps } from '../DiagramPromptComposer';
import { HomeReferencePreview } from '../Home/HomeReferencePreview';
import { HOME_REFERENCE_ACCEPT, HomeReferenceError, promptWithReference, readHomeReference } from '../../utils/homeReference';
import type { HomeReference } from '../../utils/homeReference';

type ComposerProps = Pick<DiagramPromptComposerProps, 'prompt' | 'onPromptChange' | 'onEnhance' | 'onSelectPill' | 'selectedPillId' | 'pills' | 'morePills' | 'modelOptions' | 'modelIndex' | 'onModelChange' | 'canvasOptions' | 'canvasIndex' | 'onCanvasChange'>;
type Props = { awaitingDocument?: boolean; composer: ComposerProps; onGeneratePrompt: (prompt: string) => void; disabled: boolean;
  useIcons: boolean; onUseIconsChange: (value: boolean) => void; onClose: () => void };

export function WorkspaceOnboarding({ composer, onGeneratePrompt, disabled, useIcons, onUseIconsChange, onClose, awaitingDocument }: Props) {
  const { language, t } = useLanguage();
  const zh = language === 'zh';
  const input = useRef<HTMLInputElement>(null);
  const attachmentTrigger = useRef<HTMLElement | null>(null);
  const [reference, setReference] = useState<HomeReference | null>(null);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState('');
  return <div className="workspace-onboarding-overlay pointer-events-none" data-awaiting-document={awaitingDocument}>
    <section className="workspace-start-composer pointer-events-auto" aria-label={zh ? '从想法开始' : 'Start with an idea'}>
      <button type="button" className="workspace-start-close tool-button" disabled={disabled || reading} onClick={onClose}
        aria-label={zh ? '关闭输入区，使用空白画布' : 'Close composer and use blank canvas'} title={zh ? '使用空白画布' : 'Use blank canvas'}><X size={17} /></button>
      <DiagramPromptComposer {...composer} variant="home" t={t} autoFocusPrompt isDisabled={disabled || reading}
        attachTitle={t('home.referenceFormats')} enhanceTitle={t('home.enhancePrompt')} moreLabel={t('home.pillMoreLabel')}
        generateTitle={zh ? '生成图表' : 'Generate diagram'}
        onGenerate={() => onGeneratePrompt(promptWithReference(composer.prompt, reference, language))}
        onAttachmentClick={() => { attachmentTrigger.current = document.activeElement as HTMLElement; input.current?.click(); }}
        attachmentContent={reference ? <HomeReferencePreview reference={reference} disabled={disabled} onRemove={() => setReference(null)} /> : undefined}
        leadingContent={<div className="home-composer-tools"><button type="button" className="home-icons-toggle" role="switch" aria-label={zh ? '节点图标' : 'Node icons'} aria-checked={useIcons}
          disabled={disabled || reading} onClick={() => onUseIconsChange(!useIcons)}><Shapes size={15} aria-hidden="true" /><span>{zh ? '图标' : 'Icons'}</span><i aria-hidden="true" /></button></div>} />
      <input ref={input} className="sr-only" tabIndex={-1} type="file" accept={HOME_REFERENCE_ACCEPT} aria-label={zh ? '添加参考文件' : 'Add a reference file'}
        onChange={async event => {
          const file = event.target.files?.[0]; event.target.value = '';
          if (!file) return;
          setReading(true); setError('');
          try { setReference(await readHomeReference(file)); }
          catch (error) { setError(error instanceof HomeReferenceError ? t(`home.referenceError_${error.reason}`) : zh ? '无法读取文件' : 'Could not read file'); }
          finally { setReading(false); attachmentTrigger.current?.focus(); }
        }} />
      {error && <p className="workspace-start-error" role="alert">{error}</p>}
    </section>
  </div>;
}
