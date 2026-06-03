import argparse
import copy
import json
from pathlib import Path


TOPOLOGIES = ("line", "ring", "star", "mesh", "tree")


def sorted_compute_nodes(platform):
    return sorted(node["id"] for node in platform["nodes"] if not node["is_router"])


def make_router_ids(compute_nodes, router_start=None):
    if router_start is None:
        router_start = max(compute_nodes) + 1
    return list(range(router_start, router_start + len(compute_nodes)))


def add_link(links, a, b):
    if a == b:
        return
    edge = tuple(sorted((a, b)))
    links.add(edge)


def build_router_links(router_ids, topology):
    links = set()

    if len(router_ids) <= 1:
        return links

    if topology == "line":
        for i in range(len(router_ids) - 1):
            add_link(links, router_ids[i], router_ids[i + 1])

    elif topology == "ring":
        for i in range(len(router_ids)):
            add_link(links, router_ids[i], router_ids[(i + 1) % len(router_ids)])

    elif topology == "star":
        center = router_ids[0]
        for router in router_ids[1:]:
            add_link(links, center, router)

    elif topology == "mesh":
        for i in range(len(router_ids)):
            for j in range(i + 1, len(router_ids)):
                add_link(links, router_ids[i], router_ids[j])

    elif topology == "tree":
        for child_idx in range(1, len(router_ids)):
            parent_idx = (child_idx - 1) // 2
            add_link(links, router_ids[parent_idx], router_ids[child_idx])

    else:
        raise ValueError(f"Unknown topology '{topology}'. Choose one of: {', '.join(TOPOLOGIES)}")

    return links


def build_platform(compute_nodes, topology, router_start=None):
    router_ids = make_router_ids(compute_nodes, router_start)

    nodes = [{"id": node_id, "is_router": False} for node_id in compute_nodes]
    nodes.extend({"id": router_id, "is_router": True} for router_id in router_ids)

    links = set()

    # Each compute node gets a local access router. This preserves the existing
    # scheduler assumption that jobs run only on non-router nodes.
    for compute_node, router_id in zip(compute_nodes, router_ids):
        add_link(links, compute_node, router_id)

    links.update(build_router_links(router_ids, topology))

    return {
        "nodes": nodes,
        "links": [
            {"start": start, "end": end}
            for start, end in sorted(links)
        ],
    }


def convert_topology(input_path, output_path, topology, router_start=None):
    with open(input_path, "r") as f:
        data = json.load(f)

    compute_nodes = sorted_compute_nodes(data["platform"])
    if not compute_nodes:
        raise ValueError("Input platform has no compute nodes.")

    new_data = copy.deepcopy(data)
    new_data["platform"] = build_platform(compute_nodes, topology, router_start)

    with open(output_path, "w") as f:
        json.dump(new_data, f, indent=4)

    return {
        "topology": topology,
        "compute_nodes": len(compute_nodes),
        "routers": len(compute_nodes),
        "links": len(new_data["platform"]["links"]),
        "output": str(output_path),
    }


def default_output_path(input_path, topology):
    path = Path(input_path)
    return path.with_name(f"{path.stem}_{topology}_topology{path.suffix}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate a new platform topology while preserving the application and compute node IDs."
    )
    parser.add_argument("input", help="Existing input JSON file.")
    parser.add_argument(
        "-t",
        "--topology",
        choices=TOPOLOGIES,
        required=True,
        help="Router fabric topology to generate.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output JSON path. Defaults to INPUT_<topology>_topology.json.",
    )
    parser.add_argument(
        "--router-start",
        type=int,
        help="First router ID. Defaults to max(compute_node_id) + 1.",
    )

    args = parser.parse_args()
    output = args.output or default_output_path(args.input, args.topology)

    summary = convert_topology(
        input_path=args.input,
        output_path=output,
        topology=args.topology,
        router_start=args.router_start,
    )

    print(
        f"Wrote {summary['topology']} topology to {summary['output']} "
        f"({summary['compute_nodes']} compute nodes, {summary['routers']} routers, {summary['links']} links)."
    )


if __name__ == "__main__":
    main()
