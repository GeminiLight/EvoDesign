import { Minimize2 } from 'lucide-react';
import type { RefObject } from 'react';
import { useLanguage } from '../../i18n/LanguageProvider';
import { AssistantAvatar } from './AssistantAvatar';

export function CanvasFullscreenControls({ assistantVisible, assistantButtonRef, onToggleAssistant, onExit }: {
  assistantVisible: boolean;
  assistantButtonRef: RefObject<HTMLButtonElement | null>;
  onToggleAssistant: () => void;
  onExit: () => void;
}) {
  const { t } = useLanguage();
  return <div className="canvas-fullscreen-controls" role="group" aria-label={t('workspace.fullscreenControls')}>
    <button ref={assistantButtonRef} type="button" onClick={onToggleAssistant}
      aria-label={t(assistantVisible ? 'workspace.hideAssistant' : 'workspace.showAssistant')}
      title={t(assistantVisible ? 'workspace.hideAssistant' : 'workspace.showAssistant')}
      aria-expanded={assistantVisible} aria-controls="workspace-agent-chat-panel">
      <AssistantAvatar size={23} />
    </button>
    <button type="button" onClick={onExit} aria-label={t('workspace.exitFullscreen')}
      title={`${t('workspace.exitFullscreen')} · Esc`}><Minimize2 size={17} aria-hidden="true" /></button>
  </div>;
}
