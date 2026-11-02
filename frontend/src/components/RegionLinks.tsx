import { ArrowUpRight, Globe2 } from 'lucide-react';

/** Explicit switches open a new tab so the current canvas remains available. */
export function RegionLinks({ language }: { language: 'en' | 'zh' }) {
  const zh = language === 'zh';
  return <details className="header-region-options">
    <summary><Globe2 size={17} aria-hidden="true" /><span>{zh ? '访问线路' : 'Workspace region'}</span></summary>
    <div>
      {([{ region: 'auto', label: zh ? '自动选择' : 'Automatic' },
        { region: 'cn', label: zh ? '国内工作台' : 'China workspace' },
        { region: 'global', label: zh ? '国际工作台' : 'Global workspace' }]).map(({ region, label }) => (
        <a key={region} href={`https://evodesign.aurax.live/?region=${region}`} target="_blank" rel="noopener noreferrer">
          <span>{label}</span><ArrowUpRight size={13} aria-hidden="true" />
        </a>
      ))}
      <p>{zh ? '作品和 DNA 保留在当前站点。' : 'Projects and DNA stay on their original site.'}</p>
    </div>
  </details>;
}
