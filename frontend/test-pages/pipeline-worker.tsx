import { createRoot } from 'react-dom/client';
import { Excalidraw, restoreElements } from '@excalidraw/excalidraw';
import type { ExcalidrawImperativeAPI } from '@excalidraw/excalidraw/types';
import '@excalidraw/excalidraw/index.css';
import { runPipelineWorker } from '../src/services/browser/pipelineClient';
import { diagramResponseFromStream } from '../src/services/apiDiagramService';
import type { StreamResultEvent } from '../src/types/api';
import type { BrowserModelConfig } from '../src/services/browser/modelConfig';
import './pipeline-renderer';

let api: ExcalidrawImperativeAPI;
createRoot(document.getElementById('canvas')!).render(<Excalidraw excalidrawAPI={value => { api = value; }} />);
Object.assign(window, {
  __workerReady: true,
  __restoreExpected: (elements: Parameters<typeof restoreElements>[0]) => restoreElements(elements, null),
  __runWorker: async (request: Record<string, unknown>, config: BrowserModelConfig) => {
    const events: { event: string; data: Record<string, unknown> }[] = [];
    Object.assign(window, { __workerEvents: events });
    const result = await runPipelineWorker(request, config, (event, data) => events.push({ event, data }));
    const response = diagramResponseFromStream(result as unknown as StreamResultEvent,
      { prompt: String(request.context), diagramType: String(request.diagram_type ?? 'automated') }, 'excalidraw');
    const schema = JSON.parse(response.excalidrawPayload) as { elements: Parameters<typeof restoreElements>[0] };
    api.updateScene({ elements: restoreElements(schema.elements, null) });
    await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    return { result, events, canvasElements: api.getSceneElements() };
  },
  __cancelWorker: async (request: Record<string, unknown>, config: BrowserModelConfig) => {
    const controller = new AbortController();
    const pending = runPipelineWorker(request, config, () => controller.abort(), controller.signal);
    try { await pending; return false; } catch (error) { return error instanceof DOMException && error.name === 'AbortError'; }
  },
});
