import glob, re, os, json

RUN_DIR = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/pure_oracle_hint_action_highsuccess100ep_20260812"

stop_re = re.compile(r"\[return\] VLM output: I think I should stop")
arbiter_re = re.compile(r"\[hint_arbiter\] step=(\d+) override=(\w+) reason=(\S+)")
vel_re = re.compile(r"Vel Command: \[([-\d.]+), ([-\d.]+), ([-\d.]+)\], Env Steps to go: (\d+)")

total_return_stop_steps = 0
matched_with_arbiter = 0
reason_counts = {}
mismatch_episodes = []  # STOP proposed but executed action isn't STOP
per_episode = {}

for logf in sorted(glob.glob(f"{RUN_DIR}/ep*_eval.log")):
    ep = re.search(r"ep(\d+)_eval\.log", logf).group(1)
    lines = open(logf, errors="replace").readlines()
    last_arbiter = None  # (step, override, reason)
    for i, line in enumerate(lines):
        m = arbiter_re.search(line)
        if m:
            last_arbiter = (int(m.group(1)), m.group(2), m.group(3))
            continue
        if stop_re.search(line):
            total_return_stop_steps += 1
            per_episode.setdefault(ep, {"stop_steps":0, "matched":0, "mismatch":0})
            per_episode[ep]["stop_steps"] += 1
            # check following line(s) for Vel Command to see executed action
            vel_line = None
            for j in range(i, min(i+3, len(lines))):
                vm = vel_re.search(lines[j])
                if vm:
                    vel_line = vm
                    break
            executed_is_stop = vel_line is not None and float(vel_line.group(4)) == 0 and float(vel_line.group(1))==0 and float(vel_line.group(2))==0 and float(vel_line.group(3))==0
            if last_arbiter is not None:
                matched_with_arbiter += 1
                per_episode[ep]["matched"] += 1
                reason_counts[last_arbiter[2]] = reason_counts.get(last_arbiter[2], 0) + 1
                if not executed_is_stop:
                    mismatch_episodes.append((ep, last_arbiter))
                    per_episode[ep]["mismatch"] += 1
            else:
                # no arbiter line seen yet for this episode/this point
                pass

print(f"Total return-phase STOP-text VLM outputs: {total_return_stop_steps}")
print(f"Of those, immediately preceded by an arbiter decision line: {matched_with_arbiter}")
print(f"Reason code breakdown for those: {reason_counts}")
print(f"\nSTOP proposed but executed Vel Command != [0,0,0]/steps=0: {len(mismatch_episodes)}")
for ep, arb in mismatch_episodes:
    print(f"  ep{ep}: arbiter={arb}")

print(f"\nEpisodes with >=1 return-phase STOP text: {len(per_episode)}")
