#!/usr/bin/env python3
"""Collect completed results and generate comparison graphs."""
import csv
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
manifest = json.loads((BASE / 'manifest.json').read_text())
rows = []
for item in manifest:
    row = dict(item)
    for name in ('binary_search', 'z3_makespan'):
        path = BASE / item['iteration'] / 'output' / f"{item['case']}_{name}.json"
        row[name + '_output'] = str(path.relative_to(BASE))
        if path.exists():
            result = json.loads(path.read_text())
            row[name + '_status'] = 'sat' if result.get('sat') else 'unsat'
            row[name + '_makespan'] = result.get('optimal_makespan')
            row[name + '_compute_seconds'] = result.get('scheduler_compute_time', result.get('schedule_calculation_seconds'))
            row[name + '_smt_stats'] = result.get('smt_stats', 'see per-iteration log')
        else:
            row[name + '_status'] = 'pending_or_missing'
    rows.append(row)

fields = sorted({key for row in rows for key in row})
with (BASE / 'results.csv').open('w', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()})
print(f"Wrote {BASE / 'results.csv'}")
try:
    import matplotlib.pyplot as plt
except ImportError:
    print('matplotlib unavailable; results.csv is ready')
    raise SystemExit(0)

graphs = BASE / 'graphs'
graphs.mkdir(exist_ok=True)
def comparison(y1, y2, label, filename):
    fig, ax = plt.subplots(figsize=(10, 6))
    for key, legend, marker in ((y1, 'Binary search', 'o'), (y2, 'Z3 min makespan', 's')):
        x = [r['task_count'] for r in rows]
        values = [r.get(key) for r in rows]
        ax.plot(x, [float(v) if v is not None else float('nan') for v in values], marker=marker, label=legend)
    ax.set_xlabel('Tasks'); ax.set_ylabel(label); ax.grid(True, alpha=.3); ax.legend()
    fig.tight_layout(); fig.savefig(graphs / filename, dpi=160); plt.close(fig)
    for iteration in sorted({r['iteration'] for r in rows}):
        subset = [r for r in rows if r['iteration'] == iteration]
        iter_graphs = BASE / iteration / 'graphs'
        iter_graphs.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(10, 6))
        for key, legend, marker in ((y1, 'Binary search', 'o'), (y2, 'Z3 min makespan', 's')):
            ax.plot([r['task_count'] for r in subset],
                    [float(r[key]) if r.get(key) is not None else float('nan') for r in subset],
                    marker=marker, label=legend)
        ax.set_xlabel('Tasks'); ax.set_ylabel(label); ax.grid(True, alpha=.3); ax.legend()
        fig.tight_layout(); fig.savefig(iter_graphs / filename, dpi=160); plt.close(fig)

comparison('binary_search_makespan', 'z3_makespan_makespan', 'Makespan', 'makespan_comparison.png')
comparison('binary_search_compute_seconds', 'z3_makespan_compute_seconds', 'Scheduler compute time (seconds)', 'scheduler_time_comparison.png')
for key, label in (('l_min', 'l_min'), ('deadline', 'Deadline')):
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot([r['task_count'] for r in rows], [r[key] for r in rows], marker='o')
    ax.set_xlabel('Tasks'); ax.set_ylabel(label); ax.grid(True, alpha=.3)
    fig.tight_layout(); fig.savefig(graphs / f'{key}.png', dpi=160); plt.close(fig)
    for iteration in sorted({r['iteration'] for r in rows}):
        subset = [r for r in rows if r['iteration'] == iteration]
        iter_graphs = BASE / iteration / 'graphs'
        iter_graphs.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot([r['task_count'] for r in subset], [r[key] for r in subset], marker='o')
        ax.set_xlabel('Tasks'); ax.set_ylabel(label); ax.grid(True, alpha=.3)
        fig.tight_layout(); fig.savefig(iter_graphs / f'{key}.png', dpi=160); plt.close(fig)
print(f'Wrote graphs to {graphs}')
