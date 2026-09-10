import json


def compute_lmin(jobs_data, messages_data, verbose=True):
    job_wcet = {job["id"]: job["wcet_fullspeed"] for job in jobs_data}
    msg_receiver = {msg["id"]: msg["receiver"] for msg in messages_data}

    msgs_sent_by = {}
    for msg in messages_data:
        msgs_sent_by.setdefault(msg["sender"], []).append(msg["id"])

    memo = {}
    memo_path = {}

    def chain_min_time(job_id):
        if job_id in memo:
            return memo[job_id]

        outgoing_msgs = msgs_sent_by.get(job_id, [])
        if not outgoing_msgs:
            memo[job_id] = job_wcet[job_id]
            memo_path[job_id] = []
        else:
            best_mid = max(
                outgoing_msgs,
                key=lambda mid: chain_min_time(msg_receiver[mid])
            )
            best_downstream = chain_min_time(msg_receiver[best_mid])
            memo[job_id] = job_wcet[job_id] + 1 + best_downstream
            memo_path[job_id] = [best_mid] + memo_path[msg_receiver[best_mid]]

        return memo[job_id]

    all_receivers = {msg["receiver"] for msg in messages_data}
    root_jobs = [
        job["id"]
        for job in jobs_data
        if job["id"] not in all_receivers
    ]
    if not root_jobs:
        root_jobs = [job["id"] for job in jobs_data]

    for jid in root_jobs:
        chain_min_time(jid)

    best_root = max(root_jobs, key=lambda jid: memo[jid])
    chain_lb = memo[best_root]
    job_lb = max(job_wcet.values())
    l_min = max(chain_lb, job_lb)

    chain_jobs = [best_root]
    chain_msgs = memo_path[best_root]
    for mid in chain_msgs:
        chain_jobs.append(msg_receiver[mid])

    if verbose:
        print()
        print("=" * 62)
        print("  LONGEST DEPENDENCY CHAIN - l_min calculation")
        print("=" * 62)

        running_total = 0
        for i, job_id in enumerate(chain_jobs):
            wcet = job_wcet[job_id]
            running_total += wcet
            print(f"  Job {job_id:>2}  |  wcet = {wcet:>4}  |  cumulative = {running_total}")

            if i < len(chain_msgs):
                mid = chain_msgs[i]
                running_total += 1
                print("    |")
                print(f"  Msg {mid:>2}  |  tx   = {1:>4}  |  cumulative = {running_total}")
                print("    |")

        print()
        print(f"  Chain jobs   : {chain_jobs}")
        print(f"  Chain msgs   : {chain_msgs}")
        print(f"  Chain l_min  : {chain_lb}")
        print(f"  Single job lb: {job_lb}")
        print(f"  l_min (final): {l_min}")
        print("=" * 62)
        print()

    return l_min


if __name__ == "__main__":
    input_file = "D:\\masters\\project_work\\test_code\\misc\\example_100T_fixed.json" 
    with open(input_file, "r") as f:
        data = json.load(f)

    jobs_data = data["application"]["jobs"]
    messages_data = data["application"]["messages"]

    l_min = compute_lmin(jobs_data, messages_data)
    print(f"l_min = {l_min}")
