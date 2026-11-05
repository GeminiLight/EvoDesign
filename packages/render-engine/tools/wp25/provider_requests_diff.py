# WP25 acceptance-review script (see migration/PHASE2_REPORT.md §3).
# Usage: python provider_requests_diff.py <echo_py.jsonl> <echo_ts.jsonl>
import json, sys
py = [json.loads(l) for l in open(sys.argv[1])]; ts = [json.loads(l) for l in open(sys.argv[2])]
for a, b in zip(py, ts):
    diffs = [f"body.{k}: py={json.dumps(a['body'].get(k), ensure_ascii=False)[:120]} ts={json.dumps(b['body'].get(k), ensure_ascii=False)[:120]}"
             for k in sorted(set(a['body']) | set(b['body'])) if a['body'].get(k) != b['body'].get(k)]
    diffs += [f"header {k}: py={a['headers'].get(k)} ts={b['headers'].get(k)}" for k in sorted(set(a['headers']) | set(b['headers'])) if a['headers'].get(k) != b['headers'].get(k)]
    print(a['tag'], 'SAME' if not diffs else ''); [print('   ', d) for d in diffs]
