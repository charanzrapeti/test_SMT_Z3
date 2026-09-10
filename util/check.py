
# num_nodes = 7
# adj = [[False] * num_nodes for _ in range(num_nodes)]
# print(adj)

# T = 10
# n_msgs = 5
# msg_arrived = [
#         [1 for tf in range(T)]
#         for mid in range(n_msgs)
#     ]

# print(msg_arrived)

import json

input_file = "../input/graph_0.json"
with open(input_file, "r") as f:
    data = json.load(f)

jobs_data       = data["application"]["jobs"]
messages_data   = data["application"]["messages"]
platform_nodes  = data["platform"]["nodes"]

def compute_lmin(messages_data):
    # "Which job receives message mid?"
    msg_receiver = {msg["id"]: msg["receiver"] for msg in messages_data}

    # "Which messages does job j send?"
    msgs_sent_by_job = {}
    for msg in messages_data:
        msgs_sent_by_job.setdefault(msg["sender"], []).append(msg["id"])

    memo = {}
    best_next = {}  # tracks which message leads to the longest chain

    def chain_length(mid):
        if mid in memo:
            return memo[mid]
        receiving_job = msg_receiver[mid]
        outgoing_msgs = msgs_sent_by_job.get(receiving_job, [])
        if not outgoing_msgs:
            memo[mid] = 1
            best_next[mid] = None
        else:
            lengths = {m: chain_length(m) for m in outgoing_msgs}
            best_msg = max(lengths, key=lengths.get)
            memo[mid] = 1 + lengths[best_msg]
            best_next[mid] = best_msg
        return memo[mid]

    if not messages_data:
        return 1, []

    for msg in messages_data:
        chain_length(msg["id"])

    # Find the starting message of the longest chain
    start_mid = max(messages_data, key=lambda m: memo[m["id"]])["id"]

    # Reconstruct the chain
    def reconstruct_chain(mid):
        chain = []
        current = mid
        while current is not None:
            chain.append(current)
            current = best_next[current]
        return chain

    longest_chain = reconstruct_chain(start_mid)
    return memo[start_mid], longest_chain, msg_receiver, msgs_sent_by_job

l_min, longest_chain, msg_receiver, msgs_sent_by_job = compute_lmin(messages_data)

# Build a job lookup for readable output
job_names = {job["id"]: job.get("name", job["id"]) for job in jobs_data}

print(f"Search range: T = {l_min}")
print(f"\nLongest chain (length {l_min}):")
for i, mid in enumerate(longest_chain):
    receiver = msg_receiver[mid]
    receiver_name = job_names.get(receiver, receiver)
    prefix = "   -> " if i > 0 else "Start: "
    print(f"{prefix}Message '{mid}'  -->  Job '{receiver_name}'")