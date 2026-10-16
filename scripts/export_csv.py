#!/usr/bin/env python3
"""Raw run JSONs (data/raw/runs/**) -> data/clean/steps.csv and runs.csv. Never edits raw files.
Warm-up runs are excluded. syscalls_total is filled from data/raw/syscalls/<run>.json when present."""
import csv, glob, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness"))
from categorize import categorize  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
STEPS = ["task_id", "agent", "runtime", "rep", "step", "category", "latency_ms", "cpu_user_ms", "cpu_sys_ms", "mem_peak_mb",
         "io_read_bytes", "io_write_bytes", "syscalls_total", "exit_code", "fidelity_ok",
         "kind", "inner_ms", "mem_current_mb", "io_read_ops", "io_write_ops", "procs_spawned", "out_match", "timed_out", "llm_gap_ms"]
RUNS = ["task_id", "agent", "runtime", "rep", "kernel", "started_at", "start_ms", "steps_ms", "teardown_ms", "total_ms",
        "n_steps", "n_executed", "n_exit_known", "n_exit_match", "fidelity_rate", "cpu_user_ms", "cpu_sys_ms", "io_read_bytes", "io_write_bytes", "mem_peak_mb"]


def b(v):
    return "" if v is None else int(bool(v))


def main():
    files = sorted(glob.glob(os.path.join(ROOT, "data/raw/runs/**/*.json"), recursive=True))
    os.makedirs(os.path.join(ROOT, "data/clean"), exist_ok=True)
    sw = csv.DictWriter(open(os.path.join(ROOT, "data/clean/steps.csv"), "w", newline=""), STEPS)
    rw = csv.DictWriter(open(os.path.join(ROOT, "data/clean/runs.csv"), "w", newline=""), RUNS)
    sw.writeheader(); rw.writeheader()
    nr = 0
    for f in files:
        r = json.load(open(f))
        if r.get("Warmup"):
            continue
        sysc = {}
        # syscall counts come from one separate trace pass per (task, agent, runtime), applied to all reps
        sp = os.path.join(ROOT, "data/raw/syscalls", r["Task"], f"{r['Agent']}.{r['Runtime']}.json")
        if os.path.exists(sp):
            sysc = {int(k): v for k, v in json.load(open(sp)).get("per_step_total", {}).items()}
        ex = [s for s in r["Steps"] if s["executed"]]
        known = [s for s in ex if s["exit_match"] is not None]
        for s in r["Steps"]:
            cmd = s.get("command") or ""
            ed = {"command": cmd.split(":", 1)[1].split(" ")[0]} if cmd.startswith("edit:") else None
            sw.writerow(dict(
                task_id=r["Task"], agent=r["Agent"], runtime=r["Runtime"], rep=r["Rep"], step=s["step"],
                category=categorize(s["kind"], cmd, ed) if s["executed"] else "skipped",
                latency_ms=round(s["latency_ms"], 3), cpu_user_ms=round(s["cpu_user_ms"], 3), cpu_sys_ms=round(s["cpu_sys_ms"], 3),
                mem_peak_mb=round(s["mem_peak_mb"], 3), io_read_bytes=s["io_read_bytes"], io_write_bytes=s["io_write_bytes"],
                syscalls_total=sysc.get(s["step"], ""), exit_code=s["exit_code"], fidelity_ok=b(s["exit_match"]),
                kind=s["kind"], inner_ms=round(s["inner_ms"], 3), mem_current_mb=round(s["mem_current_mb"], 3),
                io_read_ops=s["io_read_ops"], io_write_ops=s["io_write_ops"], procs_spawned=s["procs_spawned"],
                out_match=b(s["out_match"]), timed_out=int(s["timed_out"]), llm_gap_ms=s["llm_gap_ms"] if s["llm_gap_ms"] is not None else ""))
        rw.writerow(dict(
            task_id=r["Task"], agent=r["Agent"], runtime=r["Runtime"], rep=r["Rep"], kernel=r["Kernel"], started_at=r["StartedAt"],
            start_ms=round(r["StartMs"], 3), steps_ms=round(r["StepsMs"], 3), teardown_ms=round(r["TeardownMs"], 3), total_ms=round(r["TotalMs"], 3),
            n_steps=len(r["Steps"]), n_executed=len(ex), n_exit_known=len(known), n_exit_match=sum(1 for s in known if s["exit_match"]),
            fidelity_rate=round(sum(1 for s in known if s["exit_match"]) / len(known), 4) if known else "",
            cpu_user_ms=round(sum(s["cpu_user_ms"] for s in ex), 3), cpu_sys_ms=round(sum(s["cpu_sys_ms"] for s in ex), 3),
            io_read_bytes=sum(s["io_read_bytes"] for s in ex), io_write_bytes=sum(s["io_write_bytes"] for s in ex),
            mem_peak_mb=round(max((s["mem_peak_mb"] for s in ex), default=0), 3)))
        nr += 1
    print(f"exported {nr} runs from {len(files)} files")


if __name__ == "__main__":
    main()
