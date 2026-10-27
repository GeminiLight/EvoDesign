import { useEffect, useRef, useState } from 'react';
import { Check, ExternalLink, Eye, EyeOff, KeyRound, Loader2, ShieldCheck, X } from 'lucide-react';
import { useLanguage } from '../i18n/LanguageProvider';
import { callBrowserModel, completionUrl, forgetModelKey, loadModelConfig, saveModelConfig } from '../services/browser/modelConfig';
import { MODEL_CONFIG_EVENT, MODEL_SETTINGS_EVENT } from '../services/browser/runtime';

export function BrowserModelSettings() {
  const { language } = useLanguage(); const zh = language === 'zh';
  const [open, setOpen] = useState(false);
  const [config, setConfig] = useState(loadModelConfig);
  const [reveal, setReveal] = useState(false);
  const [status, setStatus] = useState<'idle' | 'testing' | 'success' | 'error'>('idle');
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
      await callBrowserModel(config, 'Reply with OK.', 'Connection test.', controller.signal, 32);
      if (controller.signal.aborted) return;
      setStatus('success'); setMessage(zh ? '连接成功，可以开始创作。' : 'Connected. You are ready to create.');
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
  return <dialog ref={dialog} className="workspace-settings-dialog w-[min(560px,calc(100vw-24px))]" aria-labelledby="browser-model-title"
    onCancel={close} onClose={() => { if (open) close(); }} onClick={event => { if (event.target === event.currentTarget) close(); }}
    onKeyDown={event => event.stopPropagation()} onKeyUp={event => event.stopPropagation()}>
    <form className="p-5 sm:p-7" onSubmit={event => { event.preventDefault(); save(); }}>
      <div className="mb-5 flex items-start gap-3">
        <span className="rounded-2xl bg-gradient-to-br from-cyan-100 to-violet-100 p-3 text-indigo-600"><KeyRound size={21} /></span>
        <div className="flex-1"><h2 id="browser-model-title" className="text-lg font-semibold text-slate-900 dark:text-white">{zh ? '连接你的模型' : 'Connect your model'}</h2>
          <p className="mt-1 text-sm text-slate-500">{zh ? '你的模型，你的画布。无需注册。' : 'Your model. Your canvas. No account needed.'}</p></div>
        <button type="button" aria-label={zh ? '关闭' : 'Close'} onClick={close} className="tool-button h-9 w-9 border-0 p-0"><X size={18} /></button>
      </div>
      <div className="space-y-4">
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
        <p className="flex items-start gap-2 text-xs leading-5 text-slate-500"><ShieldCheck size={16} className="mt-0.5 shrink-0 text-teal-600" /><span>{zh ? `请求由浏览器直接发送到 ${destination || '指定服务商'}；EvoDesign 不接收密钥。服务商需要允许浏览器跨域访问（CORS），费用由你的账户承担。` : `Requests go directly from this browser to ${destination || 'your provider'}; EvoDesign does not receive the key. Your provider must allow browser access (CORS). Usage is billed to your provider account.`}</span></p>
        {message && <p role="status" className={`rounded-xl p-3 text-xs leading-5 ${status === 'success' ? 'bg-teal-50 text-teal-800' : 'bg-rose-50 text-rose-800'}`}>{message}</p>}
      </div>
      <div className="mt-6 flex flex-wrap items-center justify-end gap-2">
        <button type="button" className="mr-auto min-h-10 text-xs text-slate-500 hover:text-rose-600" onClick={() => { request.current?.abort(); forgetModelKey(); setConfig(loadModelConfig()); setStatus('idle'); setMessage(''); window.dispatchEvent(new Event(MODEL_CONFIG_EVENT)); }}>{zh ? '清除已保存的密钥' : 'Forget saved key'}</button>
        <button type="button" disabled={status === 'testing'} onClick={() => void test()} className="tool-button min-h-11 gap-2 px-4">{status === 'testing' ? <Loader2 size={15} className="animate-spin" /> : <ExternalLink size={15} />}{zh ? '测试连接' : 'Test connection'}</button>
        <button type="submit" disabled={status === 'testing'} className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-indigo-600 px-5 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"><Check size={16} />{zh ? '保存' : 'Save'}</button>
      </div>
    </form>
  </dialog>;
}
