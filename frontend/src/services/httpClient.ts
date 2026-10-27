import { BROWSER_MODE } from './browser/runtime';
import { notifyAuthInvalidated } from '../features/auth/authEvents';
import { readLocalStorage } from '../utils/safeLocalStorage';

const RAW_API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:3010';

export const API_BASE_URL = RAW_API_BASE_URL.replace(/\/+$/, '').replace(/\/api$/, '');
export const API_V1_BASE_URL = `${API_BASE_URL}/api/v1`;

export class ApiError extends Error {
  status: number;
  detail: string;
  code?: string;

  constructor(message: string, status: number, detail = message, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.code = code;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

function normalizeApiPath(path: string): string {
  return path.startsWith('/') ? path : `/${path}`;
}

export function apiV1Url(path: string): string {
  return `${API_V1_BASE_URL}${normalizeApiPath(path)}`;
}

export function getStoredAuthToken(): string | null {
  return BROWSER_MODE ? null : readLocalStorage('auth_token');
}

export function requireStoredAuthToken(message = '未登录，请先登录'): string {
  const token = getStoredAuthToken();
  if (!token) {
    throw new Error(message);
  }
  return token;
}

export function notifyIfUnauthorized(response: Response): void {
  if (response.status === 401) {
    notifyAuthInvalidated();
  }
}

export async function readResponseDetail(response: Response, fallback: string): Promise<string> {
  try {
    const errorData = await response.json() as { detail?: unknown; error?: unknown };
    if (typeof errorData.detail === 'string') return errorData.detail;
    if (typeof errorData.error === 'string') return errorData.error;
    return fallback;
  } catch {
    return response.statusText || fallback;
  }
}
