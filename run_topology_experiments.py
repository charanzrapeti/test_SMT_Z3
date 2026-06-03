import argparse
import json
import subprocess
import sys
from pathlib import Path

from topology_generator import TOPOLOGIES, convert_topology, default_output_path


def solver_output_path(input_file):
    input_path = Path(input_file)
    return Path("output") / f"{input_path.stem}_smt_output.json"


def load_solver_summary(output_file):
    if not output_file.exists():
        return {
            "feasible": False,
            "optimal_makespan": None,
        }

    with open(output_file, "r") as f:
        data = json.load(f)

    return {
        "feasible": True,
        "optimal_makespan": data.get("optimal_makespan"),
    }


def run_solver(input_file, solver, timeout):
    output_file = solver_output_path(input_file)

    command = [
        sys.executable,
        solver,
        str(input_file),
    ]

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "ran_solver": True,
            "solver_status": "timeout",
            "return_code": None,
            "output_file": str(output_file),
            "feasible": False,
            "optimal_makespan": None,
        }

    summary = load_solver_summary(output_file)
    return {
        "ran_solver": True,
        "solver_status": "ok" if completed.returncode == 0 else "error",
        "return_code": completed.returncode,
        "output_file": str(output_file),
        **summary,
    }


def parse_topologies(raw_topologies):
    selected = []
    for item in raw_topologies:
        if item == "all":
            selected.extend(TOPOLOGIES)
        else:
            selected.append(item)

    return list(dict.fromkeys(selected))


def main():
    parser = argparse.ArgumentParser(
        description="Generate topology variants and optionally run an SMT solver for each one."
    )
    parser.add_argument("input", help="Base input JSON file.")
    parser.add_argument(
        "-t",
        "--topologies",
        nargs="+",
        choices=("all", *TOPOLOGIES),
        default=["all"],
        help="Topologies to generate. Defaults to all.",
    )
    parser.add_argument(
        "--run-solver",
        action="store_true",
        help="Run the selected solver after generating each topology.",
    )
    parser.add_argument(
        "--solver",
        default="test2Parallize.py",
        help="Solver script to run. Defaults to test2Parallize.py.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Solver timeout per topology in seconds. Defaults to 300.",
    )
    parser.add_argument(
        "--summary",
        default="output/topology_experiment_summary.json",
        help="Summary JSON output path.",
    )
    parser.add_argument(
        "--router-start",
        type=int,
        help="First router ID for generated topologies.",
    )

    args = parser.parse_args()

    selected_topologies = parse_topologies(args.topologies)
    results = []

    for topology in selected_topologies:
        output_file = default_output_path(args.input, topology)
        generation_summary = convert_topology(
            input_path=args.input,
            output_path=output_file,
            topology=topology,
            router_start=args.router_start,
        )

        result = {
            **generation_summary,
            "input_file": str(output_file),
            "ran_solver": False,
        }

        print(
            f"Generated {topology}: {output_file} "
            f"({generation_summary['links']} links)"
        )

        if args.run_solver:
            print(f"Running {args.solver} for {topology}...")
            result.update(run_solver(output_file, args.solver, args.timeout))
            if result["feasible"]:
                print(f"  feasible, optimal_makespan={result['optimal_makespan']}")
            else:
                print(f"  not feasible or no output ({result['solver_status']})")

        results.append(result)

    summary_path = Path(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w") as f:
        json.dump(
            {
                "base_input": args.input,
                "run_solver": args.run_solver,
                "solver": args.solver,
                "results": results,
            },
            f,
            indent=4,
        )

    print(f"Summary written to {summary_path}")


if __name__ == "__main__":
    main()
