import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, CircleAlert, Eye, EyeOff, Loader2, Settings2, ShieldCheck, X } from 'lucide-react';
import { useLanguage } from '../i18n/LanguageProvider';
import { completionUrl, forgetModelKey, loadCustomModelConfig, loadModelConfig, saveModelConfig, testBrowserModelConnection } from '../services/browser/modelConfig';
import { useHostedModel } from '../hooks/useHostedModel';
import { ChoiceSelect } from './ChoiceSelect';
import { ModelIdPicker } from './ModelIdPicker';
import type { BrowserModelChoice } from '../services/browser/modelConfig';
import type { BrowserModelConfig } from '../services/browser/modelConfig';
import { MODEL_CONFIG_EVENT, MODEL_SETTINGS_EVENT } from '../services/browser/runtime';

type Feedback = { kind: 'idle' | 'testing' | 'success' | 'limited' | 'error' | 'notice'; message?: string };

function connectionError(error: unknown, zh: boolean): string {
  const message = error instanceof Error ? error.message : '';
  if (!zh) return message || 'Connection failed. Check the endpoint and try again.';
  if (/401|403/.test(message)) return '接口鉴权失败，请检查密钥或服务商权限。';
  if (/402|429/.test(message)) return '服务商额度不足或请求受限，请检查账户额度后重试。';
  if (/404/.test(message)) return '找不到接口或模型，请核对 API 地址和模型 ID。';
  if (/timed out/i.test(message)) return '连接检查超时，请检查网络或接口地址后重试。';
  if (/CORS|Cannot reach/.test(message)) return '浏览器无法连接。请检查地址和网络；若服务商不支持跨域（CORS），请改用支持浏览器直连的接口，或运行完整本地版。';
  if (/catalog.*invalid|catalog.*large/i.test(message)) return '模型目录格式不受支持，可手动输入模型 ID。';
  return '连接失败，请检查接口、模型权限及服务商状态。';
}

export function BrowserModelSettings() {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const hosted = useHostedModel();
  const [open, setOpen] = useState(false);
  const [config, setConfig] = useState(loadModelConfig);
  const [reveal, setReveal] = useState(false);
  const [hasSavedKey, setHasSavedKey] = useState(false);
  const [models, setModels] = useState<BrowserModelChoice[]>([]);
  const [catalogLoaded, setCatalogLoaded] = useState(false);
  const [touched, setTouched] = useState({ baseUrl: false, model: false });
  const [feedback, setFeedback] = useState<Feedback>({ kind: 'idle' });
  const dialogRef = useRef<HTMLDialogElement>(null);
  const modelRef = useRef<HTMLInputElement>(null);
  const customDraftRef = useRef(loadCustomModelConfig());
  const requestRef = useRef<AbortController | null>(null);
  const isTesting = feedback.kind === 'testing';

  const stopRequest = () => {
    requestRef.current?.abort();
    requestRef.current = null;
  };
  const close = () => { stopRequest(); setReveal(false); setOpen(false); };
  const updateConfig = (patch: Partial<BrowserModelConfig>) => {
    if ('baseUrl' in patch || 'apiKey' in patch || 'source' in patch) {
      stopRequest(); setModels([]); setCatalogLoaded(false);
    }
    if (requestRef.current === null) setFeedback({ kind: 'idle' });
    setConfig(current => ({ ...current, ...patch }));
  };

  useEffect(() => {
    const show = () => {
      requestRef.current?.abort();
      const saved = loadModelConfig();
      customDraftRef.current = loadCustomModelConfig();
      setConfig(saved);
      setHasSavedKey(Boolean(saved.apiKey));
      setModels([]); setCatalogLoaded(false);
      setTouched({ baseUrl: false, model: false });
      setFeedback({ kind: 'idle' });
      setReveal(false);
      setOpen(true);
    };
    window.addEventListener(MODEL_SETTINGS_EVENT, show);
    return () => { window.removeEventListener(MODEL_SETTINGS_EVENT, show); requestRef.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current!;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.showModal();
    modelRef.current?.focus({ preventScroll: true });
    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
      window.setTimeout(() => { if (trigger?.isConnected) trigger.focus(); }, 0);
    };
  }, [open]);

  const isHosted = config.source === 'hosted';
  let destination = '';
  let urlError = '';
  try { if (!isHosted) destination = new URL(completionUrl(config.baseUrl)).hostname; }
  catch { urlError = zh ? '填写有效的 HTTPS 接口地址，本地服务可用 HTTP。地址不能包含密钥、查询参数或片段。' : 'Use an HTTPS endpoint (HTTP for localhost), without credentials, query parameters or fragments.'; }
  const modelError = config.model.trim() ? '' : (zh ? '请填写服务商提供的模型 ID。' : 'Enter the model ID from your provider.');
  const canSubmit = isHosted ? hosted.status === 'available' : !urlError && !modelError;

  const test = async () => {
    if (isHosted ? hosted.status !== 'available' : Boolean(urlError)) return;
    stopRequest();
    const controller = new AbortController();
    requestRef.current = controller;
    setFeedback({ kind: 'testing' });
    try {
      const result = await testBrowserModelConnection(config, controller.signal);
      if (controller.signal.aborted || requestRef.current !== controller) return;
      setModels(result.models); setCatalogLoaded(true);
      setFeedback(result.status === 'unsupported'
        ? { kind: 'limited', message: zh ? '接口未提供模型目录，可手动填写 ID。尚未验证生成能力。' : 'No model catalog is exposed. Enter an ID manually; generation remains unverified.' }
        : result.status === 'hosted'
          ? { kind: 'success', message: zh ? '体验服务在线。未发起生成请求。' : 'Demo service is online. No generation request was sent.' }
          : { kind: result.models.length ? 'success' : 'limited', message: zh
            ? `已读取 ${result.models.length} 个模型。未验证生成权限。`
            : `Models listed: ${result.models.length}. Generation access is unverified.` });
    } catch (error) {
      if (controller.signal.aborted || requestRef.current !== controller) return;
      setFeedback({ kind: 'error', message: connectionError(error, zh) });
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
    }
  };

  const save = () => {
    setTouched({ baseUrl: true, model: true });
    if (!canSubmit) return;
    try {
      saveModelConfig(config);
      window.dispatchEvent(new Event(MODEL_CONFIG_EVENT));
      close();
    } catch {
      setFeedback({ kind: 'error', message: zh ? '无法保存，请检查浏览器是否允许本地存储。' : 'Could not save. Check that browser storage is available.' });
    }
  };

  const forgetKey = () => {
    stopRequest();
    try {
      forgetModelKey();
      customDraftRef.current = { ...customDraftRef.current, apiKey: '', rememberKey: false };
      setModels([]); setCatalogLoaded(false);
      setConfig(current => ({ ...current, apiKey: '', rememberKey: false }));
      setReveal(false);
      setHasSavedKey(false);
      setFeedback({ kind: 'notice', message: zh ? '密钥已清除。其他编辑仍保留，可继续保存。' : 'Key removed. Your other edits are still here.' });
      window.dispatchEvent(new Event(MODEL_CONFIG_EVENT));
    } catch {
      setFeedback({ kind: 'error', message: zh ? '无法清除密钥，请检查浏览器存储权限。' : 'Could not remove the key. Check browser storage permissions.' });
    }
  };

  if (!open) return null;

  return (
    <dialog ref={dialogRef} className="studio-dialog model-settings-dialog" aria-labelledby="browser-model-title"
      onCancel={event => { event.preventDefault(); close(); }}
      onClick={event => {
        if (event.target !== event.currentTarget) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) close();
      }}
      onKeyDown={event => event.stopPropagation()} onKeyUp={event => event.stopPropagation()}>
      <form className="flex max-h-[calc(100dvh-2rem)] flex-col" noValidate onSubmit={event => { event.preventDefault(); save(); }}>
        <header className="flex shrink-0 items-start justify-between gap-4 px-5 pb-5 pt-5 sm:px-7 sm:pt-6">
          <div>
            <h2 id="browser-model-title" className="text-lg font-semibold tracking-tight text-slate-900 dark:text-slate-100">{zh ? '模型设置' : 'Model settings'}</h2>
            <p className="mt-1.5 text-xs leading-5 text-slate-500 dark:text-slate-400">{zh ? '使用默认体验，或连接你自己的模型。' : 'Try the shared model or connect your own.'}</p>
          </div>
          <button type="button" aria-label={zh ? '关闭' : 'Close'} onClick={close} className="studio-icon-button -mr-2 -mt-2"><X size={17} /></button>
        </header>

        <div className="min-h-0 space-y-4 overflow-y-auto px-5 pb-5 sm:px-7">
          {(hosted.status === 'available' || isHosted) && <div className="model-source-picker" role="group" aria-label={zh ? '模型来源' : 'Model source'}>
            <button type="button" aria-pressed={isHosted} disabled={hosted.status !== 'available'} onClick={() => {
              if (!isHosted) customDraftRef.current = config;
              updateConfig({ source: 'hosted', baseUrl: '/api/model', model: hosted.model, apiKey: '' });
            }}><span>GLM-5.3-Flash</span><small>{hosted.status === 'available' ? (zh ? '默认体验 · 无需密钥' : 'Shared demo · no key needed') : (zh ? '暂不可用' : 'Temporarily unavailable')}</small></button>
            <button type="button" aria-pressed={!isHosted} onClick={() => {
              if (isHosted) { stopRequest(); setModels([]); setCatalogLoaded(false); setFeedback({ kind: 'idle' }); setConfig({ ...customDraftRef.current, source: 'custom' }); }
            }}><span>{zh ? '自己的模型' : 'Your own model'}</span><small>{zh ? '使用你的 API 与额度' : 'Use your API and allowance'}</small></button>
          </div>}
          {isHosted && <p className="text-xs leading-6 text-slate-500 dark:text-slate-400">{zh ? '可以直接生成、评审和局部编辑。共享额度用尽时，可切换到自己的模型继续。' : 'Generate, review and edit directly. Switch to your own model if the shared allowance is reached.'}</p>}
          {!isHosted && <>
          <div>
            <div className="mb-2 flex items-center justify-between gap-3">
              <label htmlFor="browser-model-url" className="studio-field-label">{zh ? 'API 地址' : 'API base URL'}</label>
              <span className="text-[11px] text-slate-400 dark:text-slate-500">{zh ? 'OpenAI 兼容接口' : 'OpenAI-compatible'}</span>
            </div>
            <input id="browser-model-url" className="studio-form-input" type="url" required value={config.baseUrl} placeholder="https://api.openai.com/v1" spellCheck={false} autoComplete="off" autoCapitalize="none"
              aria-invalid={touched.baseUrl && Boolean(urlError)} aria-describedby={touched.baseUrl && urlError ? 'browser-model-url-error' : undefined}
              onBlur={() => setTouched(current => ({ ...current, baseUrl: true }))}
              onChange={event => { setReveal(false); updateConfig({ baseUrl: event.target.value, apiKey: '' }); }} />
            {touched.baseUrl && urlError && <p id="browser-model-url-error" className="studio-field-error">{urlError}</p>}
          </div>

          <div>
            <label htmlFor="browser-model-id" className="studio-field-label mb-2 block">{zh ? '模型 ID' : 'Model ID'}</label>
            <ModelIdPicker inputRef={modelRef} value={config.model} onChange={value => updateConfig({ model: value })}
              onBlur={() => { if (config.model.length > 0) setTouched(current => ({ ...current, model: true })); }} onLoad={() => { void test(); }}
              models={models} loading={isTesting} loaded={catalogLoaded} invalid={touched.model && Boolean(modelError)} zh={zh} />
            {touched.model && modelError && <p id="browser-model-id-error" className="studio-field-error">{modelError}</p>}
          </div>

          <div>
            <label htmlFor="browser-model-key" className="studio-field-label mb-2 block">API key</label>
            <div className="relative">
              <input id="browser-model-key" className="studio-form-input pr-12" type={reveal ? 'text' : 'password'} value={config.apiKey} autoComplete="off" autoCapitalize="none" spellCheck={false}
                aria-describedby="browser-model-storage-hint" placeholder={zh ? '填写密钥；无鉴权接口可留空' : 'Your API key, if required'}
                onChange={event => updateConfig({ apiKey: event.target.value })} />
              <button type="button" onClick={() => setReveal(current => !current)} aria-pressed={reveal} aria-label={zh ? (reveal ? '隐藏密钥' : '显示密钥') : (reveal ? 'Hide key' : 'Show key')}
                className="studio-icon-button absolute right-0 top-0">{reveal ? <EyeOff size={16} /> : <Eye size={16} />}</button>
            </div>
            <div className="mt-1 flex flex-wrap items-center justify-between gap-x-2">
              <label className="flex min-h-11 cursor-pointer items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                <input type="checkbox" checked={config.rememberKey} onChange={event => updateConfig({ rememberKey: event.target.checked })} aria-describedby="browser-model-storage-hint" className="h-3.5 w-3.5 rounded border-slate-300 bg-transparent text-indigo-500 checked:bg-indigo-500 focus:ring-indigo-400 dark:border-slate-500 dark:bg-transparent dark:checked:bg-indigo-500" />
                {zh ? '在此设备记住密钥' : 'Remember on this device'}
              </label>
              {(hasSavedKey || config.apiKey) && <button type="button" onClick={forgetKey} className="studio-secondary -mr-2 px-2 text-[11px] hover:text-rose-600 dark:hover:text-rose-300">{zh ? '清除密钥' : 'Remove key'}</button>}
            </div>
            <p id="browser-model-storage-hint" className="text-[11px] leading-5 text-slate-500 dark:text-slate-400">{zh ? '默认仅保留在当前标签页；公共设备请勿勾选。' : 'Tab-only by default. Leave unchecked on shared devices.'}</p>
          </div>
          </>}

          <details className="studio-details">
            <summary><span className="studio-disclosure-label"><Settings2 size={15} aria-hidden="true" />{zh ? '高级设置与连接帮助' : 'Advanced settings & help'}</span><ChevronDown size={14} aria-hidden="true" /></summary>
            <div className="space-y-4 pb-1 pt-2">
              <label className="relative flex min-h-11 cursor-pointer items-center gap-3">
                <input type="checkbox" role="switch" checked={config.refine} onChange={event => updateConfig({ refine: event.target.checked })} aria-describedby="browser-model-review-hint" className="peer absolute inset-0 z-10 h-full w-full cursor-pointer opacity-0" />
                <span aria-hidden="true" className="studio-switch" />
                <span className="text-xs text-slate-600 dark:text-slate-300">{zh ? '生成后评审' : 'Review after generation'}<span id="browser-model-review-hint" className="mt-1 block text-[11px] text-slate-500 dark:text-slate-400">{zh ? '额外调用一次模型' : 'One extra model call'}</span></span>
              </label>
              {!isHosted && <>
              <div className="flex items-center justify-between gap-3 text-xs text-slate-600 dark:text-slate-300"><span>{zh ? '推理强度' : 'Reasoning effort'}</span>
                <ChoiceSelect label={zh ? '推理强度' : 'Reasoning effort'} value={config.reasoningEffort || ''} placement="below" menuWidth={168} align="end"
                  options={[{ value: '', label: zh ? '服务商默认' : 'Provider default' }, { value: 'low', label: zh ? '低' : 'Low' }, { value: 'medium', label: zh ? '中' : 'Medium' }, { value: 'high', label: zh ? '高' : 'High' }]}
                  onChange={value => updateConfig({ reasoningEffort: (value || undefined) as BrowserModelConfig['reasoningEffort'] })} />
              </div>
              <p className="text-[11px] leading-5 text-slate-500 dark:text-slate-400">{zh ? '仅支持 reasoning_effort 的模型可调整；不确定时保持默认。接口须支持 Chat Completions 和浏览器跨域（CORS）。切换地址会清空密钥输入。' : 'Adjust only for models supporting reasoning_effort; otherwise keep the default. Your endpoint must support Chat Completions and browser access (CORS). Changing the URL clears the key field.'}</p>
              <div className="flex flex-wrap items-center gap-x-3">
                <button type="button" className="studio-secondary -ml-2 px-2 text-xs" onClick={() => {
                  setReveal(false);
                  setTouched({ baseUrl: false, model: false });
                  updateConfig({ baseUrl: 'https://openrouter.ai/api/v1', model: '', apiKey: '' });
                  setFeedback({ kind: 'notice', message: zh ? '已切换到 OpenRouter，请填写对应的模型 ID 和密钥。' : 'Switched to OpenRouter. Enter its model ID and key.' });
                  modelRef.current?.focus();
                }}>{zh ? '使用 OpenRouter' : 'Use OpenRouter'}</button>
                <a href="https://openrouter.ai/models" target="_blank" rel="noopener noreferrer" className="studio-secondary px-2 text-xs">{zh ? '查看 OpenRouter 模型 ↗' : 'Browse OpenRouter models ↗'}</a>
              </div>
              </>}
            </div>
          </details>
          <details className="studio-details model-connection-details">
            <summary><span className="studio-disclosure-label"><ShieldCheck size={15} aria-hidden="true" />{zh ? '数据与费用说明' : 'Data & billing'}</span><ChevronDown size={14} aria-hidden="true" /></summary>
            <dl className="model-connection-facts">
              <div><dt>{zh ? '请求去向' : 'Destination'}</dt><dd>{isHosted ? (zh ? 'EvoDesign → 智谱' : 'EvoDesign → BigModel') : destination || (zh ? '你指定的服务商' : 'Your provider')}</dd></div>
              <div><dt>{zh ? '密钥保管' : 'API key'}</dt><dd>{isHosted ? (zh ? '仅保存在服务端' : 'Kept on the server') : (zh ? '仅保留在你的浏览器，不发送给 EvoDesign' : 'Kept in your browser; never sent to EvoDesign')}</dd></div>
              <div><dt>{zh ? '项目存储' : 'Projects'}</dt><dd>{zh ? '当前浏览器' : 'This browser'}</dd></div>
              {!isHosted && <div><dt>{zh ? '使用费用' : 'Billing'}</dt><dd>{zh ? '由模型服务商收取' : 'Billed by your model provider'}</dd></div>}
            </dl>
          </details>
        </div>

        <footer className="shrink-0 space-y-3 border-t border-slate-200/70 px-5 pb-[max(env(safe-area-inset-bottom),1.25rem)] pt-4 dark:border-white/[0.07] sm:px-7">
          {feedback.kind === 'idle' && <p className="text-[11px] leading-5 text-slate-500 dark:text-slate-400">{zh ? '连接检查仅读取目录，不发送生成请求。' : 'Connection checks read metadata only; no generation request is sent.'}</p>}
          {feedback.kind !== 'idle' && <div role={feedback.kind === 'error' ? 'alert' : 'status'} aria-live="polite"
            className={`flex items-start gap-2 text-xs leading-5 ${feedback.kind === 'error' ? 'text-rose-600 dark:text-rose-300' : feedback.kind === 'success' ? 'text-teal-700 dark:text-teal-300' : feedback.kind === 'limited' ? 'text-amber-700 dark:text-amber-300' : 'text-slate-500 dark:text-slate-400'}`}>
            {isTesting ? <Loader2 size={14} className="mt-0.5 shrink-0 animate-spin" /> : feedback.kind === 'success' ? <Check size={14} className="mt-0.5 shrink-0" /> : feedback.kind === 'error' || feedback.kind === 'limited' ? <CircleAlert size={14} className="mt-0.5 shrink-0" /> : null}
            <span>{isTesting ? (zh ? '正在读取模型目录，不发送生成请求…' : 'Reading the catalog. No generation request is sent…') : feedback.message}</span>
          </div>}
          <div className="flex items-center justify-between gap-2">
            <button type="button" className="studio-secondary -ml-2 px-2 text-xs" disabled={!isTesting && (isHosted ? hosted.status !== 'available' : Boolean(urlError))} title={zh ? '仅读取模型目录，不调用生成接口' : 'Reads metadata only; does not call generation'}
              onClick={() => {
                if (isTesting) { stopRequest(); setFeedback({ kind: 'notice', message: zh ? '测试已停止。' : 'Test stopped.' }); }
                else void test();
              }}>{isTesting ? (zh ? '停止测试' : 'Stop test') : (zh ? '检查连接' : 'Check connection')}</button>
            <div className="flex items-center gap-1 sm:gap-2">
              <button type="button" onClick={close} className="studio-secondary px-2 sm:px-3">{zh ? '取消' : 'Cancel'}</button>
              <button type="submit" className="studio-primary" disabled={!canSubmit}>{zh ? '保存' : 'Save'}</button>
            </div>
          </div>
        </footer>
      </form>
    </dialog>
  );
}
