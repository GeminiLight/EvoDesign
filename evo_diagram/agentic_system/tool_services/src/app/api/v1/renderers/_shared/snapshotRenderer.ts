import { NextResponse } from 'next/server';
import { chromium, type Browser, type BrowserContext, type Page } from 'playwright';
import {
    RendererInputError,
    parseRendererJsonRequest,
    parseViewport,
    readRequiredField,
    resolveRendererUrl,
} from './rendererRequest';
import {
    DEFAULT_RENDER_TIMEOUT_MS,
    DEFAULT_RENDERER_VIEWPORT,
    clampDeviceScaleFactor,
} from '@/lib/renderDefaults';

class RendererBusyError extends Error {}

function readPositiveIntEnv(name: string, fallback: number): number {
    const parsed = Number.parseInt(process.env[name] ?? '', 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

// Concurrent renders share one Chromium; each render gets its own context.
const MAX_CONCURRENT_RENDERS = readPositiveIntEnv('RENDERER_MAX_CONCURRENCY', 2);
// Requests beyond the running renders wait here; past this, reply 503.
const MAX_QUEUED_RENDERS = readPositiveIntEnv('RENDERER_MAX_QUEUE', 8);

// Public, fixed asset CDNs the canvas libraries load fonts from by default
// (tldraw: cdn.tldraw.com, Excalidraw: esm.sh). GET only; every other
// cross-origin request from the headless page is aborted so snapshot
// payloads cannot make the renderer fetch arbitrary (internal) URLs.
const ALLOWED_ASSET_ORIGINS = new Set(
    (process.env.RENDERER_ALLOWED_ASSET_ORIGINS ?? 'https://cdn.tldraw.com,https://esm.sh')
        .split(',')
        .map((origin) => origin.trim())
        .filter(Boolean),
);

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]']);

type RenderPool = {
    browser: Promise<Browser> | null;
    active: number;
    waiters: Array<() => void>;
};

// Kept on globalThis so every route bundle (and dev hot reloads) share it.
const POOL_KEY = Symbol.for('evodesign.renderer.pool');

function getPool(): RenderPool {
    const holder = globalThis as unknown as Record<symbol, RenderPool | undefined>;
    if (!holder[POOL_KEY]) {
        holder[POOL_KEY] = { browser: null, active: 0, waiters: [] };
    }
    return holder[POOL_KEY]!;
}

async function acquireRenderSlot(): Promise<() => void> {
    const pool = getPool();
    let released = false;
    const release = () => {
        if (released) return;
        released = true;
        const next = pool.waiters.shift();
        if (next) {
            next(); // hand the slot over; active count is unchanged
        } else {
            pool.active -= 1;
        }
    };
    if (pool.active < MAX_CONCURRENT_RENDERS) {
        pool.active += 1;
        return release;
    }
    if (pool.waiters.length >= MAX_QUEUED_RENDERS) {
        throw new RendererBusyError('Renderer is busy; retry later');
    }
    await new Promise<void>((resolve) => pool.waiters.push(resolve));
    return release;
}

function getSharedBrowser(): Promise<Browser> {
    const pool = getPool();
    if (!pool.browser) {
        const launching = chromium.launch({
            args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        });
        pool.browser = launching;
        launching.then(
            (browser) => browser.on('disconnected', () => {
                if (pool.browser === launching) pool.browser = null;
            }),
            () => {
                if (pool.browser === launching) pool.browser = null;
            },
        );
    }
    return pool.browser;
}

function isRendererOrigin(url: URL, renderer: URL): boolean {
    if (url.protocol !== renderer.protocol || url.port !== renderer.port) return false;
    return url.hostname === renderer.hostname
        || (LOOPBACK_HOSTS.has(url.hostname) && LOOPBACK_HOSTS.has(renderer.hostname));
}

export function isAllowedRendererRequest(
    rawUrl: string,
    method: string,
    rendererUrl: string,
): boolean {
    let url: URL;
    try {
        url = new URL(rawUrl);
    } catch {
        return false;
    }
    if (url.protocol === 'data:' || url.protocol === 'blob:') return true;
    if (isRendererOrigin(url, new URL(rendererUrl))) return true;
    return method === 'GET' && ALLOWED_ASSET_ORIGINS.has(url.origin);
}

async function blockForeignRequests(
    context: BrowserContext,
    rendererUrl: string,
): Promise<void> {
    await context.route('**/*', (route) => {
        const request = route.request();
        if (isAllowedRendererRequest(request.url(), request.method(), rendererUrl)) {
            return route.continue();
        }
        return route.abort('blockedbyclient');
    });
}

type SnapshotRendererSpec = {
    label: string;
    payloadField: string;
    payloadLabel: string;
    defaultRendererUrl: string;
    rendererPath: string;
    loaderFunctionName: string;
    capturePng: (page: Page) => Promise<Buffer>;
};

function pngResponse(buffer: Buffer) {
    const body = new Uint8Array(buffer);
    const response = new NextResponse(body);
    response.headers.set('Content-Type', 'image/png');
    return response;
}

async function waitForRendererLoader(
    page: Page,
    loaderFunctionName: string,
): Promise<void> {
    await page.waitForFunction(
        (name: string) => typeof (window as any)[name] === 'function',
        loaderFunctionName,
        { timeout: DEFAULT_RENDER_TIMEOUT_MS }
    );
}

async function loadRendererPayload(
    page: Page,
    loaderFunctionName: string,
    payload: unknown,
): Promise<void> {
    await page.evaluate(
        ({ name, data }: { name: string; data: unknown }) => {
            return (window as any)[name](data);
        },
        { name: loaderFunctionName, data: payload }
    );
}

async function waitForRenderCompletion(
    page: Page,
    fallbackErrorMessage: string,
): Promise<void> {
    const renderState = await Promise.race([
        page.waitForFunction(
            () => (window as any).__renderStatus === 'ready',
            null,
            { timeout: DEFAULT_RENDER_TIMEOUT_MS }
        ).then(() => 'ready'),
        page.waitForFunction(
            () => (window as any).__renderStatus === 'error',
            null,
            { timeout: DEFAULT_RENDER_TIMEOUT_MS }
        ).then(() => 'error'),
    ]);
    if (renderState === 'error') {
        const message = await page.evaluate(
            (fallback: string) => (window as any).__renderError || fallback,
            fallbackErrorMessage
        );
        throw new Error(String(message).trim());
    }
}

export async function renderSnapshotRequest(
    request: Request,
    spec: SnapshotRendererSpec,
) {
    let context: BrowserContext | null = null;
    let releaseSlot: (() => void) | null = null;
    try {
        const body = await parseRendererJsonRequest(request);
        const payload = readRequiredField(
            body,
            spec.payloadField,
            spec.payloadLabel
        );

        const rendererUrl = resolveRendererUrl(
            spec.defaultRendererUrl,
            spec.rendererPath
        );
        const viewport = parseViewport(body.viewport, DEFAULT_RENDERER_VIEWPORT);
        const { width, height } = viewport;

        releaseSlot = await acquireRenderSlot();
        const browser = await getSharedBrowser();

        context = await browser.newContext({
            viewport: { width, height },
            // Large viewports render at a reduced scale to bound pixel memory.
            deviceScaleFactor: clampDeviceScaleFactor(width, height),
            serviceWorkers: 'block',
        });
        await blockForeignRequests(context, rendererUrl);

        const page = await context.newPage();

        await page.goto(rendererUrl, { waitUntil: 'load', timeout: DEFAULT_RENDER_TIMEOUT_MS });
        await waitForRendererLoader(page, spec.loaderFunctionName);
        await loadRendererPayload(page, spec.loaderFunctionName, payload);
        await waitForRenderCompletion(
            page,
            `Unknown ${spec.payloadLabel} render error`
        );

        return pngResponse(await spec.capturePng(page));
    } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        if (error instanceof RendererBusyError) {
            return NextResponse.json(
                { error: message },
                { status: 503, headers: { 'Retry-After': '5' } },
            );
        }
        const status = error instanceof RendererInputError ? error.status : 500;
        if (status === 500) {
            console.error(`[${spec.label}] Error:`, error);
        }
        return NextResponse.json({ error: message }, { status });
    } finally {
        if (context) {
            await context.close().catch((error) => {
                console.error(`[${spec.label}] Browser context close failed:`, error);
            });
        }
        releaseSlot?.();
    }
}
