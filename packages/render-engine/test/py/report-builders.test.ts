import { expect, it } from 'vitest';
import { MemoryFS, withFS } from '../../src/py/fs.ts';
import { build_refiner_report, write_refiner_report } from '../../src/refinement_stage/reports/refiner_report.ts';
import { VerifierRefinerState } from '../../src/refinement_stage/state.ts';
import { build_report, write_report } from '../../src/verification_stage/reports/report_builder.ts';
import { VerifierState } from '../../src/verification_stage/state.ts';

it('writes the verifier report and redacts raw critique output', () => {
  const dimension = { score: 7.5, strengths: ['Clear'] };
  const state = new VerifierState({
    manifest_path: '/diagram.json',
    image_path: '/diagram.png',
    critique: {
      structure: dimension, styling: dimension, layout: dimension,
      overall_score: 7.5, raw_response: 'private debug response',
    },
    errors: ['image comparison unavailable'],
    nonblocking_errors: ['image comparison unavailable'],
  });
  const fs = new MemoryFS();
  const report = build_report(state, 'test-model');
  const paths = withFS(fs, () => write_report(report, '/output', undefined, 'verifier.md'));
  expect(JSON.parse(fs.readText(paths.json))).toEqual(report);
  expect(fs.readText(paths.json)).not.toContain('private debug response');
  expect(fs.readText(paths.markdown)).toContain('**Overall score: 7.5/10**');
  expect(fs.readText(paths.markdown)).toContain('## Warnings\n\n- image comparison unavailable');
});

it('writes rejected edit details and skipped checks to the refinement report', () => {
  const state = new VerifierRefinerState({
    manifest_path: '/diagram.json',
    image_path: '/diagram.png',
    current_iteration: 1,
    iteration_logs: [{
      iteration: 1,
      llm_edits: [{ applied: false, error: 'invalid | proposal', raw: { op: 'unknown' } }],
    }],
    skipped_objective_checks: ['crop check'],
  });
  const fs = new MemoryFS();
  const report = build_refiner_report(state);
  const paths = withFS(fs, () => write_refiner_report(report, '/output', undefined, 'refiner.md'));
  expect(JSON.parse(fs.readText(paths.json))).toEqual(report);
  expect(fs.readText(paths.markdown)).toContain('| ✗ | `(rejected)` | `-` | invalid \\| proposal |');
  expect(fs.readText(paths.markdown)).toContain('## Objective checks NOT run\n\n- crop check');
});
