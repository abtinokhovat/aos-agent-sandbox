#!/usr/bin/env python3
"""Syscall-count pass (separate from timing runs so tracing never perturbs latency).

  runc : bpftrace (harness/syscalls.bt), cgroup-scoped, root via SUDO_ASKPASS. Counts guest==host syscalls.
  runsc: runtime "runsc-strace" (runsc --strace --debug-log=/var/log/runsc-strace/). Counts syscalls as the
         gVisor Sentry sees them (application syscalls), parsed from the boot log's strace "E" (entry) lines.
Both delimit a step by marker-file creations made by the replay (-trace-marks); a few constant syscalls from the
marker/redirect themselves fall inside each window (same on both runtimes).

Output: data/raw/syscalls/<task>/<agent>.<runtime>.json  {method, per_step: {step: {name: n}}, per_step_total}
  trace_pass.py --tasks T1,T2 [--agents a,b] [--runtimes runc,runsc]
"""
import argparse, glob, gzip, json, os, re, shutil, signal, subprocess, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import run_matrix as rm  # noqa: E402

STRACE_DIR = "/var/log/runsc-strace"


def syscall_names():
    names = {}
    for p in ("/usr/include/x86_64-linux-gnu/asm/unistd_64.h", "/usr/include/asm/unistd_64.h"):
        if os.path.exists(p):
            for m in re.finditer(r"#define __NR_(\w+)\s+(\d+)", open(p).read()):
                names[int(m.group(2))] = m.group(1)
            break
    return names


def parse_bpftrace(path, names):
    per, cur = {}, None
    for ln in open(path):
        m = re.match(r"END /tmp/\.aos_mark_e_(\d+)", ln)
        if m:
            cur = int(m.group(1)); per[cur] = {}; continue
        m = re.match(r"@c\[(\d+)\]: (\d+)", ln)
        if m and cur is not None:
            per[cur][names.get(int(m.group(1)), "nr_" + m.group(1))] = int(m.group(2))
    return per


def parse_runsc(path):
    per, cur = {}, None
    start = re.compile(r"\] \[\s*\d+:\s*\d+\] \S+ E openat\(.*?/tmp/\.aos_mark_s_(\d+),")
    end = re.compile(r"\] \[\s*\d+:\s*\d+\] \S+ E openat\(.*?/tmp/\.aos_mark_e_(\d+),")
    call = re.compile(r"\] \[\s*\d+:\s*\d+\] \S+ E (\w+)\(")
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", errors="replace") as f:
        for ln in f:
            if "strace.go" not in ln:
                continue
            m = start.search(ln)
            if m:
                cur = int(m.group(1)); per[cur] = {}; continue
            if cur is None:
                continue
            if end.search(ln):
                cur = None; continue
            m = call.search(ln)
            if m:
                per[cur][m.group(1)] = per[cur].get(m.group(1), 0) + 1
    return per


def save(task, agent, runtime, method, per):
    d = os.path.join(ROOT, "data/raw/syscalls", task)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f"{agent}.{runtime}.json")
    json.dump({"task": task, "agent": agent, "runtime": runtime, "method": method, "per_step": per,
               "per_step_total": {str(k): sum(v.values()) for k, v in per.items()}}, open(out, "w"), indent=1)
    return out


def replay_trace(task, agent, runtime_docker, label, steps, out):
    cmd = [os.path.join(ROOT, "bin/replay"), "-image", rm.image_of(task), "-runtime", runtime_docker, "-label", label,
           "-steps", steps, "-out", out, "-task", task, "-agent", agent, "-rep", "0", "-trace-marks",
           "-editor", os.path.join(ROOT, "harness/replay/editor.py")]
    if rm.AGENT_SRC[agent][2]:
        cmd.append("-persist-cwd")
    if not rm.UTF8[agent]:
        cmd.append("-utf8=false")
    return subprocess.run(cmd, capture_output=True, text=True)


def sudo(*a, **kw):
    return subprocess.run(["sudo", "-A", *a], **kw)


def trace_runc(task, agent, steps, names):
    out = os.path.join(ROOT, f"data/raw/trace_runs/{task}/{agent}.runc.json")
    if os.path.exists(out):
        os.remove(out)  # trace-run timing files are scratch (tracing perturbs timing); not measurement data
    bt_out = f"/tmp/bt_{os.getpid()}.txt"
    btf = open(bt_out, "w")
    p = subprocess.Popen(["sudo", "-A", "bpftrace", os.path.join(ROOT, "harness/syscalls.bt")],
                         stdout=btf, stderr=subprocess.PIPE, text=True)
    time.sleep(6)  # attach
    if p.poll() is not None:
        raise RuntimeError("bpftrace exited: " + p.stderr.read()[-300:])
    r = replay_trace(task, agent, "runc", "runc", steps, out)
    time.sleep(1)
    sudo("pkill", "-INT", "-x", "bpftrace")
    try:
        p.wait(timeout=20)
    except subprocess.TimeoutExpired:
        sudo("pkill", "-KILL", "-x", "bpftrace")
    if r.returncode != 0:
        raise RuntimeError("replay failed: " + r.stderr[-300:])
    btf.close()
    return parse_bpftrace(bt_out, names)


def trace_runsc(task, agent, steps):
    before = set(glob.glob(f"{STRACE_DIR}/*.boot.txt"))
    out = os.path.join(ROOT, f"data/raw/trace_runs/{task}/{agent}.runsc.json")
    if os.path.exists(out):
        os.remove(out)
    r = replay_trace(task, agent, "runsc-strace", "runsc", steps, out)
    if r.returncode != 0:
        raise RuntimeError("replay failed: " + r.stderr[-300:])
    new = sorted(set(glob.glob(f"{STRACE_DIR}/*.boot.txt")) - before, key=os.path.getsize)
    if not new:
        raise RuntimeError("no new runsc boot log")
    per = parse_runsc(new[-1])
    keep = os.path.join(ROOT, f"data/raw/strace_logs/{task}")
    os.makedirs(keep, exist_ok=True)
    with open(new[-1], "rb") as f, gzip.open(os.path.join(keep, f"{agent}.runsc.boot.txt.gz"), "wb") as g:
        shutil.copyfileobj(f, g)
    return per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--agents", default=",".join(rm.AGENT_SRC))
    ap.add_argument("--runtimes", default="runc,runsc")
    a = ap.parse_args()
    tasks = [t["instance_id"] for t in rm.SEL["tasks"]] if a.all else a.tasks.split(",")
    names = syscall_names()
    import fcntl
    lock = open(os.path.join(ROOT, "data/raw/.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("another measurement process is active")
    for task in tasks:
        if not rm.ensure_image(task):
            continue
        for ag in a.agents.split(","):
            steps = rm.ensure_steps(task, ag)
            if not steps:
                continue
            for rt in a.runtimes.split(","):
                dst = os.path.join(ROOT, f"data/raw/syscalls/{task}/{ag}.{rt}.json")
                if os.path.exists(dst):
                    continue
                try:
                    if rt == "runc":
                        per = trace_runc(task, ag, steps, names); method = "bpftrace raw_syscalls:sys_enter, cgroup-scoped, marker-delimited"
                    else:
                        per = trace_runsc(task, ag, steps); method = "runsc --strace debug log (Sentry-side application syscalls), marker-delimited"
                    save(task, ag, rt, method, per)
                    print(task, ag, rt, "steps traced:", len(per), "total syscalls:", sum(sum(v.values()) for v in per.values()))
                except Exception as e:
                    rm.log_fail(f"trace {task}/{ag}/{rt}: {e}")


if __name__ == "__main__":
    main()
