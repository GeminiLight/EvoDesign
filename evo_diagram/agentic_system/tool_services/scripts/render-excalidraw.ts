#!/usr/bin/env node

import { mkdir, readFile } from 'fs/promises'
import { createWriteStream } from 'fs'
import path from 'path'
import process from 'process'
import { chromium, type Browser, type BrowserContext, type ConsoleMessage, type Page } from 'playwright'
import {
  DEFAULT_EXCALIDRAW_EXPORT_SCALE,
  DEFAULT_RENDER_MARGIN,
  DEFAULT_RENDER_TIMEOUT_MS,
  DEFAULT_RENDERER_VIEWPORT,
} from '../src/lib/renderDefaults'
import {
  validateExcalidrawExportScale,
  validateRendererUrl,
  validateRenderDimensions,
  validateRenderMargin,
  validateRenderTimeout,
} from '../src/lib/renderContract'

type Scene = Record<string, unknown> | Array<unknown>

interface CliOptions {
  scenePath: string | null
  outputPath: string
  url: string
  viewportWidth: number
  viewportHeight: number
  timeoutMs: number
  exportScale: number
  margin: number
}

interface ParsedCli {
  options: CliOptions
  helpRequested: boolean
}

const DEFAULT_URL = process.env.EXCALIDRAW_RENDER_URL ?? 'http://localhost:3000/renderers/excalidraw'
const RENDERER_PATH = '/renderers/excalidraw'

function printHelp(): void {
  const scriptName = path.basename(process.argv[1] ?? 'render-excalidraw.ts')
  console.log(
    `Usage: ${scriptName} [options]\n\n` +
      'Options:\n' +
      '  --scene <path>   Path to scene JSON file. Use "-" or omit to read from stdin.\n' +
      '  --output <path>  Path to PNG output file. Use "-" for stdout. Default: excalidraw.png\n' +
      `  --url <url>      Renderer page URL. Default: ${DEFAULT_URL}\n` +
      `  --width <number> Viewport width. Default: ${DEFAULT_RENDERER_VIEWPORT.width}\n` +
      `  --height <number> Viewport height. Default: ${DEFAULT_RENDERER_VIEWPORT.height}\n` +
      `  --scale <number> PNG export scale. Default: ${DEFAULT_EXCALIDRAW_EXPORT_SCALE}\n` +
      `  --margin <number> PNG export padding. Default: ${DEFAULT_RENDER_MARGIN}\n` +
      `  --timeout <number> Timeout in ms for navigation and waits. Default: ${DEFAULT_RENDER_TIMEOUT_MS}\n` +
      '  -h, --help       Show this help message\n'
  )
}

function parseArgs(argv: string[]): ParsedCli {
  const options: CliOptions = {
    scenePath: null,
    outputPath: 'excalidraw.png',
    url: DEFAULT_URL,
    viewportWidth: DEFAULT_RENDERER_VIEWPORT.width,
    viewportHeight: DEFAULT_RENDERER_VIEWPORT.height,
    timeoutMs: DEFAULT_RENDER_TIMEOUT_MS,
    exportScale: Number.parseFloat(
      process.env.EXCALIDRAW_EXPORT_SCALE ?? String(DEFAULT_EXCALIDRAW_EXPORT_SCALE),
    ),
    margin: DEFAULT_RENDER_MARGIN,
  }

  let helpRequested = false

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    switch (arg) {
      case '--scene': {
        const value = argv[++i]
        if (!value) throw new Error('Missing value for --scene')
        options.scenePath = value === '-' ? null : value
        break
      }
      case '--output': {
        const value = argv[++i]
        if (!value) throw new Error('Missing value for --output')
        options.outputPath = value
        break
      }
      case '--url': {
        const value = argv[++i]
        if (!value) throw new Error('Missing value for --url')
        options.url = value
        break
      }
      case '--width': {
        const value = argv[++i]
        if (!value) throw new Error('Missing value for --width')
        options.viewportWidth = Number.parseInt(value, 10)
        break
      }
      case '--height': {
        const value = argv[++i]
        if (!value) throw new Error('Missing value for --height')
        options.viewportHeight = Number.parseInt(value, 10)
        break
      }
      case '--scale': {
        const value = argv[++i]
        if (!value) throw new Error('Missing value for --scale')
        options.exportScale = Number.parseFloat(value)
        break
      }
      case '--margin': {
        const value = argv[++i]
        if (!value) throw new Error('Missing value for --margin')
        options.margin = Number.parseInt(value, 10)
        break
      }
      case '--timeout': {
        const value = argv[++i]
        if (!value) throw new Error('Missing value for --timeout')
        options.timeoutMs = Number.parseInt(value, 10)
        break
      }
      case '-h':
      case '--help':
        helpRequested = true
        break
      default:
        if (arg.startsWith('--')) {
          throw new Error(`Unknown option: ${arg}`)
        }
        if (!options.scenePath) {
          options.scenePath = arg === '-' ? null : arg
        } else {
          throw new Error(`Unexpected positional argument: ${arg}`)
        }
    }
  }

  return { options, helpRequested }
}

function validateCliOptions(options: CliOptions): void {
  options.url = validateRendererUrl(options.url, RENDERER_PATH)
  validateRenderDimensions(options.viewportWidth, options.viewportHeight)
  validateRenderTimeout(options.timeoutMs)
  validateRenderMargin(options.margin)
  validateExcalidrawExportScale(options.exportScale)
}

async function readScene(scenePath: string | null): Promise<Scene> {
  let raw: string

  if (scenePath === null) {
    raw = await new Promise<string>((resolve, reject) => {
      const chunks: Buffer[] = []
      process.stdin.on('data', (chunk) => chunks.push(Buffer.from(chunk)))
      process.stdin.on('error', reject)
      process.stdin.on('end', () => resolve(Buffer.concat(chunks).toString('utf-8')))
    })
  } else {
    raw = await readFile(scenePath, 'utf-8')
  }

  return JSON.parse(raw) as Scene
}

function normalizeScene(scene: Scene): Record<string, unknown> {
  if (Array.isArray(scene)) {
    return { elements: scene }
  }
  if (scene && typeof scene === 'object') {
    if (!('elements' in scene)) {
      throw new Error('Scene JSON must include an "elements" field.')
    }
    return scene as Record<string, unknown>
  }
  throw new Error('Scene JSON must be a list of elements or an object with "elements".')
}

function trackErrors(page: Page) {
  const consoleErrors: string[] = []
  const pageErrors: string[] = []
  const requestErrors: string[] = []

  function handleConsole(msg: ConsoleMessage) {
    if (msg.type() === 'error') consoleErrors.push(msg.text())
  }

  function handlePageError(error: Error) {
    pageErrors.push(error.message)
  }

  function handleCrash() {
    pageErrors.push('Page rendering process crashed.')
  }

  function handleRequestFailed(request: any) {
    const failure = request.failure?.()
    const reason = failure?.errorText ? ` (${failure.errorText})` : ''
    requestErrors.push(`${request.url()}${reason}`)
  }

  page.on('console', handleConsole)
  page.on('pageerror', handlePageError)
  page.on('crash', handleCrash)
  page.on('requestfailed', handleRequestFailed)

  return {
    getConsoleErrors: () => consoleErrors,
    getPageErrors: () => pageErrors,
    getRequestErrors: () => requestErrors,
    dispose: () => {
      page.off('console', handleConsole)
      page.off('pageerror', handlePageError)
      page.off('crash', handleCrash)
      page.off('requestfailed', handleRequestFailed)
    },
  }
}

function computeClip(
  bbox: { x: number; y: number; width: number; height: number },
  margin: number,
  maxWidth: number,
  maxHeight: number,
) {
  const x = Math.max(bbox.x - margin, 0)
  const y = Math.max(bbox.y - margin, 0)
  const width = Math.min(bbox.width + 2 * margin, maxWidth - x)
  const height = Math.min(bbox.height + 2 * margin, maxHeight - y)

  if (width <= 0 || height <= 0) {
    throw new Error('Calculated clip size is invalid; adjust viewport or margin.')
  }

  return { x, y, width, height }
}

async function preparePage(options: CliOptions): Promise<{ browser: Browser; context: BrowserContext; page: Page }> {
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  })
  const context = await browser.newContext({ deviceScaleFactor: 2 })
  const page = await context.newPage()

  try {
    page.setViewportSize({ width: options.viewportWidth, height: options.viewportHeight })
    await page.goto(options.url, { waitUntil: 'load', timeout: options.timeoutMs })
    return { browser, context, page }
  } catch (error) {
    await page.close().catch(() => {})
    await context.close().catch(() => {})
    await browser.close().catch(() => {})
    throw error
  }
}

async function findCanvasBox(page: Page) {
  const selectors = ['canvas.excalidraw__canvas', '.excalidraw__canvas canvas', 'canvas', '#root']
  for (const selector of selectors) {
    const el = await page.$(selector)
    if (!el) continue
    const bbox = await el.boundingBox()
    if (bbox) return bbox
  }
  return null
}

async function render(options: CliOptions, scene: Scene): Promise<Buffer> {
  const { browser, context, page } = await preparePage(options)
  const normalized = normalizeScene(scene)

  const errorTracker = trackErrors(page)

  try {
    if (!Number.isFinite(options.exportScale) || options.exportScale <= 0) {
      throw new Error(`Invalid export scale: ${options.exportScale}`)
    }
    if (!Number.isFinite(options.margin) || options.margin < 0) {
      throw new Error(`Invalid margin: ${options.margin}`)
    }

    await page.waitForFunction(() => typeof (window as any).loadExcalidrawScene === 'function', null, { timeout: options.timeoutMs })

    const apiReady = page.waitForFunction(
      () => Boolean((window as any).__excalidrawAPI),
      null,
      { timeout: options.timeoutMs },
    )
    const earlyError = page.waitForFunction(
      () => (window as any).__renderStatus === 'error',
      null,
      { timeout: options.timeoutMs },
    )

    let apiRace: 'ready' | 'error'
    try {
      apiRace = await Promise.race([apiReady.then(() => 'ready' as const), earlyError.then(() => 'error' as const)])
    } catch (error) {
      const consoleErrors = errorTracker.getConsoleErrors()
      const pageErrors = errorTracker.getPageErrors()
      const requestErrors = errorTracker.getRequestErrors()
      const combined = [...consoleErrors, ...pageErrors, ...requestErrors].join('; ')
      if (combined.length > 0) {
        throw new Error(`Client setup failed (resource errors): ${combined}`)
      }
      throw error
    }
    if (apiRace === 'error') {
      const errorMessage = await page.evaluate(() => (window as any).__renderError || 'Unknown render error')
      throw new Error(`Client setup failed: ${String(errorMessage).trim()}`)
    }

    await page.evaluate(({ exportScale, margin }) => {
      ;(window as any).__exportScale = exportScale
      ;(window as any).__exportMargin = margin
    }, { exportScale: options.exportScale, margin: options.margin })

    await page.evaluate((sceneData) => {
      const win = window as unknown as { loadExcalidrawScene?: (data: unknown) => void }
      if (typeof win.loadExcalidrawScene === 'function') {
        win.loadExcalidrawScene(sceneData)
      }
    }, normalized)

    const timeoutMs = options.timeoutMs ?? 15000
    let timeoutHandle: NodeJS.Timeout | null = null

    const raceWinner = await Promise.race([
      page.waitForFunction(
        () => (window as any).__renderStatus === 'ready',
        null,
        { timeout: timeoutMs },
      ).then(() => 'success'),
      page.waitForFunction(
        () => (window as any).__renderStatus === 'error',
        null,
        { timeout: timeoutMs },
      ).then(() => 'error'),
      new Promise((resolve) => {
        timeoutHandle = setTimeout(() => resolve('timeout'), timeoutMs)
        timeoutHandle.unref()
      }),
    ])

    if (timeoutHandle) clearTimeout(timeoutHandle)

    if (raceWinner === 'timeout') {
      const consoleErrors = errorTracker.getConsoleErrors()
      const pageErrors = errorTracker.getPageErrors()
      if (consoleErrors.length > 0 || pageErrors.length > 0) {
        const combined = [...consoleErrors, ...pageErrors].join('; ')
        throw new Error(`Render failed (page errors): ${combined}`)
      }
      throw new Error('Render timeout: after injecting data the page did not render or report an error.')
    }

    if (raceWinner === 'error') {
      const errorMessage = await page.evaluate(() => (window as any).__renderError || 'Unknown render error')
      throw new Error(`Client render failed: ${String(errorMessage).trim()}`)
    }

    if (raceWinner !== 'success') {
      throw raceWinner as unknown as Error
    }

    // Read the exported image data (base64 data URL from exportToBlob)
    const base64Data = await page.evaluate(() => (window as any).__exportedImageData)
    if (!base64Data || typeof base64Data !== 'string') {
      throw new Error('No exported image data found after successful render.')
    }

    // Strip data URL prefix: "data:image/png;base64,..."
    const base64Content = base64Data.replace(/^data:[^;]+;base64,/, '')
    const buffer = Buffer.from(base64Content, 'base64')

    const consoleErrors = errorTracker.getConsoleErrors()
    if (consoleErrors.length > 0) {
      console.warn('[render-excalidraw] Browser console emitted errors:')
      for (const entry of consoleErrors) console.warn(`  ${entry}`)
    }

    return buffer
  } finally {
    errorTracker.dispose()
    await page.close().catch(() => {})
    await context.close().catch(() => {})
    await browser.close().catch(() => {})
  }
}

async function writeOutput(outputPath: string, data: Buffer): Promise<void> {
  if (outputPath === '-') {
    await new Promise<void>((resolve, reject) => {
      const stdout = createWriteStream('', { fd: process.stdout.fd })
      stdout.on('error', reject)
      stdout.on('finish', resolve)
      stdout.end(data)
    })
    return
  }

  const parent = path.dirname(outputPath)
  if (parent && parent !== '.') {
    await mkdir(parent, { recursive: true })
  }

  await new Promise<void>((resolve, reject) => {
    const stream = createWriteStream(outputPath)
    stream.on('error', reject)
    stream.on('finish', resolve)
    stream.end(data)
  })
}

async function main(): Promise<number> {
  try {
    const { options, helpRequested } = parseArgs(process.argv.slice(2))

    if (helpRequested) {
      printHelp()
      return 0
    }

    validateCliOptions(options)
    const scene = await readScene(options.scenePath)
    const buffer = await render(options, scene)
    await writeOutput(options.outputPath, buffer)

    return 0
  } catch (error) {
    if (error instanceof Error) {
      console.error(`[render-excalidraw] ${error.message}`)
    } else {
      console.error('[render-excalidraw] Unexpected error.', error)
    }
    return 1
  }
}

main()
  .then((code) => {
    if (code !== 0) process.exit(code)
  })
  .catch((error) => {
    console.error('[render-excalidraw] Failed to execute CLI.', error)
    process.exit(1)
  })
