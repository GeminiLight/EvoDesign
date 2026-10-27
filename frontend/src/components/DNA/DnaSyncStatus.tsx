import { useLanguage } from '../../i18n/LanguageProvider';
import type { useRuleLibrary } from '../../hooks/useRuleLibrary';
type Props = Pick<ReturnType<typeof useRuleLibrary>, 'syncStatus' | 'retrySync' | 'acceptServerRules'>;
export function DnaSyncStatus({ syncStatus, retrySync, acceptServerRules }: Props) {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const labels = {
    local: zh ? '保存在此浏览器' : 'Saved in this browser',
    loading: zh ? '正在加载云端偏好，请稍候…' : 'Loading your saved preferences…',
    saving: zh ? '正在同步…' : 'Syncing…',
    synced: zh ? '已同步' : 'Synced',
    failed: zh ? '同步失败；修改已保留在本机。' : 'Sync failed. Changes are kept on this device.',
    failedVolatile: zh ? '同步和本机保存均失败，请在离开前重试。' : 'Cloud and local saves failed. Retry before leaving this page.',
    loadFailed: zh ? '暂时无法加载云端偏好。重新加载后才能编辑，避免覆盖已有内容。' : 'Could not load cloud preferences. Reload before editing to protect existing rules.',
    conflict: zh ? '发现未同步的本机修改。已保留两份内容，请选择要继续使用的版本。' : 'Unsynced local changes found. Both copies are preserved; choose which version to continue with.',
  };
  const needsAction = ['failed', 'failedVolatile', 'loadFailed', 'conflict'].includes(syncStatus);
  return <div className={`flex flex-wrap items-center gap-3 rounded-lg py-2 text-xs ${needsAction ? 'px-3 border border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100' : 'text-slate-500 dark:text-slate-400'}`}>
    <span role="status">{labels[syncStatus]}</span>
    {needsAction && <button type="button" className="tool-button" onClick={retrySync}>{syncStatus === 'conflict' ? (zh ? '保留本机修改并同步' : 'Keep local changes and sync') : (zh ? '重试' : 'Retry')}</button>}
    {syncStatus === 'conflict' && <button type="button" className="tool-button" onClick={acceptServerRules}>{zh ? '使用云端版本' : 'Use cloud version'}</button>}
  </div>;
}
