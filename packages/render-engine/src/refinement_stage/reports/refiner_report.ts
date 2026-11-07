// Ported from evodesign/agentic_system/refinement_stage/reports/refiner_report.py.
import { mkdirSync, writeFileSync } from '../../py/fs.ts';
import { copyF, withPyFloats } from '../../py/float_marks.ts';
import { pyJsonDumps } from '../../py/json.ts';
import { isAbsolute, join } from '../../py/path.ts';
import { pyStr } from '../../py/str.ts';
import { IterationLog, type EditApplyOutcome, type VerifierRefinerState } from '../state.ts';

type Report = Record<string, any>;

export function _utc_timestamp(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export function _outcome_to_dict(outcome: EditApplyOutcome): Report {
  return {
    applied: outcome.applied,
    error: outcome.error,
    edit: outcome.edit?.to_dict() ?? null,
    ...(outcome.raw !== null ? { raw: outcome.raw } : {}),
  };
}

export function _iteration_to_dict(log: IterationLog): Report {
  return {
    iteration: log.iteration,
    rolled_back: log.rolled_back,
    findings_before: log.findings_before,
    findings_after: log.findings_after,
    rerender_ok: log.rerender_ok,
    rerender_path: log.rerender_path,
    rerender_error: log.rerender_error,
    deterministic_edits: log.deterministic_edits.map(_outcome_to_dict),
    llm_edits: log.llm_edits.map(_outcome_to_dict),
    rerouted_arrows: log.rerouted_arrows,
    notes: log.notes,
  };
}

export function build_refiner_report(state: VerifierRefinerState, vlm_model_name = 'unknown'): Report {
  const report = {
    inputs: {
      manifest_path: state.manifest_path,
      image_path: state.image_path,
      structure_path: state.structure_path,
      verifier_report_path: state.verifier_report_path,
    },
    controls: {
      max_iterations: state.max_iterations,
      skip_rerender_between_iterations: state.skip_rerender_between_iterations,
    },
    iterations: state.iteration_logs.map(_iteration_to_dict),
    final: {
      converged: state.converged,
      termination_reason: state.termination_reason,
      iterations_run: state.current_iteration,
      best_findings_score: state.best_findings_score,
      refined_manifest_path: state.refined_manifest_path,
      refined_image_path: state.refined_image_path,
    },
    skipped_objective_checks: [...state.skipped_objective_checks],
    metadata: {
      timestamp: _utc_timestamp(),
      vlm_model: vlm_model_name,
      status: state.status,
      errors: [...state.errors],
      logs: state.logs.slice(-20),
    },
  };
  copyF(state, 'best_findings_score', report.final);
  return report;
}

export function _edit_row_md(outcome: EditApplyOutcome): string {
  const mark = outcome.applied ? '✓' : '✗';
  const { edit, error } = outcome;
  const detail = (edit ? edit.rationale || error || '' : error || 'rejected').replaceAll('|', '\\|');
  const text = [...detail].slice(0, 80).join('');
  return edit
    ? `| ${mark} | \`${edit.op}\` | \`${edit.id}\` | ${text} |`
    : `| ${mark} | \`(rejected)\` | \`-\` | ${text} |`;
}

export function _render_iteration_md(log: IterationLog): string[] {
  const counts = (values: Record<string, number>) =>
    Object.entries(values).map(([key, value]) => `${key}=${value}`).join(', ') || '(none)';
  const path = log.rerender_path ? `(${log.rerender_path})` : '';
  const lines = [
    `### Iteration ${log.iteration}`,
    `- Findings before: ${counts(log.findings_before)}`,
    `- Findings after:  ${counts(log.findings_after)}`,
    `- Re-render: ${log.rerender_ok ? 'ok' : 'skipped/failed'} ${path}`,
  ];
  if (log.rerender_error) lines.push(`- Re-render error: ${log.rerender_error}`);
  for (const [label, edits] of [['Deterministic', log.deterministic_edits], ['LLM', log.llm_edits]] as const) {
    if (edits.length) {
      lines.push('', `**${label} edits (${edits.length}):**`, '',
        '| applied | op | id | rationale |', '|---|---|---|---|', ...edits.map(_edit_row_md));
    }
  }
  if (log.rerouted_arrows.length) {
    const ids = log.rerouted_arrows.slice(0, 10).map(item => `\`${pyStr(item.arrow_id ?? null)}\``);
    lines.push('', `**Arrows re-routed onto moved endpoints (${log.rerouted_arrows.length}):** ${ids.join(', ')}`);
  }
  if (log.notes.length) lines.push('', '**Notes:**', ...log.notes.map(note => `- ${note}`));
  return [...lines, ''];
}

export function build_markdown_report(report: Report): string {
  const inputs = report.inputs ?? {};
  const final = report.final ?? {};
  const meta = report.metadata ?? {};
  const lines = [
    '# Refiner Report', '',
    `- Manifest: \`${pyStr(inputs.manifest_path ?? null)}\``,
    `- Image: \`${pyStr(inputs.image_path ?? null)}\``,
  ];
  if (inputs.structure_path) lines.push(`- Structure: \`${inputs.structure_path}\``);
  if (inputs.verifier_report_path) lines.push(`- Verifier report: \`${inputs.verifier_report_path}\``);
  const outcome = final.converged ? 'CONVERGED' : `STOPPED: ${final.termination_reason || 'unknown'}`;
  const iterations_run = final.iterations_run ?? 0;
  lines.push(
    `- Timestamp: ${pyStr(meta.timestamp ?? null)}`,
    `- VLM model: \`${pyStr(meta.vlm_model ?? null)}\``,
    `- Status: **${pyStr(meta.status ?? null)}**`, '',
    `## Outcome: ${outcome} (${iterations_run} iteration${iterations_run === 1 ? '' : 's'})`, '',
  );
  if (final.refined_manifest_path) lines.push(`- Refined manifest: \`${final.refined_manifest_path}\``);
  if (final.refined_image_path) lines.push(`- Refined image: \`${final.refined_image_path}\``);
  lines.push('');

  if (report.iterations?.length) {
    lines.push('## Iteration audit', '');
    for (const iteration of report.iterations) lines.push(..._render_iteration_md(IterationLog.model_validate(iteration)));
  }
  if (report.skipped_objective_checks?.length) {
    lines.push('## Objective checks NOT run', '', ...report.skipped_objective_checks.map((check: string) => `- ${check}`), '');
  }
  if (meta.errors?.length) lines.push('## Errors', '', ...meta.errors.map((error: string) => `- ${error}`), '');
  return lines.join('\n');
}

export function write_refiner_report(
  report: Report, output_dir: string, json_name = 'refiner_report.json', markdown_name: string | null = null,
): Record<string, string> {
  mkdirSync(output_dir, { recursive: true });
  const paths: Record<string, string> = { json: isAbsolute(json_name) ? json_name : join(output_dir, json_name) };
  writeFileSync(paths.json, pyJsonDumps(withPyFloats(report), { indent: 2, ensureAscii: false }), 'utf-8');
  if (markdown_name) {
    paths.markdown = isAbsolute(markdown_name) ? markdown_name : join(output_dir, markdown_name);
    writeFileSync(paths.markdown, build_markdown_report(report), 'utf-8');
  }
  return paths;
}
