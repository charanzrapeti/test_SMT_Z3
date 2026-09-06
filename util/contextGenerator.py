import json
import random
from pathlib import Path


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def generate_context(
    total_events=13,
    proc_failures=2,
    router_failures=2,
    slack_events=9,
    input_file=None,

    # -----------------------------
    # Allowed nodes
    # -----------------------------
    proc_failure_nodes=None,
    router_failure_nodes=None,
    slack_event_nodes=None,

    seed=None,
):
    """
    Generates a context DAG.

    Event types:
        - proc_failure
        - rout_failure
        - slack_event
    """

    if seed is not None:
        random.seed(seed)

    input_data = None
    deadline = 100
    if input_file is not None:
        input_data = load_json(input_file)
        deadline = input_data["application"]["deadline"]

    if proc_failures + router_failures + slack_events != total_events:
        raise ValueError(
            "proc_failures + router_failures + slack_events must equal total_events"
        )

    # -----------------------------
    # Default empty lists
    # -----------------------------
    proc_failure_nodes = list(proc_failure_nodes or [])
    router_failure_nodes = list(router_failure_nodes or [])
    slack_event_nodes = list(slack_event_nodes or [])

    # Enough nodes?
    if len(proc_failure_nodes) < proc_failures:
        raise ValueError(
            "Not enough processor nodes supplied for proc_failure events."
        )

    if len(router_failure_nodes) < router_failures:
        raise ValueError(
            "Not enough router nodes supplied for rout_failure events."
        )

    if len(slack_event_nodes) < slack_events:
        raise ValueError(
            "Not enough slack nodes supplied for slack events."
        )

    # -----------------------------
    # Event types
    # -----------------------------
    event_types = (
        ["proc_failure"] * proc_failures
        + ["rout_failure"] * router_failures
        + ["slack_event"] * slack_events
    )

    random.shuffle(event_types)

    # -----------------------------
    # Generate DAG
    # -----------------------------
    events = []

    for event_id in range(total_events):

        event_type = event_types[event_id]

        if event_type == "proc_failure":

            node_id = random.choice(proc_failure_nodes)
            proc_failure_nodes.remove(node_id)
            et = None

        elif event_type == "rout_failure":

            node_id = random.choice(router_failure_nodes)
            router_failure_nodes.remove(node_id)
            et = None

        elif event_type == "slack_event":

            node_id = random.choice(slack_event_nodes)
            slack_event_nodes.remove(node_id)

            # Execution percentage for the slack-event WCET update.
            et = random.choice(range(10, 101, 10))

        pred_event_id = None
        parent_level = 0
        if event_id > 0:
            pred_event_id = random.randint(0, event_id - 1)
            parent_level = events[pred_event_id]["dag_level"] + 1

        event_time = parent_level * deadline + random.randint(0, deadline)

        event = {
            "event_id": event_id,
            "event_type": event_type,
            "event_time": event_time,
            "ET": et,
            "pred_event_id": pred_event_id,
            "dag_level": parent_level,
        }

        if event_type == "slack_event":
            event["job_id"] = int(node_id)
        else:
            event["node_id"] = node_id

        events.append(event)

    # -----------------------------
    # Save
    # -----------------------------
    output_dir = Path(__file__).resolve().parent.parent / "context"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "context.json"

    with open(output_file, "w") as f:
        json.dump(events, f, indent=4)

    print(f"Saved {len(events)} events to {output_file}")

    return events


if __name__ == "__main__":

    generate_context(
        total_events=13,
        proc_failures=5,
        router_failures=4,
        slack_events=4,
        input_file=Path(__file__).resolve().parent.parent / "input" / "graph_1 - input.json",

        proc_failure_nodes=[
          
            "1",
            "2",
            "3",
            "11",
            "17",
            "16",
            "15",
            "7",
        ],

        router_failure_nodes=[
            "9",
            "8",
            "10",
            "12",
            "13",
            "14"
        ],

        slack_event_nodes=[
            "18",
            "17",
            "12",
            "7",
            "6",
            "5",
            "4",
            "9",
            "3",
            "2",
            "1"

        ],

        seed=42,
    )
