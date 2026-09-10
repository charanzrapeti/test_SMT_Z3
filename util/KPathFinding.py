# KPathFinding.py

def compute_min_path_costs(json_file, k=2):
    import json
    import networkx as nx
    from itertools import islice

    with open(json_file, "r") as f:
        json_data = json.load(f)

    nodes = json_data['platform']['nodes']
    links = json_data['platform']['links']

    G = nx.Graph()

    for node in nodes:
        G.add_node(node['id'], is_router=node['is_router'])

    for link in links:
        G.add_edge(link['start'], link['end'])

    processor_nodes = [node['id'] for node in nodes if not node['is_router']]

    def k_shortest_paths(G, source, target, k):
        return list(islice(nx.shortest_simple_paths(G, source, target), k))

    def path_cost(G, path):
        return sum(1 for i in range(1, len(path)) if G.nodes[path[i]]['is_router'])

    min_cost_dict = {}

    for i in range(len(processor_nodes)):
        for j in range(len(processor_nodes)):
            src = processor_nodes[i]
            dst = processor_nodes[j]

            if src == dst:
                min_cost_dict[(src, dst)] = [0]* k
                continue

            paths = k_shortest_paths(G, src, dst, k)
            costs = [path_cost(G, p) for p in paths]
            min_cost_dict[(src, dst)] = costs

        
    

    return min_cost_dict
    


print(compute_min_path_costs("../input/example_30T_fixed.json", k=2))