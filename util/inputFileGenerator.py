
import re
import json
import random
import sys
import math
from pathlib import Path

# Optional: only needed if you want to use compute_lmin().
# The current version uses the TGFF hard deadline directly.
# from compute_min import compute_lmin


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

RANDOM_SEED = 42

# Application deadline = hard deadline * this factor
DEADLINE_FACTOR = 1.5

# Platform
PLATFORM = {
    "nodes": [
        {"id": 1,  "is_router": False},
        {"id": 2,  "is_router": False},
        {"id": 3,  "is_router": False},
        {"id": 4,  "is_router": True},
        {"id": 5,  "is_router": True},
        {"id": 6,  "is_router": True},
        {"id": 7,  "is_router": False},
        {"id": 8,  "is_router": True},
        {"id": 9,  "is_router": True},
        {"id": 10, "is_router": True},
        {"id": 11, "is_router": False},
        {"id": 12, "is_router": True},
        {"id": 13, "is_router": True},
        {"id": 14, "is_router": True},
        {"id": 15, "is_router": False},
        {"id": 16, "is_router": False},
        {"id": 17, "is_router": False},
    ],

    "links": [
        {"start": 4,  "end": 1},
        {"start": 5,  "end": 2},
        {"start": 6,  "end": 3},
        {"start": 4,  "end": 5},
        {"start": 4,  "end": 8},
        {"start": 5,  "end": 6},
        {"start": 5,  "end": 9},
        {"start": 6,  "end": 10},
        {"start": 8,  "end": 7},
        {"start": 8,  "end": 9},
        {"start": 9,  "end": 10},
        {"start": 8,  "end": 12},
        {"start": 9,  "end": 13},
        {"start": 10, "end": 14},
        {"start": 10, "end": 11},
        {"start": 12, "end": 13},
        {"start": 13, "end": 14},
        {"start": 12, "end": 15},
        {"start": 13, "end": 16},
        {"start": 14, "end": 17},
    ]
}

FREQUENCIES = [500, 1000]

SCHEMES = [
    {
        "id": 0,
        "wcdt": 0,
        "wcct": 0,
        "wccr": 1
    }
]


# ─────────────────────────────────────────────────────────────────────────────
# Compute nodes and speed factors
# ─────────────────────────────────────────────────────────────────────────────

COMPUTE_NODES = [
    1, 2, 3, 11, 17, 16, 15, 7
]

# Same speed-factor pattern as your existing stress-test script.
SPEED_FACTOR_PATTERN = [
    1, 2, 1.5, 1, 2, 1.5, 1, 2
]


def speed_factors_by_node():
    """
    Assign the processing-power/speed factor to each compute node.

    Node 1  -> 1
    Node 2  -> 2
    Node 3  -> 1.5
    Node 11 -> 1
    Node 17 -> 2
    Node 16 -> 1.5
    Node 15 -> 1
    Node 7  -> 2
    """
    return {
        node_id: SPEED_FACTOR_PATTERN[index]
        for index, node_id in enumerate(COMPUTE_NODES)
    }


def add_speed_factors(platform):
    """
    Add speed_factor to every non-router node.
    Routers do not get a speed_factor.
    """
    platform_copy = json.loads(json.dumps(platform))
    node_speed_factors = speed_factors_by_node()

    for node in platform_copy["nodes"]:
        if not node["is_router"]:
            node["speed_factor"] = node_speed_factors[node["id"]]

    return platform_copy


# ─────────────────────────────────────────────────────────────────────────────
# TGFF parser
# ─────────────────────────────────────────────────────────────────────────────

def parse_tgff(filepath):
    """
    Parse a TGFF file.

    Returns:
        list of task graphs.

    Each graph contains:
        id
        period
        tasks
        arcs
        hard_deadlines
    """

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    graphs = []

    # ── Parse @COMMUN 0 execution times ──────────────────────────────────────
    #
    # Example:
    #
    # @COMMUN 0 {
    #   ...
    #   0 0 34.013
    #   1 0 51.5672
    #   2 0 40.7966
    # }
    #
    # We use these execution times as the WCET source.

    commun_match = re.search(
        r'@COMMUN\s+0\s*\{(.*?)\}',
        content,
        re.DOTALL
    )

    if not commun_match:
        raise ValueError(
            "Could not find @COMMUN 0 section in the TGFF file."
        )

    commun_block = commun_match.group(1)

    execution_times = {}

    for line in commun_block.splitlines():
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        parts = line.split()

        # Expected:
        # type version exec_time
        if len(parts) >= 3:
            try:
                task_type = int(parts[0])
                version = int(parts[1])
                exec_time = float(parts[2])

                if version == 0:
                    execution_times[task_type] = exec_time

            except ValueError:
                continue

    if not execution_times:
        raise ValueError(
            "No execution times were found in @COMMUN 0."
        )

    # ── Parse task graph blocks ──────────────────────────────────────────────

    tg_blocks = re.findall(
        r'@TASK_GRAPH\s+(\d+)\s*\{(.*?)\}',
        content,
        re.DOTALL
    )

    if not tg_blocks:
        raise ValueError(
            "No @TASK_GRAPH sections were found in the TGFF file."
        )

    for tg_id, block in tg_blocks:

        # Period
        period_match = re.search(
            r'\bPERIOD\s+([0-9.]+)',
            block
        )

        period = (
            float(period_match.group(1))
            if period_match
            else None
        )

        # Tasks
        tasks = {}

        for match in re.finditer(
            r'TASK\s+(t\d+_\d+)\s+TYPE\s+(\d+)',
            block
        ):
            task_name = match.group(1)
            task_type = int(match.group(2))

            tasks[task_name] = {
                "type": task_type
            }

        # Arcs
        arcs = []

        for match in re.finditer(
            r'ARC\s+(a\d+_\d+)\s+FROM\s+(t\d+_\d+)\s+TO\s+(t\d+_\d+)\s+TYPE\s+(\d+)',
            block
        ):
            arcs.append(
                {
                    "name": match.group(1),
                    "from_task": match.group(2),
                    "to_task": match.group(3),
                    "type": int(match.group(4))
                }
            )

        # Hard deadlines
        hard_deadlines = []

        for match in re.finditer(
            r'HARD_DEADLINE\s+\S+\s+ON\s+(t\d+_\d+)\s+AT\s+([0-9.]+)',
            block
        ):
            hard_deadlines.append(
                {
                    "task": match.group(1),
                    "deadline": float(match.group(2))
                }
            )

        if not tasks:
            print(
                f"Warning: Graph {tg_id} contains no tasks. Skipping."
            )
            continue

        graphs.append(
            {
                "id": int(tg_id),
                "period": period,
                "tasks": tasks,
                "arcs": arcs,
                "hard_deadlines": hard_deadlines,
                "execution_times": execution_times
            }
        )

    return graphs


# ─────────────────────────────────────────────────────────────────────────────
# can_run_on generation
# ─────────────────────────────────────────────────────────────────────────────
# Minimum and maximum number of processors
# that a job can run on.
MIN_NODES = 2
MAX_NODES = 4


def allowed_nodes_for_job(job_id):
    """
    Randomly select the processors on which a job can execute.

    The number of processors is randomly selected between
    MIN_NODES and MAX_NODES.

    The processors themselves are randomly selected from
    COMPUTE_NODES without replacement.
    """

    number_of_nodes = random.randint(MIN_NODES, MAX_NODES)

    return random.sample(
        COMPUTE_NODES,
        number_of_nodes
    )

# ─────────────────────────────────────────────────────────────────────────────
# Processing times
# ─────────────────────────────────────────────────────────────────────────────

def processing_times_for_job(wcet, allowed_nodes):
    """
    processing_time = ceil(
        wcet_fullspeed * node_speed_factor
    )

    Example:

        wcet = 41
        node factor = 1.5

        41 * 1.5 = 61.5
        ceil(61.5) = 62

    Therefore every processing time is an integer.
    """

    node_speed_factors = speed_factors_by_node()

    return [
        math.ceil(
            wcet * node_speed_factors[node_id]
        )
        for node_id in allowed_nodes
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Task selection
# ─────────────────────────────────────────────────────────────────────────────

def select_tasks(graph, requested_job_count):
    """
    Select the requested number of tasks.

    Tasks are taken in TGFF order.

    The returned task names are therefore:

        t0_0
        t0_1
        ...
        t0_(N-1)

    for a graph whose original tasks follow the normal TGFF numbering.

    The selected tasks are then renumbered to local JSON IDs:

        0
        1
        ...
        N-1
    """

    task_names = list(graph["tasks"].keys())

    if requested_job_count > len(task_names):
        raise ValueError(
            f"Requested {requested_job_count} jobs, "
            f"but graph {graph['id']} only contains "
            f"{len(task_names)} tasks."
        )

    return task_names[:requested_job_count]


# ─────────────────────────────────────────────────────────────────────────────
# Message selection
# ─────────────────────────────────────────────────────────────────────────────

def select_messages(graph, selected_tasks, requested_message_count):
    """
    Select messages randomly from arcs whose sender and receiver
    both survived task selection.

    Messages are then renumbered from 0.
    """

    selected_task_set = set(selected_tasks)

    valid_arcs = [
        arc
        for arc in graph["arcs"]
        if (
            arc["from_task"] in selected_task_set
            and arc["to_task"] in selected_task_set
        )
    ]

    if requested_message_count > len(valid_arcs):
        raise ValueError(
            f"Requested {requested_message_count} messages, "
            f"but only {len(valid_arcs)} valid messages remain "
            f"after selecting the requested jobs."
        )

    # Randomly select the requested number of arcs.
    chosen_arcs = random.sample(
        valid_arcs,
        requested_message_count
    )

    return chosen_arcs


# ─────────────────────────────────────────────────────────────────────────────
# Deadline
# ─────────────────────────────────────────────────────────────────────────────

def application_deadline(graph):
    """
    Use the maximum hard deadline from the TGFF graph.

    Application deadline:

        ceil(max_hard_deadline * 1.5)

    Example:

        hard deadline = 900
        application deadline = ceil(900 * 1.5)
                            = 1350
    """

    if not graph["hard_deadlines"]:
        raise ValueError(
            f"Graph {graph['id']} has no HARD_DEADLINE entries."
        )

    max_hard_deadline = max(
        item["deadline"]
        for item in graph["hard_deadlines"]
    )

    return math.ceil(
        max_hard_deadline * DEADLINE_FACTOR
    )


# ─────────────────────────────────────────────────────────────────────────────
# JSON generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_json_for_graph(
    graph,
    requested_job_count,
    requested_message_count
):
    """
    Generate the final JSON for one TGFF task graph.
    """

    # ── Select tasks ─────────────────────────────────────────────────────────

    selected_tasks = select_tasks(
        graph,
        requested_job_count
    )

    # Map TGFF task name -> local JSON job ID
    local_task_id = {
        task_name: job_id
        for job_id, task_name in enumerate(selected_tasks)
    }

    # ── Generate jobs ────────────────────────────────────────────────────────

    jobs = []

    for job_id, task_name in enumerate(selected_tasks):

        task_type = graph["tasks"][task_name]["type"]

        if task_type not in graph["execution_times"]:
            raise ValueError(
                f"Task type {task_type} for {task_name} "
                f"does not exist in @COMMUN 0."
            )

        # TGFF execution time
        raw_wcet = graph["execution_times"][task_type]

        # All JSON values must be whole numbers.
        wcet = math.ceil(raw_wcet)

        allowed_nodes = allowed_nodes_for_job(job_id)

        processing_times = processing_times_for_job(
            wcet,
            allowed_nodes
        )

        jobs.append(
            {
                "id": job_id,
                "wcet_fullspeed": wcet,
                "mcet": 0,
                "processing_times": processing_times,
                "can_run_on": allowed_nodes
            }
        )

    # ── Select messages ──────────────────────────────────────────────────────

    selected_arcs = select_messages(
        graph,
        selected_tasks,
        requested_message_count
    )

    messages = []

    for message_id, arc in enumerate(selected_arcs):

        sender = local_task_id[arc["from_task"]]
        receiver = local_task_id[arc["to_task"]]

        messages.append(
            {
                "id": message_id,
                "sender": sender,
                "receiver": receiver,

                # Message size is not defined by the TGFF ARC itself.
                # Use a deterministic integer range for now.
                "size": random.randint(10, 30),

                "timetriggered": True,

                # TGFF does not directly provide the JSON message period.
                # Use the TGFF graph period when available, rounded up.
                "period": (
                    math.ceil(graph["period"])
                    if graph["period"] is not None
                    else 50
                )
            }
        )

    # ── Deadline ─────────────────────────────────────────────────────────────

    deadline = application_deadline(graph)

    # ── Final JSON ───────────────────────────────────────────────────────────

    return {
        "application": {
            "jobs": jobs,
            "messages": messages,
            "deadline": deadline
        },

        "platform": add_speed_factors(PLATFORM),

        "frequencies": FREQUENCIES,

        "schemes": SCHEMES
    }


# ─────────────────────────────────────────────────────────────────────────────
# User input
# ─────────────────────────────────────────────────────────────────────────────

def ask_integer(prompt, minimum, maximum):
    """
    Ask the user for an integer within a specified range.
    """

    while True:
        raw = input(
            f"{prompt} [{minimum}-{maximum}]: "
        ).strip()

        try:
            value = int(raw)
        except ValueError:
            print("Please enter a whole number.")
            continue

        if value < minimum or value > maximum:
            print(
                f"Please enter a value between "
                f"{minimum} and {maximum}."
            )
            continue

        return value


def ask_generation_config(graph):
    """
    Ask the user for the number of jobs and messages.

    The maximum number of jobs is determined by the TGFF graph.

    The maximum number of messages is determined dynamically
    after the requested number of jobs is selected.
    """

    max_jobs = len(graph["tasks"])

    print()
    print("=" * 70)
    print(f"Task Graph {graph['id']}")
    print("=" * 70)

    print(
        f"Maximum number of jobs available in TGFF: {max_jobs}"
    )

    job_count = ask_integer(
        "Number of jobs",
        1,
        max_jobs
    )

    # Determine how many arcs remain after task reduction.
    selected_tasks = select_tasks(
        graph,
        job_count
    )

    selected_task_set = set(selected_tasks)

    valid_arcs = [
        arc
        for arc in graph["arcs"]
        if (
            arc["from_task"] in selected_task_set
            and arc["to_task"] in selected_task_set
        )
    ]

    max_messages = len(valid_arcs)

    print(
        f"Maximum number of messages available "
        f"with {job_count} jobs: {max_messages}"
    )

    message_count = ask_integer(
        "Number of messages",
        0,
        max_messages
    )

    return job_count, message_count


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():

    if len(sys.argv) < 2:
        print(
            "Usage:\n"
            "    python inputFileGenerator.py <input.tgff>"
        )
        sys.exit(1)

    tgff_path = Path(sys.argv[1])

    if not tgff_path.exists():
        print(
            f"Error: TGFF file not found: {tgff_path}"
        )
        sys.exit(1)

    # Reproducible generation.
    random.seed(RANDOM_SEED)

    try:
        graphs = parse_tgff(tgff_path)
    except Exception as exc:
        print(f"Error while parsing TGFF: {exc}")
        sys.exit(1)

    print()
    print(f"Parsed {len(graphs)} task graph(s) from:")
    print(f"  {tgff_path}")

    # Output directory = current directory.
    output_dir = Path("D:/masters/project_work/test_code/context/inputFiles")

    for graph in graphs:

        print()
        print(
            f"Processing Task Graph {graph['id']}..."
        )

        # Ask independently for each graph.
        job_count, message_count = ask_generation_config(
            graph
        )

        try:
            result = generate_json_for_graph(
                graph,
                job_count,
                message_count
            )
        except Exception as exc:
            print(
                f"Error generating Graph {graph['id']}: {exc}"
            )
            continue

        # Required naming convention:
        #
        #     <number_of_jobs>_<number_of_messages>.json
        #
        output_file = (
            output_dir
            / f"{job_count}_{message_count}.json"
        )

        with open(
            output_file,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                result,
                f,
                indent=4
            )

        print()
        print(
            f"Generated: {output_file}"
        )
        print(
            f"  Jobs:             {len(result['application']['jobs'])}"
        )
        print(
            f"  Messages:         {len(result['application']['messages'])}"
        )
        print(
            f"  Deadline:         {result['application']['deadline']}"
        )

        print("  Job processing configuration:")

        for job in result["application"]["jobs"]:
            print(
                f"    Job {job['id']}: "
                f"WCET={job['wcet_fullspeed']}, "
                f"nodes={job['can_run_on']}, "
                f"processing_times={job['processing_times']}"
            )

        print()


if __name__ == "__main__":
    main()

