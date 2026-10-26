#!/usr/bin/env node

import { chromium } from "playwright";
import { spawn, execSync } from "node:child_process";
import { mkdirSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import http from "node:http";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");
const OUT_DIR = resolve(ROOT, "data/pages");
const DEV_URL = "http://localhost:5175";

const ROUTES = [
  { path: "/", filename: "landing.png" },
  { path: "/home", filename: "home.png" },
  { path: "/projects", filename: "projects.png" },
  { path: "/insights", filename: "insights.png" },
  { path: "/dna", filename: "dna.png" },
  { path: "/auth/email", filename: "auth-email.png" },
  { path: "/workspace", filename: "workspace.png" },
];

/** Check if dev server is reachable */
function isServerRunning() {
  return new Promise((resolve) => {
    const req = http.get(DEV_URL, () => resolve(true));
    req.on("error", () => resolve(false));
    req.setTimeout(2000, () => {
      req.destroy();
      resolve(false);
    });
  });
}

/** Start dev server and wait until it's reachable */
function startDevServer() {
  console.log("Dev server not detected. Starting it...");
  const proc = spawn("npm", ["run", "dev"], {
    cwd: ROOT,
    stdio: "pipe",
    detached: false,
  });

  proc.stdout.on("data", (d) => process.stdout.write(`[dev] ${d}`));
  proc.stderr.on("data", (d) => process.stderr.write(`[dev] ${d}`));

  return new Promise((resolvePromise, reject) => {
    const timeout = setTimeout(() => {
      reject(new Error("Dev server failed to start within 30s"));
    }, 30_000);

    const poll = setInterval(async () => {
      if (await isServerRunning()) {
        clearInterval(poll);
        clearTimeout(timeout);
        console.log("Dev server is ready.");
        resolvePromise(proc);
      }
    }, 1000);

    proc.on("exit", (code) => {
      clearInterval(poll);
      clearTimeout(timeout);
      reject(new Error(`Dev server exited with code ${code}`));
    });
  });
}

async function main() {
  mkdirSync(OUT_DIR, { recursive: true });

  let devProc = null;
  const running = await isServerRunning();

  if (!running) {
    devProc = await startDevServer();
  } else {
    console.log("Dev server already running.");
  }

  // Ensure dev server is killed on exit if we started it
  const cleanup = () => {
    if (devProc && !devProc.killed) {
      console.log("\nStopping dev server...");
      devProc.kill("SIGTERM");
    }
  };
  process.on("SIGINT", cleanup);
  process.on("SIGTERM", cleanup);
  process.on("exit", cleanup);

  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
      viewport: { width: 2560, height: 1440 },
      deviceScaleFactor: 2,
    });

    for (const { path, filename } of ROUTES) {
      const url = `${DEV_URL}${path}`;
      const outPath = resolve(OUT_DIR, filename);
      console.log(`Capturing ${url} -> ${filename}`);

      const page = await context.newPage();
      try {
        await page.goto(url, { waitUntil: "networkidle", timeout: 30_000 });

        // Wait for all fonts to finish loading
        await page.evaluate(() => document.fonts.ready);

        // Wait for any loading spinner to disappear
        await page
          .locator('[data-testid="loading-spinner"], .loading-spinner, .spinner')
          .first()
          .waitFor({ state: "hidden", timeout: 5_000 })
          .catch(() => {});

        // Stabilization delay for animations/transitions
        await page.waitForTimeout(1000);

        await page.screenshot({ path: outPath, fullPage: true });
        console.log(`  Saved ${filename}`);
      } catch (err) {
        console.error(`  Failed to capture ${filename}: ${err.message}`);
      } finally {
        await page.close();
      }
    }
  } finally {
    if (browser) await browser.close();
    cleanup();
  }

  console.log(`\nDone. Screenshots saved to ${OUT_DIR}`);
}

main().catch((err) => {
  console.error("Fatal:", err);
  process.exit(1);
});
