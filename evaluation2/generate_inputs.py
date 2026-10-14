#!/usr/bin/env python3
"""Generate the deterministic Evaluation 2 benchmark matrix."""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from util.inputFileGenerator import generate_json_for_graph, parse_tgff
from util.compute_min import compute_lmin
from util.deadline_calculator import calculate_application_deadline

BASE = Path(__file__).resolve().parent
TASKS = {
    "iteration1": [50, 53, 56, 59, 62, 65, 68, 71, 75, 80],
    "iteration2": list(range(82, 121, 2)),
    "iteration3": [128, 136, 144, 152, 160, 168, 176, 184, 192, 200],
    "iteration4": [210, 220, 230, 240, 250],
}


def main():
    graph = parse_tgff(ROOT / "util/simple6.tgff")[2]
    previous_lmin = 0
    manifest = []
    case_index = 0
    for iteration, task_counts in TASKS.items():
        input_dir = BASE / iteration / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        (BASE / iteration / "output").mkdir(parents=True, exist_ok=True)
        (BASE / iteration / "logs").mkdir(parents=True, exist_ok=True)
        (BASE / iteration / "graphs").mkdir(parents=True, exist_ok=True)
        for task_count in task_counts:
            message_count = task_count + [0, 10, 20][case_index % 3]
            case_index += 1
            random.seed(4200 + task_count * 31 + message_count)
            data = generate_json_for_graph(graph, task_count, message_count)
            lmin = compute_lmin(data["application"]["jobs"], data["application"]["messages"], verbose=False)

            # Keep TGFF workload shape, applying the smallest uniform WCET
            # offset that ensures strictly rising l_min across this suite.
            offset = 0
            while lmin <= previous_lmin:
                offset += 1
                for job in data["application"]["jobs"]:
                    job["wcet_fullspeed"] += 1
                    job["processing_times"] = [
                        int(job["wcet_fullspeed"] * next(
                            node["speed_factor"] for node in data["platform"]["nodes"]
                            if node["id"] == node_id
                        ) + 0.999999)
                        for node_id in job["can_run_on"]
                    ]
                lmin = compute_lmin(data["application"]["jobs"], data["application"]["messages"], verbose=False)

            data["application"]["deadline"] = calculate_application_deadline(
                data["application"]["jobs"], data["application"]["messages"], alpha=0.5
            )
            case = f"{task_count}T_{message_count}M"
            input_path = input_dir / f"{case}.json"
            input_path.write_text(json.dumps(data, indent=2) + "\n")
            previous_lmin = lmin
            manifest.append({
                "iteration": iteration, "case": case,
                "input_file": str(input_path.relative_to(BASE)),
                "task_count": task_count, "message_count": message_count,
                "l_min": lmin, "deadline": data["application"]["deadline"],
                "wcet_offset": offset, "tgff": "util/simple6.tgff#graph2",
            })
            print(f"{iteration}/{case}: tasks={task_count} messages={message_count} l_min={lmin} offset={offset}")
    (BASE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote {len(manifest)} inputs and {BASE / 'manifest.json'}")


if __name__ == "__main__":
    main()
