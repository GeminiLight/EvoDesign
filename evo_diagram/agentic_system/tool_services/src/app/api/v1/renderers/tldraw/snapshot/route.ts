import { type Page } from 'playwright';
import { renderSnapshotRequest } from '../../_shared/snapshotRenderer';

const DEFAULT_RENDERER_URL = process.env.TLDRAW_RENDER_URL || 'http://localhost:3000/renderers/tldraw';
const RENDERER_PATH = '/renderers/tldraw';

async function captureTldrawPng(page: Page): Promise<Buffer> {
    return page.screenshot({
        fullPage: false,
        omitBackground: true
    });
}

export async function POST(request: Request) {
    return renderSnapshotRequest(request, {
        label: 'TLDraw Render',
        payloadField: 'snapshot',
        payloadLabel: 'TLDraw snapshot',
        defaultRendererUrl: DEFAULT_RENDERER_URL,
        rendererPath: RENDERER_PATH,
        loaderFunctionName: 'loadTldrawSnapshot',
        capturePng: captureTldrawPng,
    });
}
