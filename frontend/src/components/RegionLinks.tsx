import { Globe2 } from 'lucide-react';
import { ChoiceSelect } from './ChoiceSelect';

/** Explicit switches open a new tab so the current canvas remains available. */
export function RegionLinks({ language }: { language: 'en' | 'zh' }) {
  const zh = language === 'zh';
  const current = /(?:\.ms\.show|\.api-inference\.modelscope\.net)$/.test(window.location.hostname) ? 'cn' : 'global';
  return <div className="header-region-options">
    <div className="header-preference-row">
      <label htmlFor="workspace-region"><Globe2 size={16} aria-hidden="true" />{zh ? '访问线路' : 'Workspace'}</label>
      <ChoiceSelect id="workspace-region" label={zh ? '切换访问线路，在新标签页打开' : 'Switch workspace in a new tab'} value={current}
        menuWidth={192} align="end"
        options={[{ value: 'auto', label: zh ? '自动选择' : 'Automatic' },
          { value: 'cn', label: zh ? '国内工作台' : 'China workspace' },
          { value: 'global', label: zh ? '国际工作台' : 'Global workspace' }]}
        onChange={region => window.open(`https://evodesign.aurax.live/?region=${region}`, '_blank', 'noopener,noreferrer')} />
    </div>
    <p>{zh ? '切换会打开新标签页，作品保留在原站点。' : 'Opens a new tab. Your work stays on its original site.'}</p>
  </div>;
}
