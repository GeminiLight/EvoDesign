// Test page for the in-browser pipeline renderer (PHASE3_PLAN.md WP28).
// packages/render-engine/tools/wp28/compare-renderers.ts opens this page with
// playwright and calls window.__pipelineRender for every stage fixture.
import { pipelineRenderer, type PngRenderOptions } from '../src/services/browser/pipelineRenderer.ts'

function toBase64(bytes: Uint8Array): string {
  let binary = ''
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  }
  return btoa(binary)
}

declare global {
  interface Window {
    __pipelineRender: (scene: Record<string, unknown>, options: PngRenderOptions) => Promise<{
      base64: string; width: number; height: number; warnings: string[]; renderer: string; ms: number
    }>
    __pipelineRendererReady: boolean
  }
}

window.__pipelineRender = async (scene, options) => {
  const started = performance.now()
  const result = await pipelineRenderer.render({ scene, options })
  return {
    base64: toBase64(result.png),
    width: result.width,
    height: result.height,
    warnings: result.warnings,
    renderer: result.renderer,
    ms: performance.now() - started,
  }
}
window.__pipelineRendererReady = true
