import { type Page } from 'playwright';
import { renderSnapshotRequest } from '../../_shared/snapshotRenderer';

const DEFAULT_RENDERER_URL = process.env.EXCALIDRAW_RENDER_URL || 'http://localhost:3000/renderers/excalidraw';
const RENDERER_PATH = '/renderers/excalidraw';

function decodePngDataUrl(dataUrl: unknown): Buffer {
    if (typeof dataUrl !== 'string') {
        throw new Error('Excalidraw renderer did not export image data.');
    }
    const match = dataUrl.match(/^data:image\/png;base64,(.+)$/);
    if (!match) {
        throw new Error('Excalidraw renderer returned a non-PNG data URL.');
    }
    return Buffer.from(match[1], 'base64');
}

async function captureExcalidrawPng(page: Page): Promise<Buffer> {
    const dataUrl = await page.evaluate(
        () => (window as any).__exportedImageData
    );
    return decodePngDataUrl(dataUrl);
}

export async function POST(request: Request) {
    return renderSnapshotRequest(request, {
        label: 'Excalidraw Render',
        payloadField: 'scene',
        payloadLabel: 'Excalidraw scene',
        defaultRendererUrl: DEFAULT_RENDERER_URL,
        rendererPath: RENDERER_PATH,
        loaderFunctionName: 'loadExcalidrawScene',
        capturePng: captureExcalidrawPng,
    });
}
