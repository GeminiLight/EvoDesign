import { NextResponse } from 'next/server';
import { chromium, type Browser, type Page } from 'playwright';
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
} from '@/lib/renderDefaults';

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
    let browser: Browser | null = null;
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

        browser = await chromium.launch({
            args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        });

        const context = await browser.newContext({
            viewport: { width, height },
            deviceScaleFactor: 2
        });

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
        const status = error instanceof RendererInputError ? 400 : 500;
        if (status === 500) {
            console.error(`[${spec.label}] Error:`, error);
        }
        const message = error instanceof Error ? error.message : String(error);
        return NextResponse.json({ error: message }, { status });
    } finally {
        if (browser) {
            await browser.close().catch((error) => {
                console.error(`[${spec.label}] Browser close failed:`, error);
            });
        }
    }
}
