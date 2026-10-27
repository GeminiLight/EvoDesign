import { useEffect, useRef, useState } from 'react';
import { Check, ExternalLink, Eye, EyeOff, KeyRound, Loader2, ShieldCheck, X } from 'lucide-react';
import { useLanguage } from '../i18n/LanguageProvider';
import { completionUrl, forgetModelKey, loadModelConfig, saveModelConfig, testBrowserModelConnection } from '../services/browser/modelConfig';
import { MODEL_CONFIG_EVENT, MODEL_SETTINGS_EVENT } from '../services/browser/runtime';

export function BrowserModelSettings() {
  const { language } = useLanguage(); const zh = language === 'zh';
  const [open, setOpen] = useState(false);
  const [config, setConfig] = useState(loadModelConfig);
  const [reveal, setReveal] = useState(false);
  const [status, setStatus] = useState<'idle' | 'testing' | 'success' | 'limited' | 'error'>('idle');
  const [message, setMessage] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  const request = useRef<AbortController | null>(null);
  const close = () => { request.current?.abort(); setOpen(false); };
  useEffect(() => {
    const show = () => { setConfig(loadModelConfig()); setStatus('idle'); setMessage(''); setReveal(false); setOpen(true); };
    window.addEventListener(MODEL_SETTINGS_EVENT, show);
    return () => { window.removeEventListener(MODEL_SETTINGS_EVENT, show); request.current?.abort(); };
  }, []);
  useEffect(() => {
    if (!open) return;
    const element = dialog.current!; element.showModal();
    const overflow = document.body.style.overflow; document.body.style.overflow = 'hidden';
    return () => { element.close(); document.body.style.overflow = overflow; };
  }, [open]);
  const test = async () => {
    const controller = new AbortController(); request.current?.abort(); request.current = controller;
    setStatus('testing'); setMessage('');
    try {
      const result = await testBrowserModelConnection(config, controller.signal);
      if (controller.signal.aborted) return;
      setStatus(result === 'ready' ? 'success' : 'limited');
      setMessage(result === 'ready'
        ? (zh ? '连接成功，可以开始创作。' : 'Connected. You are ready to create.')
        : (zh ? '接口已连通，但模型在小额测试中用完了输出额度。生成时会使用更大额度；若仍无正文，请换用推理开销较小的模型。' : 'Endpoint connected, but the model used the small test budget before finishing. Generation allows more output; choose a less reasoning-heavy model if it still returns no text.'));
    } catch (error) {
      if (controller.signal.aborted) return;
      setStatus('error'); setMessage(error instanceof Error ? error.message : 'Connection failed.');
    }
  };
  const save = () => {
    try {
      saveModelConfig(config); window.dispatchEvent(new Event(MODEL_CONFIG_EVENT)); close();
    } catch (error) { setStatus('error'); setMessage(error instanceof Error ? error.message : 'Unable to save settings.'); }
  };
  const input = 'mt-2 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-3 text-sm text-slate-800 outline-none transition focus:border-indigo-400 focus:ring-4 focus:ring-indigo-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-indigo-500/15';
  let destination = '';
  try { destination = new URL(completionUrl(config.baseUrl)).hostname; } catch { /* Validation is shown on save/test. */ }
  return <dialog ref={dialog} className="workspace-settings-dialog overflow-hidden w-[min(560px,calc(100vw-24px))]" aria-labelledby="browser-model-title"
    onCancel={close} onClose={() => { if (open) close(); }} onClick={event => { if (event.target === event.currentTarget) close(); }}
    onKeyDown={event => event.stopPropagation()} onKeyUp={event => event.stopPropagation()}>
    <form className="flex max-h-[calc(100dvh-48px)] flex-col" onSubmit={event => { event.preventDefault(); save(); }}>
      <div className="flex shrink-0 items-start gap-3 px-5 pb-4 pt-5 sm:px-7 sm:pt-7">
        <span className="rounded-2xl bg-gradient-to-br from-cyan-100 to-violet-100 p-3 text-indigo-600"><KeyRound size={21} /></span>
        <div className="flex-1"><h2 id="browser-model-title" className="text-lg font-semibold text-slate-900 dark:text-white">{zh ? '连接你的模型' : 'Connect your model'}</h2>
          <p className="mt-1 text-sm text-slate-500">{zh ? '你的模型，你的画布。无需注册。' : 'Your model. Your canvas. No account needed.'}</p></div>
        <button type="button" aria-label={zh ? '关闭' : 'Close'} onClick={close} className="tool-button h-9 w-9 border-0 p-0"><X size={18} /></button>
      </div>
      <div className="min-h-0 space-y-4 overflow-y-auto px-5 pb-5 sm:px-7">
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
          {zh ? '需要支持浏览器直连的接口？' : 'Need a browser-compatible endpoint?'}
          <button type="button" className="font-semibold text-indigo-600 underline underline-offset-4 dark:text-indigo-300" onClick={() => {
            request.current?.abort(); setStatus('idle'); setMessage('');
            setConfig({ ...config, baseUrl: 'https://openrouter.ai/api/v1', model: '', apiKey: '' });
          }}>{zh ? '使用 OpenRouter' : 'Use OpenRouter'}</button>
          <a href="https://openrouter.ai/models" target="_blank" rel="noopener noreferrer" className="underline underline-offset-4">{zh ? '查看模型 ID' : 'Find model IDs'}</a>
        </p>
        <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">{zh ? 'API 地址' : 'API base URL'}
          <input className={input} type="url" required value={config.baseUrl} placeholder="https://api.openai.com/v1" spellCheck={false} autoComplete="off"
            onChange={event => { request.current?.abort(); setStatus('idle'); setMessage(''); setConfig({ ...config, baseUrl: event.target.value, apiKey: '' }); }} />
          <span className="mt-1.5 block text-xs font-normal leading-5 text-slate-500">{zh ? '支持 OpenAI 兼容的 Chat Completions 接口。切换地址会清空输入框中的密钥。' : 'An OpenAI-compatible Chat Completions endpoint. Changing the address clears the entered key.'}</span>
        </label>
        <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">{zh ? '模型名称' : 'Model identifier'}
          <input className={input} required value={config.model} placeholder={zh ? '填写服务商提供的模型 ID' : 'The exact model ID from your provider'} spellCheck={false} autoComplete="off"
            onChange={event => { request.current?.abort(); setStatus('idle'); setMessage(''); setConfig({ ...config, model: event.target.value }); }} />
        </label>
        <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">API key
          <span className="relative block"><input className={`${input} pr-12`} type={reveal ? 'text' : 'password'} value={config.apiKey} autoComplete="off" spellCheck={false}
            placeholder={zh ? '仅发送给你指定的模型服务商' : 'Sent only to the provider you choose'}
            onChange={event => { request.current?.abort(); setStatus('idle'); setMessage(''); setConfig({ ...config, apiKey: event.target.value }); }} />
            <button type="button" onClick={() => setReveal(!reveal)} aria-label={reveal ? (zh ? '隐藏密钥' : 'Hide key') : (zh ? '显示密钥' : 'Show key')} className="absolute right-2 top-2 flex h-9 w-9 items-center justify-center text-slate-500">{reveal ? <EyeOff size={17} /> : <Eye size={17} />}</button>
          </span>
        </label>
        <div className="space-y-3 rounded-xl bg-slate-50 p-3.5 dark:bg-slate-800/60">
          <label className="flex cursor-pointer items-start gap-2.5 text-sm text-slate-700 dark:text-slate-200"><input type="checkbox" className="mt-1 rounded border-slate-300 text-indigo-600" checked={config.rememberKey} onChange={e => setConfig({ ...config, rememberKey: e.target.checked })} />
            <span>{zh ? '在此设备记住密钥' : 'Remember the key on this device'}<span className="mt-0.5 block text-xs leading-5 text-slate-500">{zh ? '默认仅保留在当前标签页会话。勾选后存入浏览器本地存储，不适用于共享设备。' : 'Otherwise kept only for this tab session. Remembered keys use browser storage; avoid this on shared devices.'}</span></span>
          </label>
          <label className="flex cursor-pointer items-center gap-2.5 text-sm text-slate-700 dark:text-slate-200"><input type="checkbox" className="rounded border-slate-300 text-indigo-600" checked={config.refine} onChange={e => setConfig({ ...config, refine: e.target.checked })} />{zh ? '生成后进行一次内容评审（额外一次模型调用）' : 'Review content after generation (one extra model call)'}</label>
        </div>
        <details className="rounded-xl border border-slate-200 px-3.5 py-3 dark:border-slate-700">
          <summary className="cursor-pointer text-sm font-medium text-slate-600 dark:text-slate-300">{zh ? '高级模型选项' : 'Advanced model options'}</summary>
          <label className="mt-3 block text-sm text-slate-700 dark:text-slate-200">{zh ? '推理强度' : 'Reasoning effort'}
            <select className={input} value={config.reasoningEffort || ''} onChange={event => {
              request.current?.abort(); setStatus('idle'); setMessage('');
              setConfig({ ...config, reasoningEffort: (event.target.value || undefined) as typeof config.reasoningEffort });
            }}>
              <option value="">{zh ? '服务商默认（推荐）' : 'Provider default (recommended)'}</option>
              <option value="low">{zh ? '低' : 'Low'}</option><option value="medium">{zh ? '中' : 'Medium'}</option><option value="high">{zh ? '高' : 'High'}</option>
            </select>
            <span className="mt-1.5 block text-xs leading-5 text-slate-500">{zh ? '仅适用于支持 reasoning_effort 的模型。低强度可减少推理耗时，为图形内容留出更多输出空间；不支持时请选择默认。' : 'For models that support reasoning_effort. Low can reduce thinking time and leave more output for the diagram. Use the default if your provider does not support this option.'}</span>
          </label>
        </details>
        <p className="flex items-start gap-2 text-xs leading-5 text-slate-500"><ShieldCheck size={16} className="mt-0.5 shrink-0 text-teal-600" /><span>{zh ? `请求由浏览器直接发送到 ${destination || '指定服务商'}；EvoDesign 不接收密钥。服务商需要允许浏览器跨域访问（CORS），费用由你的账户承担。` : `Requests go directly from this browser to ${destination || 'your provider'}; EvoDesign does not receive the key. Your provider must allow browser access (CORS). Usage is billed to your provider account.`}</span></p>
        {status === 'testing' && <p role="status" className="text-xs text-slate-500">{zh ? '正在发送小额测试请求，最多等待 60 秒，可随时停止。' : 'Sending a small test request. Up to 60 seconds; you can stop at any time.'}</p>}
        {message && <p role="status" className={`rounded-xl p-3 text-xs leading-5 ${status === 'success' ? 'bg-teal-50 text-teal-800' : status === 'limited' ? 'bg-amber-50 text-amber-900' : 'bg-rose-50 text-rose-800'}`}>{message}</p>}
      </div>
      <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-slate-100 bg-white p-5 dark:border-slate-800 dark:bg-slate-900 sm:px-7">
        <button type="button" className="mr-auto min-h-10 text-xs text-slate-500 hover:text-rose-600" onClick={() => { request.current?.abort(); forgetModelKey(); setConfig(loadModelConfig()); setStatus('idle'); setMessage(''); window.dispatchEvent(new Event(MODEL_CONFIG_EVENT)); }}>{zh ? '清除已保存的密钥' : 'Forget saved key'}</button>
        <button type="button" onClick={() => {
          if (status === 'testing') { request.current?.abort(); setStatus('idle'); setMessage(''); }
          else void test();
        }} className="tool-button min-h-11 gap-2 px-4">{status === 'testing' ? <Loader2 size={15} className="animate-spin" /> : <ExternalLink size={15} />}{status === 'testing' ? (zh ? '停止测试' : 'Stop test') : (zh ? '测试连接' : 'Test connection')}</button>
        <button type="submit" className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-indigo-600 px-5 text-sm font-semibold text-white hover:bg-indigo-500"><Check size={16} />{zh ? '保存' : 'Save'}</button>
      </div>
    </form>
  </dialog>;
}
