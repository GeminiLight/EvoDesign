"""Opt-in real-model smoke matrix. Uses configured credentials; writes only to --output.

Run from the repository with PYTHONPATH=backend:. and the project's virtualenv.
No real-model requests are made by ordinary test discovery.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import time
import traceback


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


async def main(args):
    repo = Path(__file__).resolve().parents[2]
    root = Path(args.source_root or repo).resolve()
    output = Path(args.output).resolve()
    memory_template = Path(args.memory_template).resolve() if args.memory_template else None
    if not (root / 'evo_diagram/agentic_system/tool_services/node_modules/playwright').exists():
        raise RuntimeError('Install renderer dependencies (or link node_modules into the source snapshot) before real-model testing.')
    sys.path[:0] = [str(root / 'backend'), str(root)]
    os.chdir(root)
    from dotenv import load_dotenv
    load_dotenv(repo / '.env')
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')
    os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
    os.environ.setdefault('EXCALIDRAW_RENDER_URL', 'http://127.0.0.1:3000/renderers/excalidraw')
    from app.services.workflow_engine_adapter import WorkflowEngineAdapter, WorkflowRunRequest
    from app.services.llm_client import create_backend_llm
    from app.services.design_learning_jobs import read_status, wait_for_learning
    from langchain_core.callbacks import BaseCallbackHandler

    class ModelTiming(BaseCallbackHandler):
        """Record latency and usage only, never prompts, credentials or images."""

        def __init__(self, path):
            self.path, self.pending, self.rows = path, {}, []
            self.stage = 'memory'

        def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
            self.pending[run_id] = (time.monotonic(), self.stage, sum(
                len(msg.content) for batch in messages for msg in batch
                if isinstance(msg.content, str)))

        def on_llm_end(self, response, *, run_id, **kwargs):
            started, stage, chars = self.pending.pop(run_id, (time.monotonic(), self.stage, 0))
            message = response.generations[0][0].message
            self.rows.append({'stage': stage, 'status': 'completed',
                              'duration_s': round(time.monotonic() - started, 3),
                              'input_text_chars': chars,
                              'output_text_chars': len(message.content),
                              'usage': getattr(message, 'usage_metadata', None),
                              'provider_usage': (response.llm_output or {}).get('token_usage')})
            write(self.path, self.rows)

        def on_llm_error(self, error, *, run_id, **kwargs):
            started, stage, chars = self.pending.pop(run_id, (time.monotonic(), self.stage, 0))
            self.rows.append({'stage': stage, 'status': 'failed',
                              'duration_s': round(time.monotonic() - started, 3),
                              'input_text_chars': chars, 'error_type': type(error).__name__})
            write(self.path, self.rows)
    # Avoid measuring Python's first-time module import race as a model failure.
    from evo_diagram.agentic_system.render_engine.shared import render_audit  # noqa: F401
    cases = json.loads((repo / 'scripts/research/diagram_matrix_cases.json').read_text())
    output.mkdir(parents=True, exist_ok=True)
    limit = asyncio.Semaphore(args.concurrency)
    summaries = []

    async def run(case, icons):
        name = case['id'] + ('_icons' if icons else '_plain')
        if args.only and name not in args.only.split(','):
            return
        async with limit:
            out = output / name
            out.mkdir(exist_ok=False)
            memory = out / 'memory'
            if memory_template:
                shutil.copytree(memory_template, memory, ignore=shutil.ignore_patterns('.learning'))
            requirements = (
                'Keep the exact requested labels, participants, relationships and order. '
                'Use a white background, readable dark labels, and restrained blue/cyan/violet fills. '
                'Do not add a legend or decorative title. '
            )
            if icons:
                requirements += ('Enable small monochrome icons, matching the host stroke color, only on these nodes or participant headers: '
                                 + ', '.join(case['icon_labels']) + '. No icons on other nodes, messages or decision diamonds. Keep every text label.')
            else:
                requirements += 'Disable all icons; use text and geometric shapes only.'
            kwargs = dict(context=case['context'], requirements=requirements,
                          locked_nodes=[], current_schema=None, canvas_library='excalidraw', user_tier='free',
                          request_id=f'{args.variant}_{name}', enable_refiner=True, refiner_max_iterations=2,
                          enable_design_memory=True, design_memory_path=str(memory),
                          design_memory_seed_path=str(root / 'evo_diagram/design_memory/seeds/web_strategies.json'),
                          learn_design_memory=True, retain_artifacts=True, use_icons=icons,
                          diagram_type=case['diagram_type'])
            write(out / 'request.json', kwargs)
            started = time.monotonic()
            events = []
            summary = {'case': name, 'variant': args.variant, 'concurrency': args.concurrency}
            print('START', name, flush=True)
            try:
                model = create_backend_llm()
                timing = ModelTiming(out / 'model-timings.json')
                model.callbacks = [timing]
                async for chunk in WorkflowEngineAdapter(str(out)).stream_without_render(
                        model=model, request=WorkflowRunRequest(**kwargs)):
                    lines = chunk.splitlines()
                    event = next((line[6:].strip() for line in lines if line.startswith('event:')), '')
                    data = json.loads('\n'.join(line[5:].strip() for line in lines if line.startswith('data:')))
                    if event == 'stage_start':
                        timing.stage = data['stage']
                    elapsed = round(time.monotonic() - started, 3)
                    events.append({'event': event, 'elapsed_s': elapsed, 'data': data})
                    write(out / 'events.json', events)
                    print(name, event, data.get('stage', ''), elapsed, flush=True)
                    if event == 'result':
                        write(out / 'result.json', data)
                        summary['delivery_s'] = elapsed
                        summary['generation'] = data.get('metrics_scores', {}).get('generation', {})
                    elif event == 'error':
                        summary['error'] = data
            except Exception as exc:
                summary['exception'] = type(exc).__name__
                (out / 'exception.txt').write_text(traceback.format_exc())
            summary['stream_s'] = round(time.monotonic() - started, 3)
            write(out / 'summary.json', summary)
            summaries.append(summary)
            print('DELIVERED', name, json.dumps(summary), flush=True)

    # Paired settings share only frozen initial knowledge, never online updates.
    await asyncio.gather(*(run(case, icons) for case in cases for icons in (False, True)))
    await wait_for_learning()
    for summary in summaries:
        out = output / summary['case']
        status = read_status(out / 'memory', f"{args.variant}_{summary['case']}")
        summary['learning_final'] = status or summary.get('generation', {}).get('learning')
        write(out / 'summary.json', summary)
    write(output / 'summary.json', summaries)
    print('MATRIX_COMPLETE', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--source-root')
    parser.add_argument('--memory-template')
    parser.add_argument('--variant', default='matrix')
    parser.add_argument('--only', help='Comma-separated case IDs with _plain or _icons suffix')
    parser.add_argument('--concurrency', type=int, choices=(1, 2), default=2)
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main(parser.parse_args()))
