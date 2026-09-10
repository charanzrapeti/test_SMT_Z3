def compute_k_paths(json_file, k=1):
    import json
    import networkx as nx
    from itertools import islice

    # -------------------------
    # Load JSON
    # -------------------------
    with open(json_file, "r") as f:
        json_data = json.load(f)

    nodes = json_data['platform']['nodes']
    links = json_data['platform']['links']

    # -------------------------
    # Build graph (WITH router info)
    # -------------------------
    G = nx.Graph()

    for node in nodes:
        G.add_node(node['id'], is_router=node['is_router'])

    for link in links:
        G.add_edge(link['start'], link['end'])

    # -------------------------
    # Compute nodes only
    # -------------------------
    processors = [n['id'] for n in nodes if not n['is_router']]

    # -------------------------
    # K shortest paths
    # -------------------------
    def k_shortest_paths(G, source, target, k):
        return list(islice(nx.shortest_simple_paths(G, source, target), k))

    # -------------------------
    # Path cost = number of routers
    # -------------------------
    def path_cost(G, path):
        return sum(
            1 for node in path if G.nodes[node]['is_router']
        )

    # -------------------------
    # Main computation
    # -------------------------
    result = {}

    for src in processors:
        for dst in processors:

            if src == dst:
                result[(src, dst)] = {
                    "paths": [[src]],
                    "costs": [0]
                }
                continue

            try:
                paths = k_shortest_paths(G, src, dst, k)
                costs = [path_cost(G, p) for p in paths]

                result[(src, dst)] = {
                    "paths": paths,
                    "costs": costs
                }

            except nx.NetworkXNoPath:
                result[(src, dst)] = {
                    "paths": [],
                    "costs": []
                }

    return result


if __name__ == "__main__":
    print(compute_k_paths("../input/CloudModel1.json", k=1))
