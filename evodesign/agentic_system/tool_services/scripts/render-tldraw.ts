#!/usr/bin/env node

import { mkdir, readFile } from 'fs/promises'
import { createWriteStream } from 'fs'
import path from 'path'
import process from 'process'
import { chromium, type Browser, type BrowserContext, type Page } from 'playwright'
import type { TLEditorSnapshot } from 'tldraw'
import {
  DEFAULT_RENDER_MARGIN,
  DEFAULT_RENDER_TIMEOUT_MS,
  DEFAULT_RENDERER_VIEWPORT,
} from '../src/lib/renderDefaults'
import {
  validateRendererUrl,
  validateRenderDimensions,
  validateRenderMargin,
  validateRenderTimeout,
} from '../src/lib/renderContract'

type Snapshot = TLEditorSnapshot

interface CliOptions {
  snapshotPath: string | null
  outputPath: string
  url: string
  viewportWidth: number
  viewportHeight: number
  timeoutMs: number
  margin: number
}

interface ParsedCli {
  options: CliOptions
  helpRequested: boolean
}

const DEFAULT_URL = process.env.TLDRAW_RENDER_URL ?? 'http://localhost:3000/renderers/tldraw'
const RENDERER_PATH = '/renderers/tldraw'

function printHelp(): void {
  const scriptName = path.basename(process.argv[1] ?? 'render-tldraw.ts')
  console.log(`Usage: ${scriptName} [options]\n\n` +
    'Options:\n' +
    '  --snapshot <path>   Path to snapshot JSON file. Use "-" or omit to read from stdin.\n' +
    '  --output <path>     Path to PNG output file. Use "-" for stdout. Default: snapshot.png\n' +
    `  --url <url>         Renderer page URL. Default: ${DEFAULT_URL}\n` +
    `  --width <number>    Viewport width. Default: ${DEFAULT_RENDERER_VIEWPORT.width}\n` +
    `  --height <number>   Viewport height. Default: ${DEFAULT_RENDERER_VIEWPORT.height}\n` +
    `  --timeout <number>  Timeout in ms for navigation and waits. Default: ${DEFAULT_RENDER_TIMEOUT_MS}\n` +
    `  --margin <number>   Padding around the canvas when capturing. Default: ${DEFAULT_RENDER_MARGIN}\n` +
    '  -h, --help          Show this help message\n')
}

function parseArgs(argv: string[]): ParsedCli {
  const options: CliOptions = {
    snapshotPath: null,
    outputPath: 'snapshot.png',
    url: DEFAULT_URL,
    viewportWidth: DEFAULT_RENDERER_VIEWPORT.width,
    viewportHeight: DEFAULT_RENDERER_VIEWPORT.height,
    timeoutMs: DEFAULT_RENDER_TIMEOUT_MS,
    margin: DEFAULT_RENDER_MARGIN,
  }

  let helpRequested = false

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    switch (arg) {
      case '--snapshot': {
        const value = argv[++i]
        if (!value) throw new Error('Missing value for --snapshot')
        options.snapshotPath = value === '-' ? null : value
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
      case '--timeout': {
        const value = argv[++i]
        if (!value) throw new Error('Missing value for --timeout')
        options.timeoutMs = Number.parseInt(value, 10)
        break
      }
      case '--margin': {
        const value = argv[++i]
        if (!value) throw new Error('Missing value for --margin')
        options.margin = Number.parseInt(value, 10)
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
        if (!options.snapshotPath) {
          options.snapshotPath = arg === '-' ? null : arg
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
}

async function readSnapshot(snapshotPath: string | null): Promise<Snapshot> {
  let raw: string

  if (snapshotPath === null) {
    raw = await new Promise<string>((resolve, reject) => {
      const chunks: Buffer[] = []
      process.stdin.on('data', (chunk) => chunks.push(Buffer.from(chunk)))
      process.stdin.on('error', reject)
      process.stdin.on('end', () => resolve(Buffer.concat(chunks).toString('utf-8')))
    })
  } else {
    raw = await readFile(snapshotPath, 'utf-8')
  }

  const parsed = JSON.parse(raw)
  if (!parsed || typeof parsed !== 'object' || !('document' in parsed)) {
    throw new Error('Snapshot JSON must be an object containing a "document" property.')
  }

  return parsed as Snapshot
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

async function preparePage(
  options: CliOptions
): Promise<{ browser: Browser; context: BrowserContext; page: Page }> {
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
  })
  const context = await browser.newContext({ deviceScaleFactor: 2 })
  const page = await context.newPage()

  try {
    page.setViewportSize({ width: options.viewportWidth, height: options.viewportHeight })
    console.error(`Status: Navigating to ${options.url}`)
    await page.goto(options.url, { waitUntil: 'load', timeout: options.timeoutMs })

    return { browser, context, page }
  } catch (error) {
    await page.close().catch(() => {})
    await context.close().catch(() => {})
    await browser.close().catch(() => {})
    throw error
  }
}

async function render(options: CliOptions, snapshot: Snapshot): Promise<Buffer> {
  const { browser, context, page } = await preparePage(options)

  // Set up console error collection
  const consoleErrors: string[] = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      console.log(`[Browser Console Error]: ${msg.text()}`)
      consoleErrors.push(msg.text())
    }
  })

  // Handle page errors
  const pageErrorPromise = new Promise<never>((_, reject) => {
    page.on('pageerror', (err) => reject(err))
    page.on('crash', () => reject(new Error('Page rendering process crashed.')))
  })

  try {
    await Promise.race([
      page.waitForFunction(() => typeof (window as any).loadTldrawSnapshot === 'function', null, { timeout: options.timeoutMs }),
      pageErrorPromise,
    ])

    await page.evaluate(
      (snapshotData: any) => {
        return (window as any).loadTldrawSnapshot(snapshotData)
      },
      snapshot as any
    )

    const status = await Promise.race([
      page.waitForFunction(() => (window as any).__renderStatus === 'ready', null, { timeout: options.timeoutMs }).then(() => 'ready'),
      page.waitForFunction(() => (window as any).__renderStatus === 'error', null, { timeout: options.timeoutMs }).then(() => 'error'),
      pageErrorPromise,
    ])
    if (status === 'error') {
      const message = await page.evaluate(() => (window as any).__renderError || 'Unknown TLDraw render error')
      throw new Error(`Client render failed: ${String(message).trim()}`)
    }

    // Wait for canvas to be ready (common to both)
    const successSelector = '.tl-canvas'
    await page.waitForSelector(successSelector, { state: 'visible', timeout: options.timeoutMs })

    // Allow a brief moment for fonts/styles to settle
    await page.waitForTimeout(500)

    const canvas = await page.$(successSelector)
    if (!canvas) throw new Error('Canvas element not found after successful render.')

    const bbox = await canvas.boundingBox()
    if (!bbox) throw new Error('Failed to obtain canvas bounding box.')

    const clip = computeClip(bbox, options.margin, options.viewportWidth, options.viewportHeight)
    const buffer = await page.screenshot({ type: 'png', clip })

    if (consoleErrors.length > 0) {
      console.warn('[render-snapshot] Browser console emitted errors:')
      for (const entry of consoleErrors) console.warn(`  ${entry}`)
    }

    return buffer
  } finally {
    // cleanup listeners and browser
    page.removeAllListeners('console')
    page.removeAllListeners('pageerror')
    page.removeAllListeners('crash')
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
    const snapshot = await readSnapshot(options.snapshotPath)
    const buffer = await render(options, snapshot)
    await writeOutput(options.outputPath, buffer)

    return 0
  } catch (error) {
    if (error instanceof Error) {
      console.error(`[render-snapshot] ${error.message}`)
    } else {
      console.error('[render-snapshot] Unexpected error.', error)
    }
    return 1
  }
}

main().then((code) => {
  if (code !== 0) process.exit(code)
}).catch((error) => {
  console.error('[render-snapshot] Failed to execute CLI.', error)
  process.exit(1)
})
