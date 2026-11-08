const QUOTA_CODES = ['visitor_quota', 'daily_quota', 'run_quota', 'quota'] as const;

type SharedModelQuota = typeof QUOTA_CODES[number];

export function isSharedModelQuota(code: unknown): code is SharedModelQuota {
  return QUOTA_CODES.some(value => value === code);
}

/** Only trust known codes from the same-origin shared model route. */
export async function readSharedModelQuota(response: Response): Promise<SharedModelQuota | null> {
  if (response.status !== 429) return null;
  const body = await response.clone().json().catch(() => null);
  const code = body?.error?.code;
  return isSharedModelQuota(code) ? code : null;
}
