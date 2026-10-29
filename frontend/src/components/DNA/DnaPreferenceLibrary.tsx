import { Dna, Layers3, ListChecks, Pencil, Plus, Search, X, type LucideIcon } from 'lucide-react';
import { useRef, type MouseEvent } from 'react';
import { useLanguage } from '../../i18n/LanguageProvider';
import { BROWSER_MODE } from '../../services/browser/runtime';
import { ChoiceSelect } from '../ChoiceSelect';
import type { CabinId, Rule } from '../../types/dna';
import { dnaPreferenceExample } from '../../utils/dnaPreferenceExamples';
import { emptyDnaFilters, filterDnaPreferences, type DnaLibraryFilters } from '../../utils/dnaLibrary';
import '../../styles/dna-library.css';

type Cabin = { id: CabinId; name: string; icon: LucideIcon };
type Props = {
  cabins: Cabin[];
  library: Record<CabinId, Rule[]>;
  filters: DnaLibraryFilters;
  onFilterChange: (filters: DnaLibraryFilters) => void;
  canEdit: boolean;
  onEdit: (event: MouseEvent<HTMLButtonElement>, cabinId: CabinId, rule: Rule) => void;
  onToggle: (cabinId: CabinId, ruleId: number) => void;
  onManage: (event: MouseEvent<HTMLButtonElement>, cabinId: CabinId) => void;
  onAdd: (event: MouseEvent<HTMLButtonElement>, cabinId: CabinId) => void;
  onExample?: (event: MouseEvent<HTMLButtonElement>, cabinId: CabinId) => void;
};

export function DnaPreferenceLibrary({ cabins, library, filters, onFilterChange, canEdit,
  onEdit, onToggle, onManage, onAdd, onExample }: Props) {
  const { language, t } = useLanguage();
  const zh = language === 'zh';
  const searchRef = useRef<HTMLInputElement>(null);
  const tabRefs = useRef(new Map<string, HTMLButtonElement>());
  const total = cabins.reduce((count, cabin) => count + library[cabin.id].length, 0);
  const tabs = [{ id: 'all' as const, name: zh ? '全部' : 'All', icon: Layers3 },
    ...cabins.map(cabin => ({ ...cabin, name: !zh && cabin.id === 'style' ? 'Style' : cabin.name }))];
  const preferences = filterDnaPreferences(library, filters);
  const selectedCabin = cabins.find(cabin => cabin.id === filters.category);
  const hasFilters = Boolean(filters.query.trim() || filters.status !== 'all');

  return <section className="dna-library" aria-label={zh ? '偏好库' : 'Preference library'}>
    <div className="dna-library-toolbar">
      <div className="dna-category-tabs studio-browse-tabs" role="tablist" aria-label={zh ? '偏好类型' : 'Preference type'}>
        {tabs.map((tab, index) => {
          const Icon = tab.icon;
          const active = filters.category === tab.id;
          return <button key={tab.id} type="button" role="tab" id={`dna-category-${tab.id}`}
            className={`studio-tab ${active ? 'studio-tab-active' : ''}`}
            ref={element => { if (element) tabRefs.current.set(tab.id, element); else tabRefs.current.delete(tab.id); }}
            aria-selected={active} aria-controls="dna-preferences-panel" tabIndex={active ? 0 : -1}
            data-category={tab.id} onClick={() => onFilterChange({ ...filters, category: tab.id })}
            onKeyDown={event => {
              const offset = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
              const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
                : offset ? (index + offset + tabs.length) % tabs.length : null;
              if (next === null) return;
              event.preventDefault();
              onFilterChange({ ...filters, category: tabs[next].id });
              tabRefs.current.get(tabs[next].id)?.focus();
            }}>
            <Icon size={16} strokeWidth={1.6} aria-hidden="true" /><span>{tab.name}</span>
            <small>{tab.id === 'all' ? total : library[tab.id].length}</small>
          </button>;
        })}
      </div>
      <label className="dna-library-search"><Search size={16} aria-hidden="true" />
        <input ref={searchRef} type="search" value={filters.query} aria-label={zh ? '搜索偏好' : 'Search preferences'}
          placeholder={zh ? '搜索偏好…' : 'Search preferences…'}
          onChange={event => onFilterChange({ ...filters, query: event.target.value })} />
        {filters.query && <button type="button" onClick={() => { onFilterChange({ ...filters, query: '' }); searchRef.current?.focus(); }}
          aria-label={zh ? '清除搜索' : 'Clear search'}><X size={14} /></button>}
      </label>
    </div>

    <div className="dna-library-meta">
      <p role="status">{zh ? `${preferences.length} 条偏好` : `${preferences.length} ${preferences.length === 1 ? 'preference' : 'preferences'}`}</p>
      <div className="dna-library-filters">
        <ChoiceSelect className="dna-status-filter" label={zh ? '启用状态' : 'Preference status'} value={filters.status}
          options={[{ value: 'all', label: zh ? '全部状态' : 'Any status' }, { value: 'enabled', label: zh ? '已启用' : 'Enabled' }, { value: 'disabled', label: zh ? '未启用' : 'Disabled' }]}
          onChange={value => onFilterChange({ ...filters, status: value as DnaLibraryFilters['status'] })} />
        {selectedCabin && library[selectedCabin.id].length > 0 && <button type="button" className="dna-library-manage" disabled={!canEdit}
          onClick={event => onManage(event, selectedCabin.id)}><ListChecks size={15} aria-hidden="true" />{zh ? '批量管理' : 'Manage in bulk'}</button>}
      </div>
    </div>

    <div id="dna-preferences-panel" role="tabpanel" aria-labelledby={`dna-category-${filters.category}`}>
      {preferences.length > 0 ? <div className="dna-preference-grid">
        {preferences.map(({ cabinId, rule }) => {
          const cabin = cabins.find(item => item.id === cabinId)!;
          const Icon = cabin.icon;
          return <article className="dna-preference" key={`${cabinId}:${rule.id}`} data-enabled={rule.enabled}>
            <div className="dna-preference-topline">
              <span className="dna-type-badge" data-category={cabinId}><Icon size={13} aria-hidden="true" />{cabin.name}</span>
              <button type="button" role="switch" aria-checked={rule.enabled} disabled={!canEdit} className="dna-preference-switch"
                aria-label={t(rule.enabled ? 'dna.page.disableRuleLabel' : 'dna.page.enableRuleLabel').replace('{title}', rule.title)}
                onClick={event => {
                  const trigger = event.currentTarget;
                  onToggle(cabinId, rule.id);
                  requestAnimationFrame(() => { if (!trigger.isConnected) searchRef.current?.focus(); });
                }}>
                <span>{zh ? (rule.enabled ? '已启用' : '未启用') : (rule.enabled ? 'Enabled' : 'Disabled')}</span>
                <i aria-hidden="true"><b /></i>
              </button>
            </div>
            <h3>{rule.title}</h3>
            <p className="dna-preference-description" title={rule.preview}>{rule.preview}</p>
            <div className="dna-preference-bottomline">
              {!BROWSER_MODE && <span>{t(rule.source === 'ai' ? 'dna.page.aiLearned' : 'dna.page.manualSet')}</span>}
              <button type="button" className="dna-preference-edit" disabled={!canEdit} onClick={event => onEdit(event, cabinId, rule)}
                aria-label={t('dna.page.editRuleLabel').replace('{title}', rule.title)}><Pencil size={13} aria-hidden="true" />{t('dna.page.edit')}</button>
            </div>
          </article>;
        })}
      </div> : <div className="dna-library-empty">
        <Dna size={28} strokeWidth={1.3} aria-hidden="true" />
        <h3>{hasFilters ? (zh ? '没有匹配的偏好' : 'No matching preferences')
          : selectedCabin ? (zh ? `还没有${selectedCabin.name}偏好` : `No ${selectedCabin.name.toLowerCase()} preferences yet`)
            : (zh ? '还没有偏好' : 'No preferences yet')}</h3>
        {hasFilters ? <button type="button" className="studio-secondary" onClick={() => onFilterChange({ ...emptyDnaFilters, category: filters.category })}>{zh ? '清除筛选' : 'Clear filters'}</button>
          : <div className="dna-empty-suggestions">
            {(selectedCabin ? [selectedCabin] : cabins).map(cabin => {
              const Icon = cabin.icon;
              const example = dnaPreferenceExample(cabin.id, language);
              return <button key={cabin.id} type="button" disabled={!canEdit} data-category={cabin.id}
                onClick={event => (onExample ?? onAdd)(event, cabin.id)}>
                <Icon size={15} aria-hidden="true" /><span>{cabin.name}<strong>{onExample ? example.title : (zh ? '添加偏好' : 'Add preference')}</strong></span><Plus size={14} aria-hidden="true" />
              </button>;
            })}
          </div>}
      </div>}
    </div>
  </section>;
}
