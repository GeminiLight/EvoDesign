import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { createCanvas, registerFont } from 'canvas';

export type TextWidthRequest = {
  text: string;
  fontSize: number;
  font?: string;
};

export type TextWidthResult = {
  width: number;
  height: number;
  status: 'ok';
};

export class TextWidthInputError extends Error {}

const SYSTEM_FONT_FALLBACKS: Record<string, string> = {
  mono: 'DejaVu Sans Mono',
  sans: 'Nimbus Sans',
  serif: 'FreeSerif',
  draw: 'sans-serif',
};

const FONT_FILE_NAMES: Record<string, string> = {
  mono: 'IBMPlexMono-Medium.ttf',
  sans: 'IBMPlexSans-Medium.ttf',
  serif: 'IBMPlexSerif-Medium.ttf',
  draw: 'Shantell_Sans-Informal_Regular.ttf',
};

export const SUPPORTED_TEXT_WIDTH_FONTS = new Set(Object.keys(FONT_FILE_NAMES));
export const MAX_TEXT_WIDTH_TEXT_LENGTH = 10000;
export const MAX_TEXT_WIDTH_FONT_SIZE = 512;

const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));
let fontsInitialized = false;
const registeredFonts: Record<string, string> = {};

function candidateFontDirs(anchor: string): string[] {
  const candidates: string[] = [];
  let current = path.resolve(anchor);

  for (let depth = 0; depth < 8; depth += 1) {
    candidates.push(
      path.join(current, 'evo_diagram/resources/fonts'),
      path.join(current, 'resources/fonts'),
    );
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }

  return candidates;
}

export function resolveFontsDir(): string {
  const candidates = [
    ...candidateFontDirs(process.cwd()),
    ...candidateFontDirs(MODULE_DIR),
  ];
  const uniqueCandidates = Array.from(new Set(candidates));
  return uniqueCandidates.find((candidate) => fs.existsSync(candidate)) || uniqueCandidates[0];
}

export function initTextWidthFonts(): Record<string, string> {
  if (fontsInitialized) return registeredFonts;

  const fontsDir = resolveFontsDir();
  Object.entries(FONT_FILE_NAMES).forEach(([alias, fileName]) => {
    const filePath = path.join(fontsDir, fileName);
    if (fs.existsSync(filePath)) {
      try {
        registerFont(filePath, { family: alias });
        registeredFonts[alias] = alias;
      } catch {
        registeredFonts[alias] = SYSTEM_FONT_FALLBACKS[alias];
      }
    } else {
      registeredFonts[alias] = SYSTEM_FONT_FALLBACKS[alias];
    }
  });
  fontsInitialized = true;
  return registeredFonts;
}

function readText(value: unknown): string {
  if (typeof value !== 'string') {
    throw new TextWidthInputError('text must be a string');
  }
  if (value.length > MAX_TEXT_WIDTH_TEXT_LENGTH) {
    throw new TextWidthInputError(
      `text must be at most ${MAX_TEXT_WIDTH_TEXT_LENGTH} characters`,
    );
  }
  return value;
}

function readFontSize(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new TextWidthInputError('fontSize must be a finite number');
  }
  if (value <= 0 || value > MAX_TEXT_WIDTH_FONT_SIZE) {
    throw new TextWidthInputError(
      `fontSize must be greater than 0 and at most ${MAX_TEXT_WIDTH_FONT_SIZE}`,
    );
  }
  return value;
}

function readOptionalFont(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== 'string') {
    throw new TextWidthInputError('font must be a string');
  }
  if (!SUPPORTED_TEXT_WIDTH_FONTS.has(value)) {
    throw new TextWidthInputError(
      `font must be one of: ${Array.from(SUPPORTED_TEXT_WIDTH_FONTS).join(', ')}`,
    );
  }
  return value;
}

export function parseTextWidthRequest(value: unknown): TextWidthRequest {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new TextWidthInputError('Request body must be a JSON object');
  }
  const body = value as Record<string, unknown>;
  if (body.text === undefined || body.text === null) {
    throw new TextWidthInputError('Missing required field: text');
  }
  if (body.fontSize === undefined || body.fontSize === null) {
    throw new TextWidthInputError('Missing required field: fontSize');
  }
  return {
    text: readText(body.text),
    fontSize: readFontSize(body.fontSize),
    font: readOptionalFont(body.font),
  };
}

export function measureTextWidth(request: TextWidthRequest): TextWidthResult {
  const fonts = initTextWidthFonts();
  const canvas = createCanvas(100, 100);
  const ctx = canvas.getContext('2d');
  const fontAlias = request.font && fonts[request.font] ? request.font : 'sans';
  const fontFamily = fonts[fontAlias] || 'sans-serif';

  ctx.font = `${request.fontSize}px "${fontFamily}"`;
  const metrics = ctx.measureText(request.text);
  const height = metrics.actualBoundingBoxAscent + metrics.actualBoundingBoxDescent || request.fontSize;

  return {
    width: metrics.width,
    height,
    status: 'ok',
  };
}
