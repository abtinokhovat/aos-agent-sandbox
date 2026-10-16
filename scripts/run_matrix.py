#!/usr/bin/env python3
"""Run the measurement matrix sequentially (never parallel).

For each task: pull image if missing (after a disk check), fetch + parse trajectories, one discarded warm-up
per (task, runtime), then REPS measured runs per (agent, runtime). Runtime order alternates by rep
(odd rep: runc,runsc ; even rep: runsc,runc). Existing raw outputs are skipped (resumable, never overwritten).
Failures are logged to data/raw/failures.log, never silently dropped.

  run_matrix.py --tasks django__django-11099 [--reps 3] [--agents a,b] [--runtimes runc,runsc]
  run_matrix.py --all --reps 3
"""
import argparse, fcntl, json, os, shutil, subprocess, sys, time, urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
B = "https://swe-bench-submissions.s3.amazonaws.com"
SEL = json.load(open(os.path.join(ROOT, "data/selection.json")))
AGENT_SRC = {  # agent -> (s3 path template, local filename template, persist_cwd)
    "mini-swe-agent": ("{p}/trajs/{t}/{t}.traj.json", "{t}.traj.json", False),
    "openhands": ("{p}/trajs/{t}.json", "{t}.json", True),
    "sweagent": ("{p}/trajs/{t}/{t}.traj", "{t}.traj", True),
}
UTF8 = {"mini-swe-agent": False, "openhands": True, "sweagent": True}
MIN_FREE_GB = 50
ESTIMATE_IMAGE_GB = 8  # uncompressed headroom per image


def image_of(task):
    return "swebench/sweb.eval.x86_64." + task.replace("__", "_1776_").lower()


def log_fail(msg):
    with open(os.path.join(ROOT, "data/raw/failures.log"), "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}\n")
    print("FAIL:", msg, file=sys.stderr)


def free_gb():
    return shutil.disk_usage("/").free / 1e9


def ensure_image(task):
    img = image_of(task)
    if subprocess.run(["docker", "image", "inspect", img], capture_output=True).returncode == 0:
        return True
    if free_gb() - ESTIMATE_IMAGE_GB < MIN_FREE_GB:
        log_fail(f"{task}: skipped pull, only {free_gb():.0f} GB free (floor {MIN_FREE_GB} GB)")
        return False
    r = subprocess.run(["docker", "pull", "-q", img + ":latest"], capture_output=True, text=True)
    if r.returncode != 0:
        log_fail(f"{task}: docker pull failed: {r.stderr.strip()[:300]}")
        return False
    return True


def ensure_steps(task, agent):
    out = os.path.join(ROOT, f"data/raw/steps/{task}.{agent}.jsonl")
    if os.path.exists(out):
        return out
    tmpl, fn, _ = AGENT_SRC[agent]
    local = os.path.join(ROOT, "data/raw/trajs", agent, fn.format(t=task))
    if not os.path.exists(local):
        os.makedirs(os.path.dirname(local), exist_ok=True)
        url = f"{B}/" + tmpl.format(p=SEL["agents"][agent], t=task)
        try:
            urllib.request.urlretrieve(url, local)
        except Exception as e:
            log_fail(f"{task}/{agent}: trajectory download failed: {e}")
            return None
    r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "harness/parsers.py"), agent, local], capture_output=True, text=True)
    if r.returncode != 0:
        log_fail(f"{task}/{agent}: parse failed: {r.stderr.strip()[-300:]}")
        return None
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w").write(r.stdout)
    return out


def replay(task, agent, runtime, rep, steps, out, warmup):
    if os.path.exists(out):
        return True
    cmd = [os.path.join(ROOT, "bin/replay"), "-image", image_of(task), "-runtime", runtime, "-steps", steps, "-out", out,
           "-task", task, "-agent", agent, "-rep", str(rep), "-editor", os.path.join(ROOT, "harness/replay/editor.py")]
    if warmup:
        cmd.append("-warmup")
    if AGENT_SRC[agent][2]:
        cmd.append("-persist-cwd")
    if not UTF8[agent]:
        cmd.append("-utf8=false")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log_fail(f"{task}/{agent}/{runtime}/rep{rep}{' warmup' if warmup else ''}: {r.stderr.strip()[-300:]}")
        return False
    print(r.stdout.strip())
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--agents", default=",".join(AGENT_SRC))
    ap.add_argument("--runtimes", default="runc,runsc")
    a = ap.parse_args()
    tasks = [t["instance_id"] for t in SEL["tasks"]] if a.all else a.tasks.split(",")
    agents, rts = a.agents.split(","), a.runtimes.split(",")

    lock = open(os.path.join(ROOT, "data/raw/.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("another run_matrix is active; measurements must never run in parallel")

    for task in tasks:
        if not ensure_image(task):
            continue
        steps = {ag: ensure_steps(task, ag) for ag in agents}
        ok_agents = [ag for ag in agents if steps[ag]]
        if not ok_agents:
            continue
        d = os.path.join(ROOT, "data/raw/runs", task)
        for rt in rts:  # one discarded warm-up per (task, runtime), using the first agent's trajectory
            replay(task, ok_agents[0], rt, 0, steps[ok_agents[0]], f"{d}/warmup.{rt}.json", True)
        for ag in ok_agents:
            for rep in range(1, a.reps + 1):
                order = rts if rep % 2 == 1 else rts[::-1]
                for rt in order:
                    replay(task, ag, rt, rep, steps[ag], f"{d}/{ag}.{rt}.rep{rep}.json", False)


if __name__ == "__main__":
    main()
