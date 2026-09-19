import argparse
import json
import math


DEFAULT_ALPHA = 0.5

# Deadline formula reference:
# Q. He, N. Guan, M. Lv, and W. Yi, "Bounding the Response Time of DAG
# Tasks Using Long Paths", arXiv:2211.08800, 2022.


def calculate_dag_volume(jobs):
    """Return C, the DAG volume: sum of all job WCETs."""
    return sum(job["wcet_fullspeed"] for job in jobs)


def calculate_critical_path_length(jobs, messages):
    """Return L, the longest weighted dependency chain in the DAG."""
    wcet_by_job = {job["id"]: job["wcet_fullspeed"] for job in jobs}
    successors = {job["id"]: [] for job in jobs}

    for message in messages:
        sender = message["sender"]
        receiver = message["receiver"]
        if sender not in successors:
            raise ValueError(f"Message sender job does not exist: {sender}")
        if receiver not in wcet_by_job:
            raise ValueError(f"Message receiver job does not exist: {receiver}")
        successors[sender].append(receiver)

    visiting = set()
    visited = {}

    def longest_from(job_id):
        if job_id in visited:
            return visited[job_id]
        if job_id in visiting:
            raise ValueError("The job dependency graph contains a cycle.")

        visiting.add(job_id)
        downstream = [
            longest_from(child_id)
            for child_id in successors[job_id]
        ]
        visiting.remove(job_id)

        result = wcet_by_job[job_id] + (max(downstream) if downstream else 0)
        visited[job_id] = result
        return result

    if not jobs:
        return 0

    return max(longest_from(job["id"]) for job in jobs)


def calculate_application_deadline(jobs, messages, alpha=DEFAULT_ALPHA):
    """
    Calculate application deadline using:

        D = L + alpha * (C - L)

    where L is the longest path / critical-path length and C is the DAG
    volume. This follows the synthetic DAG task generation method described
    in the evaluation section of:

        Q. He, N. Guan, M. Lv, and W. Yi,
        "Bounding the Response Time of DAG Tasks Using Long Paths",
        arXiv:2211.08800, 2022.

    The paper uses this form to generate DAG task deadlines from L and C.
    """
    if alpha < 0:
        raise ValueError("alpha must be non-negative.")

    critical_path = calculate_critical_path_length(jobs, messages)
    volume = calculate_dag_volume(jobs)
    return math.ceil(critical_path + alpha * (volume - critical_path))


def calculate_application_deadline_from_file(input_file, alpha=DEFAULT_ALPHA):
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    application = data["application"]
    return calculate_application_deadline(
        application["jobs"],
        application["messages"],
        alpha=alpha,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Calculate application deadline for a generated input JSON."
    )
    parser.add_argument("input_file", help="Path to generated scheduler input JSON.")
    parser.add_argument(
        "--alpha",
        type=float,
        default=DEFAULT_ALPHA,
        help=f"Deadline looseness factor. Default: {DEFAULT_ALPHA}",
    )
    args = parser.parse_args()

    deadline = calculate_application_deadline_from_file(
        args.input_file,
        alpha=args.alpha,
    )
    print(deadline)


if __name__ == "__main__":
    main()
