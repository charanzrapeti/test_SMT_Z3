import json
import copy
import re
import random

def fix_can_run_on(input_path, output_path):
    with open(input_path, "r") as f:
        data = json.load(f)

    nodes = data["platform"]["nodes"]

    router_ids = set()
    non_router_ids = set()

    for node in nodes:
        if node["is_router"]:
            router_ids.add(node["id"])
        else:
            non_router_ids.add(node["id"])

    new_data = copy.deepcopy(data)

    for job in new_data["application"]["jobs"]:
        original_list = job["can_run_on"]
        original_size = len(original_list)

        filtered = [nid for nid in original_list if nid not in router_ids]
        removed_count = original_size - len(filtered)

        available_candidates = sorted(list(non_router_ids - set(filtered)))

        if removed_count > len(available_candidates):
            raise ValueError(
                f"Not enough non-router nodes to replace routers in job {job['id']}"
            )

        replacements = random.sample(available_candidates, removed_count)
        final_list = sorted(filtered + replacements)

        if len(final_list) != original_size:
            raise ValueError(
                f"Size mismatch in job {job['id']}"
            )

        job["can_run_on"] = final_list

    # Step 1: dump normally
    json_text = json.dumps(new_data, indent=4)

    # Step 2: compress only can_run_on arrays to single line
    json_text = re.sub(
        r'"can_run_on": \[\s*([\d,\s]+?)\s*\]',
        lambda m: '"can_run_on": [' +
                  ','.join(x.strip() for x in m.group(1).split(',')) +
                  ']',
        json_text
    )

    # Step 3: write to file
    with open(output_path, "w") as f:
        f.write(json_text)

    print(f"Fixed JSON written to {output_path}")


if __name__ == "__main__":
    fix_can_run_on("example_15T.json", "example_15T_fixed.json")