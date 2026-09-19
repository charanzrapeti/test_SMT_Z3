import json
import random
import math
import argparse


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

SPEED_FACTOR_VALUES = [1, 1.5, 2]
DEFAULT_COMPUTE_NODES_PER_JOB = 2


# ------------------------------------------------------------
# Load JSON
# ------------------------------------------------------------

def load_json(input_file):
    with open(input_file, "r", encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------
# Rename nodes AND create old_id -> new_id mapping
# ------------------------------------------------------------

def rename_nodes(platform):
    """
    Rename all platform nodes sequentially starting from 1.

    Also creates a mapping:

        old node ID -> new node ID

    Example:

        P1001 -> 1
        P1002 -> 2
        R101  -> 95
        ...

    Returns:
        old_to_new
    """

    old_to_new = {}

    for new_id, node in enumerate(platform["nodes"], start=1):

        old_id = node["id"]

        old_to_new[old_id] = new_id

        node["id"] = new_id

    return old_to_new


# ------------------------------------------------------------
# Update links
# ------------------------------------------------------------

def update_links(platform, old_to_new):
    """
    Update every link's start and end node IDs.

    Old:

        {
            "start": "P1001",
            "end": "R101"
        }

    New:

        {
            "start": 1,
            "end": 95
        }
    """

    if "links" not in platform:
        return

    for link in platform["links"]:

        if "start" in link:
            old_start = link["start"]

            if old_start not in old_to_new:
                raise ValueError(
                    f"Link start node '{old_start}' "
                    f"does not exist in node mapping."
                )

            link["start"] = old_to_new[old_start]

        if "end" in link:
            old_end = link["end"]

            if old_end not in old_to_new:
                raise ValueError(
                    f"Link end node '{old_end}' "
                    f"does not exist in node mapping."
                )

            link["end"] = old_to_new[old_end]


# ------------------------------------------------------------
# Get compute nodes
# ------------------------------------------------------------

def get_compute_nodes(platform):
    """
    Compute nodes:

        is_router == false
    """

    return [
        node["id"]
        for node in platform["nodes"]
        if not node["is_router"]
    ]


# ------------------------------------------------------------
# Get router nodes
# ------------------------------------------------------------

def get_router_nodes(platform):
    """
    Router nodes:

        is_router == true
    """

    return [
        node["id"]
        for node in platform["nodes"]
        if node["is_router"]
    ]


# ------------------------------------------------------------
# Generate speed factors
# ------------------------------------------------------------

def speed_factors_by_node(compute_node_ids):
    """
    Assign one random speed factor to every compute node.

    Possible values:

        1
        1.5
        2
    """

    return {
        node_id: random.choice(SPEED_FACTOR_VALUES)
        for node_id in compute_node_ids
    }


# ------------------------------------------------------------
# Add speed factors to compute nodes
# ------------------------------------------------------------

def add_speed_factors(platform, node_speed_factors):

    for node in platform["nodes"]:

        node_id = node["id"]

        if not node["is_router"]:

            node["speed_factor"] = (
                node_speed_factors[node_id]
            )

        else:

            # Routers should not have speed_factor
            node.pop("speed_factor", None)


# ------------------------------------------------------------
# Calculate processing times
# ------------------------------------------------------------

def processing_times_for_job(
    wcet,
    allowed_nodes,
    node_speed_factors
):
    """
    processing_time =
        ceil(wcet_fullspeed * speed_factor)
    """

    return [
        math.ceil(
            wcet * node_speed_factors[node_id]
        )
        for node_id in allowed_nodes
    ]


# ------------------------------------------------------------
# Assign nodes + processing times to jobs
# ------------------------------------------------------------

def assign_compute_nodes_to_jobs(
    application,
    compute_node_ids,
    node_speed_factors,
    nodes_per_job
):

    if nodes_per_job > len(compute_node_ids):

        raise ValueError(
            f"Requested {nodes_per_job} compute nodes per job, "
            f"but only {len(compute_node_ids)} compute nodes exist."
        )

    for job in application["jobs"]:

        # Randomly select compute nodes
        allowed_nodes = random.sample(
            compute_node_ids,
            nodes_per_job
        )

        # Store node IDs
        job["can_run_on"] = allowed_nodes

        # Calculate processing times
        job["processing_times"] = (
            processing_times_for_job(
                wcet=job["wcet_fullspeed"],
                allowed_nodes=allowed_nodes,
                node_speed_factors=node_speed_factors
            )
        )


# ------------------------------------------------------------
# Process complete file
# ------------------------------------------------------------

def process_file(
    input_file,
    output_file,
    nodes_per_job
):

    # --------------------------------------------------------
    # Load
    # --------------------------------------------------------

    data = load_json(input_file)

    platform = data["platform"]
    application = data["application"]

    # --------------------------------------------------------
    # 1. Rename nodes
    # --------------------------------------------------------

    old_to_new = rename_nodes(platform)

    # --------------------------------------------------------
    # 2. IMPORTANT:
    #    Update link start/end IDs
    # --------------------------------------------------------

    update_links(
        platform,
        old_to_new
    )

    # --------------------------------------------------------
    # 3. Get compute/router nodes
    # --------------------------------------------------------

    compute_node_ids = get_compute_nodes(
        platform
    )

    router_node_ids = get_router_nodes(
        platform
    )

    # --------------------------------------------------------
    # 4. Generate speed factors
    # --------------------------------------------------------

    node_speed_factors = speed_factors_by_node(
        compute_node_ids
    )

    # --------------------------------------------------------
    # 5. Add speed factors
    # --------------------------------------------------------

    add_speed_factors(
        platform,
        node_speed_factors
    )

    # --------------------------------------------------------
    # 6. Assign compute nodes to jobs
    #    and calculate processing times
    # --------------------------------------------------------

    assign_compute_nodes_to_jobs(
        application,
        compute_node_ids,
        node_speed_factors,
        nodes_per_job
    )

    # --------------------------------------------------------
    # 7. Save
    # --------------------------------------------------------

    with open(
        output_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            indent=4
        )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print()
    print("========================================")
    print("JSON generation completed")
    print("========================================")
    print(f"Input file           : {input_file}")
    print(f"Output file          : {output_file}")
    print(
        f"Total platform nodes : "
        f"{len(platform['nodes'])}"
    )
    print(
        f"Compute nodes        : "
        f"{len(compute_node_ids)}"
    )
    print(
        f"Router nodes         : "
        f"{len(router_node_ids)}"
    )
    print(
        f"Compute nodes/job    : "
        f"{nodes_per_job}"
    )
    print(
        f"Jobs                 : "
        f"{len(application['jobs'])}"
    )

    if "links" in platform:
        print(
            f"Links                : "
            f"{len(platform['links'])}"
        )

    print("========================================")
    print()


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Generate scheduling JSON with sequential "
            "node IDs, updated links, random job mappings, "
            "speed factors and processing times."
        )
    )

    parser.add_argument(
        "input",
        help="Input JSON file"
    )

    parser.add_argument(
        "-o",
        "--output",
        default="generated_input.json",
        help=(
            "Output JSON file "
            "(default: generated_input.json)"
        )
    )

    parser.add_argument(
        "-n",
        "--nodes-per-job",
        type=int,
        default=DEFAULT_COMPUTE_NODES_PER_JOB,
        help=(
            "Number of compute nodes assigned "
            "to each job (default: 2)"
        )
    )

    args = parser.parse_args()

    if args.nodes_per_job < 1:
        parser.error(
            "--nodes-per-job must be at least 1"
        )

    process_file(
        args.input,
        args.output,
        args.nodes_per_job
    )


if __name__ == "__main__":
    main()