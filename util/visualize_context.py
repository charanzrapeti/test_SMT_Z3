import argparse
import html
import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONTEXT_FILE = ROOT_DIR / "context" / "context.json"
DEFAULT_OUTPUT_FILE = ROOT_DIR / "context" / "context_dag.svg"


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def event_label(event):
    lines = [
        f"event {event['event_id']}",
        event["event_type"],
        f"t={event.get('event_time')}",
    ]

    if "schedule_makespan" in event:
        lines.append(f"T={event['schedule_makespan']}")
    if "schedule_calculation_seconds" in event:
        lines.append(f"{event['schedule_calculation_seconds']:.2f}s")

    return lines


def compute_levels(events):
    by_id = {event["event_id"]: event for event in events}
    memo = {}

    def level_for(event):
        event_id = event["event_id"]
        if event_id in memo:
            return memo[event_id]

        parent_id = event.get("pred_event_id")
        if parent_id is None or parent_id not in by_id:
            memo[event_id] = 0
        else:
            memo[event_id] = level_for(by_id[parent_id]) + 1
        return memo[event_id]

    for event in events:
        event["dag_level"] = level_for(event)

    return events


def svg_text(lines, x, y):
    parts = []
    for idx, line in enumerate(lines):
        weight = "700" if idx == 0 else "400"
        parts.append(
            f'<text x="{x}" y="{y + idx * 18}" text-anchor="middle" '
            f'font-size="14" font-weight="{weight}">{html.escape(str(line))}</text>'
        )
    return "\n".join(parts)


def build_svg(events):
    events = compute_levels(events)
    levels = {}
    for event in events:
        levels.setdefault(event["dag_level"], []).append(event)

    for level_events in levels.values():
        level_events.sort(key=lambda item: item["event_id"])

    node_width = 180
    node_height = 108
    x_gap = 70
    y_gap = 120
    margin = 60
    max_level_width = max(len(level_events) for level_events in levels.values())
    width = max(900, margin * 2 + max_level_width * node_width + (max_level_width - 1) * x_gap)
    height = margin * 2 + len(levels) * node_height + (len(levels) - 1) * y_gap

    positions = {}
    for level, level_events in sorted(levels.items()):
        row_width = len(level_events) * node_width + (len(level_events) - 1) * x_gap
        start_x = (width - row_width) / 2
        y = margin + level * (node_height + y_gap)
        for index, event in enumerate(level_events):
            x = start_x + index * (node_width + x_gap)
            positions[event["event_id"]] = (x, y)

    edges = []
    for event in events:
        parent_id = event.get("pred_event_id")
        if parent_id is None or parent_id not in positions:
            continue

        parent_x, parent_y = positions[parent_id]
        child_x, child_y = positions[event["event_id"]]
        edges.append(
            f'<line x1="{parent_x + node_width / 2}" y1="{parent_y + node_height}" '
            f'x2="{child_x + node_width / 2}" y2="{child_y}" '
            'stroke="#52616b" stroke-width="2" marker-end="url(#arrow)" />'
        )

    nodes = []
    colors = {
        "slack_event": "#d8f3dc",
        "proc_failure": "#ffd6a5",
        "rout_failure": "#ffccd5",
    }

    for event in events:
        x, y = positions[event["event_id"]]
        fill = colors.get(event["event_type"], "#e9ecef")
        nodes.append(
            f'<rect x="{x}" y="{y}" width="{node_width}" height="{node_height}" '
            f'rx="8" fill="{fill}" stroke="#2f3e46" stroke-width="1.5" />'
        )
        nodes.append(svg_text(event_label(event), x + node_width / 2, y + 26))

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<defs>
  <marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">
    <path d="M 0 0 L 10 4 L 0 8 z" fill="#52616b" />
  </marker>
</defs>
<rect width="100%" height="100%" fill="#f8f9fa" />
<text x="{width / 2}" y="32" text-anchor="middle" font-size="22" font-weight="700">Context Event DAG</text>
{chr(10).join(edges)}
{chr(10).join(nodes)}
</svg>
'''


def main():
    parser = argparse.ArgumentParser(description="Render context.json as a DAG SVG.")
    parser.add_argument("--context-file", default=DEFAULT_CONTEXT_FILE)
    parser.add_argument("--output-file", default=DEFAULT_OUTPUT_FILE)
    args = parser.parse_args()

    context_file = Path(args.context_file)
    output_file = Path(args.output_file)
    events = load_json(context_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(build_svg(events))
    print(f"Context DAG written to {output_file}")


if __name__ == "__main__":
    main()
