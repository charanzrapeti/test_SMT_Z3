import json


def convert_platform(json_path):
    """
    Load a platform JSON file, convert node IDs to sequential
    integers, and return the converted platform dictionary.

    Args:
        json_path: Path to the input .json file

    Returns:
        {
            "nodes": [...],
            "links": [...]
        }
    """

    # Load JSON file
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Get platform from JSON
    platform = data["platform"]

    # --------------------------------------------------
    # Create ID mapping
    #
    # Example:
    # P1001 -> 1
    # P1002 -> 2
    # ...
    # R101  -> 26
    # ...
    # RID1  -> 51
    # --------------------------------------------------

    id_mapping = {}

    for new_id, node in enumerate(platform["nodes"], start=1):
        old_id = node["id"]
        id_mapping[old_id] = new_id

    # --------------------------------------------------
    # Convert nodes
    # --------------------------------------------------

    nodes = []

    for node in platform["nodes"]:
        nodes.append({
            "id": id_mapping[node["id"]],
            "is_router": node["is_router"]
        })

    # --------------------------------------------------
    # Convert links
    # --------------------------------------------------

    links = []

    for link in platform["links"]:
        links.append({
            "start": id_mapping[link["start"]],
            "end": id_mapping[link["end"]]
        })

    # --------------------------------------------------
    # Return Python object
    # --------------------------------------------------

    return {
        "nodes": nodes,
        "links": links
    }

print(convert_platform("./platform/cloudModel1.json"))