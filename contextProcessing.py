import copy
import json
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
CONTEXT_FILE = ROOT_DIR / "context" / "context.json"
BASE_INPUT_FILE = ROOT_DIR / "input" / "graph_1 - input.json"
EVENT_INPUT_DIR = ROOT_DIR / "input"
EVENT_SCHEDULE_DIR = ROOT_DIR / "prevSchedules" / "contextSchedules"
SCHEDULER_FILE = ROOT_DIR / "test2Parallize.py"


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=4)


def event_file_stem(event):
    event_type = event.get("event_type", "event")
    event_id = event.get("event_id", "unknown")
    return f"{event_type}_{event_id}"


def normalize_node_id(node_id):
    return str(node_id)


def attach_scheduler_result(event, input_name, schedule_name, sat, result):
    event["event_input"] = input_name
    event["event_schedule"] = schedule_name
    event["SAT"] = sat

    if not sat:
        event["scheduler_returncode"] = result.returncode
        if result.stderr:
            event["scheduler_error"] = result.stderr.strip()

    return event


def remove_failed_processors_from_jobs(input_data, failed_node_ids):
    failed_node_ids = {normalize_node_id(node_id) for node_id in failed_node_ids}
    affected_jobs = []

    for job in input_data["application"]["jobs"]:
        can_run_on = job.get("can_run_on", [])
        updated_can_run_on = [
            node_id
            for node_id in can_run_on
            if normalize_node_id(node_id) not in failed_node_ids
        ]

        if len(updated_can_run_on) != len(can_run_on):
            affected_jobs.append(job["id"])
            job["can_run_on"] = updated_can_run_on

    return affected_jobs


def find_processors_only_connected_to_router(input_data, router_id):
    router_id = normalize_node_id(router_id)
    nodes = input_data["platform"].get("nodes", [])
    links = input_data["platform"].get("links", [])
    neighbours_by_node = {}

    for link in links:
        start = normalize_node_id(link.get("start"))
        end = normalize_node_id(link.get("end"))
        neighbours_by_node.setdefault(start, set()).add(end)
        neighbours_by_node.setdefault(end, set()).add(start)

    implicit_failures = []
    for node in nodes:
        node_id = normalize_node_id(node.get("id"))
        if node.get("is_router"):
            continue

        neighbours = neighbours_by_node.get(node_id, set())
        if neighbours == {router_id}:
            implicit_failures.append(node.get("id"))

    return implicit_failures


def remove_router_from_input(input_data, router_id):
    router_id = normalize_node_id(router_id)
    updated_data = copy.deepcopy(input_data)
    platform = updated_data["platform"]

    platform["nodes"] = [
        node
        for node in platform.get("nodes", [])
        if normalize_node_id(node.get("id")) != router_id
    ]

    platform["links"] = [
        link
        for link in platform.get("links", [])
        if (
            normalize_node_id(link.get("start")) != router_id
            and normalize_node_id(link.get("end")) != router_id
        )
    ]

    return updated_data


def run_scheduler(input_path, schedule_path):
    EVENT_SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
    if schedule_path.exists():
        schedule_path.unlink()

    result = subprocess.run(
        [
            sys.executable,
            str(SCHEDULER_FILE),
            str(input_path),
            "--output-file",
            str(schedule_path),
        ],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
    )

    return result.returncode == 0 and schedule_path.exists(), result


def process_rout_failure(event, base_input_data):
    router_id = normalize_node_id(event["node_id"])
    stem = event_file_stem(event)
    input_name = f"{stem}_input.json"
    schedule_name = f"{stem}_schedule.json"

    event_input_path = EVENT_INPUT_DIR / input_name
    event_schedule_path = EVENT_SCHEDULE_DIR / schedule_name

    implicit_failed_processors = find_processors_only_connected_to_router(
        base_input_data,
        router_id,
    )
    updated_input = remove_router_from_input(base_input_data, router_id)
    affected_jobs = remove_failed_processors_from_jobs(
        updated_input,
        implicit_failed_processors,
    )
    save_json(event_input_path, updated_input)

    sat, result = run_scheduler(event_input_path, event_schedule_path)

    event["implicit_failed_processors"] = implicit_failed_processors
    event["affected_jobs"] = affected_jobs
    return attach_scheduler_result(event, input_name, schedule_name, sat, result)


def process_proc_failure(event, base_input_data):
    failed_node_id = event["node_id"]
    stem = event_file_stem(event)
    input_name = f"{stem}_input.json"
    schedule_name = f"{stem}_schedule.json"

    event_input_path = EVENT_INPUT_DIR / input_name
    event_schedule_path = EVENT_SCHEDULE_DIR / schedule_name

    updated_input = copy.deepcopy(base_input_data)
    affected_jobs = remove_failed_processors_from_jobs(
        updated_input,
        [failed_node_id],
    )
    save_json(event_input_path, updated_input)

    sat, result = run_scheduler(event_input_path, event_schedule_path)

    event["failed_processor"] = failed_node_id
    event["affected_jobs"] = affected_jobs
    return attach_scheduler_result(event, input_name, schedule_name, sat, result)


def get_execution_percentage(event):
    percentage = event.get("ET")
    if not isinstance(percentage, int):
        raise ValueError("Slack event ET must be a whole-number percentage.")
    if percentage < 10 or percentage > 100 or percentage % 10 != 0:
        raise ValueError("Slack event ET must be a multiple of 10 from 10 to 100.")
    return percentage


def process_slack_event(event, base_input_data):
    """
    Process a Slack Event.

    The affected job's actual execution is calculated from ET, a
    whole-number percentage from 10 to 100.

    A new scheduler input JSON is generated and the SMT scheduler
    is executed to produce a new schedule.
    """

    job_id = int(event["job_id"])
    execution_percentage = get_execution_percentage(event)

    stem = event_file_stem(event)

    input_name = f"{stem}_input.json"
    schedule_name = f"{stem}_schedule.json"

    event_input_path = EVENT_INPUT_DIR / input_name
    event_schedule_path = EVENT_SCHEDULE_DIR / schedule_name

    updated_input = copy.deepcopy(base_input_data)

    found = False

    for job in updated_input["application"]["jobs"]:

        if job["id"] == job_id:

            found = True

            wcet = job["wcet_fullspeed"]

            actual_execution = int(round(wcet * execution_percentage / 100))

            slack = wcet - actual_execution

            job["wcet_fullspeed"] = actual_execution
            job["original_wcet"] = wcet
            job["actual_execution"] = actual_execution
            job["execution_percentage"] = execution_percentage
            job["slack"] = slack

            break

    if not found:
        raise ValueError(f"Job {job_id} not found.")

    #
    # Save new scheduler input
    #
    save_json(event_input_path, updated_input)

    #
    # Run scheduler
    #
    sat, result = run_scheduler(
        event_input_path,
        event_schedule_path,
    )

    attach_scheduler_result(event, input_name, schedule_name, sat, result)

    if sat:

        event["original_wcet"] = wcet
        event["actual_execution"] = actual_execution
        event["execution_percentage"] = execution_percentage
        event["slack"] = slack

    return event


EVENT_PROCESSORS = {
    "proc_failure": process_proc_failure,
    "rout_failure": process_rout_failure,
    "slack_event": process_slack_event,
}


def process_context():
    context_events = load_json(CONTEXT_FILE)
    base_input_data = load_json(BASE_INPUT_FILE)

    processed_events = []

    for event in context_events:
        processor = EVENT_PROCESSORS.get(event.get("event_type"))
        if processor is None:
            processed_events.append(event)
            continue

        processed_events.append(processor(event, base_input_data))

    save_json(CONTEXT_FILE, processed_events)
    return processed_events


if __name__ == "__main__":
    events = process_context()
    processed_count = sum("SAT" in event for event in events)
    print(f"Processed {processed_count} event(s). Updated {CONTEXT_FILE}.")
