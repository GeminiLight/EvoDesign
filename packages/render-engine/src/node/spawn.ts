// ``subprocess.run`` for Node (PHASE3_PLAN.md WP27; moved from
// render_engine/canvas_render.ts ``_spawn``).

import { spawn } from 'node:child_process';
import type { SpawnOptions, SpawnResult } from '../py/platform_types.ts';

export function spawnProcess(cmd: string[], options: SpawnOptions): Promise<SpawnResult> {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(cmd[0], cmd.slice(1), { cwd: options.cwd, stdio: ['pipe', 'pipe', 'pipe'] });
    const out: Buffer[] = [];
    const err: Buffer[] = [];
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGKILL');
    }, options.timeoutSeconds * 1000);
    child.stdout.on('data', (chunk: Buffer) => out.push(chunk));
    child.stderr.on('data', (chunk: Buffer) => err.push(chunk));
    child.on('error', (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolvePromise({ returncode: code ?? 1, stdout: new Uint8Array(Buffer.concat(out)), stderr: new Uint8Array(Buffer.concat(err)), timedOut });
    });
    child.stdin.on('error', () => {});
    child.stdin.end(options.input);
  });
}
