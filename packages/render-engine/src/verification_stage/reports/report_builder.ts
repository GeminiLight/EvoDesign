// Ported from evodesign/agentic_system/verification_stage/reports/report_builder.py.
import { mkdirSync, writeFileSync } from '../../py/fs.ts';
import { withPyFloats } from '../../py/float_marks.ts';
import { pyJsonDumps } from '../../py/json.ts';
import { isAbsolute, join } from '../../py/path.ts';
import { pyFormatFixed, pyStr } from '../../py/str.ts';
import { isDict } from '../../py/truthy.ts';
import { summarize_findings, type Finding } from '../checks/finding.ts';
import { DimensionCritique, type Critique, type VerifierState } from '../state.ts';

type Report = Record<string, any>;

export type VerifierStateLike = Pick<VerifierState,
  'manifest_path' | 'image_path' | 'canvas_library' | 'structure_path' | 'layout_path'
  | 'objective_findings' | 'critique' | 'design_constraints' | 'skip_critic' | 'status'
  | 'has_errors' | 'has_blocking_errors' | 'blocking_finding_count' | 'quality_passed'
  | 'errors' | 'blocking_errors' | 'nonblocking_errors'>;

export function _utc_timestamp(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export function _findings_to_dicts(findings: Finding[]): Report[] {
  return findings.map(finding => finding.to_dict());
}

export function _critique_to_dict(critique: Critique | null): Report | null {
  if (critique === null) return null;
  const payload = critique.model_dump();
  delete payload.raw_response;
  return payload;
}

export function _effective_blocking_errors(state: VerifierStateLike): string[] {
  if (state.blocking_errors.length) return [...state.blocking_errors];
  if (state.status !== 'failed' && state.status !== 'reported_with_errors') return [];
  return state.errors.filter(error => !state.nonblocking_errors.includes(error));
}

export function build_report(state: VerifierStateLike, vlm_model_name: string | null = null): Report {
  return {
    manifest_path: state.manifest_path,
    image_path: state.image_path,
    canvas_library: state.canvas_library,
    structure_path: state.structure_path,
    layout_path: state.layout_path,
    objective: {
      summary: summarize_findings(state.objective_findings),
      findings: _findings_to_dicts(state.objective_findings),
    },
    subjective: _critique_to_dict(state.critique),
    design_constraints: state.design_constraints,
    metadata: {
      timestamp: _utc_timestamp(),
      vlm_model: vlm_model_name,
      skip_critic: state.skip_critic,
      canvas_library: state.canvas_library,
      status: state.status,
      had_errors: state.has_errors,
      had_blocking_errors: state.has_blocking_errors,
      had_blocking_findings: state.blocking_finding_count > 0,
      quality_passed: state.quality_passed,
      errors: [...state.errors],
      blocking_errors: _effective_blocking_errors(state),
      nonblocking_errors: [...state.nonblocking_errors],
    },
  };
}

export function _render_dimension_md(name: string, dim: DimensionCritique | null): string[] {
  if (dim === null) return [`#### ${name}`, '_(unavailable)_', ''];
  const lines = [`#### ${name} — score **${pyFormatFixed(dim.score, 1)}/10**`];
  for (const [label, values] of [
    ['Strengths', dim.strengths], ['Weaknesses', dim.weaknesses], ['Suggestions', dim.suggestions],
  ] as const) {
    if (values.length) lines.push(`- **${label}:**`, ...values.map(value => `  - ${value}`));
  }
  return [...lines, ''];
}

export function build_markdown_report(report: Report): string {
  const objective = report.objective ?? {};
  const subjective = report.subjective ?? null;
  const meta = report.metadata ?? {};
  const lines = [
    '# Verifier Report', '',
    `- Manifest: \`${pyStr(report.manifest_path ?? null)}\``,
    `- Image: \`${pyStr(report.image_path ?? null)}\``,
  ];
  for (const [label, value] of [
    ['Canvas', report.canvas_library], ['Structure', report.structure_path], ['Layout', report.layout_path],
  ]) {
    if (value) lines.push(`- ${label}: \`${value}\``);
  }
  if (meta.timestamp) lines.push(`- Timestamp: ${meta.timestamp}`);
  if (meta.vlm_model) lines.push(`- VLM model: \`${meta.vlm_model}\``);

  const counts = ['critical', 'major', 'minor', 'info', 'total']
    .map(key => `${key}=${objective.summary?.[key] ?? 0}`).join(', ');
  lines.push('', '## Objective Findings', '', `Counts: ${counts}`, '');
  if (objective.findings?.length) {
    lines.push('| Severity | Category | Element | Message |', '|---|---|---|---|');
    for (const finding of objective.findings) {
      const message = (finding.message || '').replaceAll('|', '\\|');
      lines.push(`| ${finding.severity ?? '?'} | ${finding.category ?? '?'} | \`${finding.element_id || ''}\` | ${message} |`);
    }
  } else {
    lines.push('_No objective findings._');
  }

  if (subjective === null) {
    lines.push('', '## Subjective Critique', '', '_Skipped or unavailable._', '');
  } else {
    lines.push('', '## Subjective Critique (VLM)', '');
    if (subjective.overall_score != null) {
      lines.push(`**Overall score: ${pyFormatFixed(Number(subjective.overall_score), 1)}/10**`);
    }
    if (subjective.summary) lines.push(`\n> ${subjective.summary}`);
    lines.push('');
    for (const key of ['structure', 'styling', 'layout']) {
      const payload = subjective[key];
      lines.push(..._render_dimension_md(
        key[0].toUpperCase() + key.slice(1), isDict(payload) ? new DimensionCritique(payload) : null,
      ));
    }
  }

  const blocking = meta.blocking_errors ?? [];
  const nonblocking = meta.nonblocking_errors ?? [];
  const other = (meta.errors ?? []).filter((error: string) => !blocking.includes(error) && !nonblocking.includes(error));
  if (blocking.length || other.length) {
    lines.push('## Errors', '', ...[...blocking, ...other].map(error => `- ${error}`), '');
  }
  if (nonblocking.length) lines.push('## Warnings', '', ...nonblocking.map((warning: string) => `- ${warning}`), '');
  return lines.join('\n');
}

export function write_report(
  report: Report, output_dir: string, json_name = 'verifier_report.json', markdown_name: string | null = null,
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
