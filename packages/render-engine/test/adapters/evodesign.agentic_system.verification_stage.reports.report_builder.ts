import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { Adapter } from '../parity/functions.test.ts';
import type { Vector } from '../harness/fixtures.ts';
import { Finding } from '../../src/verification_stage/checks/finding.ts';
import type { VerifierStateLike } from '../../src/verification_stage/reports/report_builder.ts';

// The vectors carry pydantic models (VerifierState, Critique, Finding) as their
// field dicts. VerifierState is ported by WP20; until then the adapter rebuilds
// the parts report_builder reads: Finding instances (``to_dict``), a Critique
// with ``model_dump`` and VerifierState's computed properties (same formulas as
// verification_stage/state.py).

type Dict = Record<string, any>;

function critique(fields: Dict | null): Dict | null {
  if (fields === null || fields === undefined) return null;
  return { model_dump: () => structuredClone(fields) };
}

function verifierState(fields: Dict): VerifierStateLike {
  const state: Dict = {
    ...fields,
    objective_findings: (fields.objective_findings ?? []).map((f: Dict) => new Finding(f as never)),
    critique: critique(fields.critique),
  };
  const truthyList = (value: unknown): boolean => Array.isArray(value) && value.length > 0;
  Object.defineProperties(state, {
    has_errors: { get: () => truthyList(state.errors) || ['failed', 'reported_with_errors'].includes(state.status) },
    has_blocking_errors: { get: () => truthyList(state.blocking_errors) || ['failed', 'reported_with_errors'].includes(state.status) },
    blocking_finding_count: {
      get: () => {
        const summary = state.objective_summary ?? {};
        if (Object.keys(summary).length) return Math.trunc(Number(summary.critical || 0)) + Math.trunc(Number(summary.major || 0));
        return state.objective_findings.filter((f: Finding) => f.severity === 'critical' || f.severity === 'major').length;
      },
    },
    quality_passed: { get: () => !state.has_blocking_errors && !(state.blocking_finding_count > 0) },
  });
  return state as VerifierStateLike;
}

const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

/** A fresh timestamp cannot equal the recorded one; check the format instead. */
function sameTimestamp(actual: unknown, expected: unknown): unknown {
  return typeof actual === 'string' && TIMESTAMP.test(actual) ? expected : actual;
}

let outputRoot: string | null = null;
const redirected = new Map<number, { from: string; to: string }>();

export default {
  _utc_timestamp: { result: (actual, vector) => sameTimestamp(actual, vector.result) },
  build_report: {
    args: (bound) => [verifierState(bound[0] as Dict), ...bound.slice(1)],
    result: (actual, vector) => {
      const report = structuredClone(actual) as Dict;
      const expected = vector.result as Dict;
      report.metadata.timestamp = sameTimestamp(report.metadata.timestamp, expected.metadata.timestamp);
      return report;
    },
    checkMutation: false, // the state argument is rebuilt; the function does not mutate it
  },
  _findings_to_dicts: {
    args: (bound) => [(bound[0] as Dict[]).map((f) => new Finding(f as never))],
    checkMutation: false,
  },
  _critique_to_dict: {
    args: (bound) => [critique(bound[0] as Dict | null)],
    checkMutation: false,
  },
  // The recorded output directory was a temporary directory that no longer
  // exists: write into a fresh one and map the returned paths back. The JSON
  // file is checked against the report value, the Markdown file against
  // build_markdown_report (covered by its own vectors).
  write_report: {
    args: (bound, vector: Vector) => {
      outputRoot ??= mkdtempSync(join(tmpdir(), 'wp19-write-report-'));
      const target = join(outputRoot, String(vector.line));
      redirected.set(vector.line, { from: bound[1] as string, to: target });
      return [bound[0], target, ...bound.slice(2)];
    },
    result: (actual, vector) => {
      const { from, to } = redirected.get(vector.line)!;
      const paths = actual as Record<string, string>;
      const written = JSON.parse(readFileSync(paths.json, 'utf-8'));
      if (JSON.stringify(written) !== JSON.stringify(vector.args[0])) return { error: 'written JSON differs from the report' };
      return Object.fromEntries(Object.entries(paths).map(([key, value]) => [key, value.replace(to, from)]));
    },
    checkMutation: false,
  },
} satisfies Record<string, Adapter>;
