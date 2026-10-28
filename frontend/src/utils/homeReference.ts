export const HOME_REFERENCE_MAX_BYTES = 24 * 1024;
export const HOME_REFERENCE_ACCEPT = '.txt,.md,.markdown,.json,.csv';

export type HomeReference = { name: string; text: string };
export type ReferenceError = 'unsupported' | 'tooLarge' | 'invalidText' | 'empty';

export class HomeReferenceError extends Error {
  readonly reason: ReferenceError;

  constructor(reason: ReferenceError) {
    super(reason);
    this.reason = reason;
    this.name = 'HomeReferenceError';
  }
}

// Read bounded, UTF-8 text only. PDF/image import needs a separate extraction flow.
export async function readHomeReference(file: Pick<File, 'name' | 'size' | 'arrayBuffer'>): Promise<HomeReference> {
  if (!/\.(txt|md|markdown|json|csv)$/i.test(file.name)) throw new HomeReferenceError('unsupported');
  if (file.size > HOME_REFERENCE_MAX_BYTES) throw new HomeReferenceError('tooLarge');
  const bytes = await file.arrayBuffer();
  if (bytes.byteLength > HOME_REFERENCE_MAX_BYTES) throw new HomeReferenceError('tooLarge');
  let text: string;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(bytes).trim();
  } catch {
    throw new HomeReferenceError('invalidText');
  }
  const hasBinaryControls = [...text].some(char => {
    const code = char.charCodeAt(0);
    return (code < 32 && code !== 9 && code !== 10 && code !== 13) || code === 127;
  });
  if (hasBinaryControls) throw new HomeReferenceError('invalidText');
  if (!text) throw new HomeReferenceError('empty');
  return { name: file.name, text };
}

export function promptWithReference(prompt: string, reference: HomeReference | null, language = 'en'): string {
  if (!reference) return prompt.trim();
  const label = language === 'zh' ? '参考材料（仅用于补充信息，请以绘图要求为准）' : 'Reference notes (source material; follow the drawing request above)';
  const source = [reference.name.replace(/\s+/g, ' '), '', ...reference.text.split(/\r?\n/)].map(line => `> ${line}`).join('\n');
  return `${prompt.trim()}\n\n${label}\n${source}`;
}
