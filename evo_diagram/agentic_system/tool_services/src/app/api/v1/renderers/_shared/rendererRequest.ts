import { MAX_RENDERER_VIEWPORT } from '@/lib/renderDefaults';

export class RendererInputError extends Error {}

type JsonObject = Record<string, unknown>;

export type RendererViewport = {
    width: number;
    height: number;
};

const LOCAL_RENDERER_HOSTS = new Set([
    'localhost',
    '127.0.0.1',
    '::1',
    '[::1]',
    '0.0.0.0',
]);
function isObject(value: unknown): value is JsonObject {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasOwn(value: JsonObject, key: string): boolean {
    return Object.prototype.hasOwnProperty.call(value, key);
}

function normalizePathname(pathname: string): string {
    if (pathname === '/') return pathname;
    return pathname.replace(/\/+$/, '');
}

function readBoundedNumber(
    value: unknown,
    options: {
        field: string;
        fallback: number;
        min: number;
        max: number;
    },
): number {
    const { field, fallback, min, max } = options;
    if (value === undefined || value === null) return fallback;
    if (typeof value !== 'number' || !Number.isFinite(value)) {
        throw new RendererInputError(`${field} must be a finite number`);
    }
    if (value < min || value > max) {
        throw new RendererInputError(`${field} must be between ${min} and ${max}`);
    }
    return value;
}

export function parseRendererRequestBody(value: unknown): JsonObject {
    if (!isObject(value)) {
        throw new RendererInputError('Request body must be a JSON object');
    }
    if (hasOwn(value, 'url')) {
        throw new RendererInputError(
            'Renderer URL overrides are not accepted; configure the service renderer URL on the server.',
        );
    }
    return value;
}

export async function parseRendererJsonRequest(request: Request): Promise<JsonObject> {
    try {
        return parseRendererRequestBody(await request.json());
    } catch (error) {
        if (error instanceof RendererInputError) {
            throw error;
        }
        throw new RendererInputError('Request body must be valid JSON');
    }
}

export function readRequiredField(
    body: JsonObject,
    field: string,
    label: string = field,
): unknown {
    if (!hasOwn(body, field) || body[field] === undefined || body[field] === null) {
        throw new RendererInputError(`${label} is required`);
    }
    return body[field];
}

export function resolveRendererUrl(defaultUrl: string, expectedPathname: string): string {
    let parsed: URL;
    try {
        parsed = new URL(defaultUrl);
    } catch {
        throw new RendererInputError('Configured renderer URL is invalid');
    }

    if (!['http:', 'https:'].includes(parsed.protocol)) {
        throw new RendererInputError('Configured renderer URL must use http or https');
    }
    if (!LOCAL_RENDERER_HOSTS.has(parsed.hostname)) {
        throw new RendererInputError('Configured renderer URL must point to a local host');
    }
    if (normalizePathname(parsed.pathname) !== normalizePathname(expectedPathname)) {
        throw new RendererInputError(
            `Configured renderer URL must point to ${expectedPathname}`,
        );
    }

    return parsed.toString();
}

export function parseViewport(
    value: unknown,
    defaults: RendererViewport,
): RendererViewport {
    if (value === undefined || value === null) return defaults;
    if (!isObject(value)) {
        throw new RendererInputError('viewport must be a JSON object');
    }
    if (hasOwn(value, 'margin')) {
        throw new RendererInputError(
            'viewport.margin is not supported by snapshot routes; use the renderer CLI margin option for clipped exports.',
        );
    }

    return {
        width: readBoundedNumber(value.width, {
            field: 'viewport.width',
            fallback: defaults.width,
            min: 1,
            max: MAX_RENDERER_VIEWPORT.width,
        }),
        height: readBoundedNumber(value.height, {
            field: 'viewport.height',
            fallback: defaults.height,
            min: 1,
            max: MAX_RENDERER_VIEWPORT.height,
        }),
    };
}
