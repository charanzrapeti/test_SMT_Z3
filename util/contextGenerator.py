import json
import random
from pathlib import Path


def generate_context(
    total_events=10,
    proc_failures=7,
    router_failures=3,
    slack_events=2,

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

            # Execution time (seconds)
            et = round(random.uniform(0.5, 10.0), 3)

        event = {
            "event_id": event_id,
            "event_type": event_type,
            "event_time": random.randint(0, 100), # update this to be more realistic if needed , #randomGenertor for slackpercentage.
            "node_id": node_id,
            "ET": et,
            "event_input": f"event_{event_id}_input.json",
            "event_schedule": f"schedule_{event_id}.json",
            "pred_event_id": None,
        }

        if event_id > 0:
            event["pred_event_id"] = random.randint(0, event_id - 1)

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
        total_events=6,
        proc_failures=3,
        router_failures=1,
        slack_events=2,

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
            "9"
        ],

        slack_event_nodes=[
             "1",
            "2",
            "3",
            "11",
            "17",
            "16",
            "15",
            "7",
        ],

        seed=42,
    )