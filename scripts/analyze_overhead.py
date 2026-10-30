"""Where does gVisor's overhead come from? Analysis of data/clean/{runs,steps}.csv.

Usage: python3 scripts/analyze_overhead.py [runs.csv] [steps.csv]
Prints the numbers quoted in research/findings-draft.md.
"""
import sys

import numpy as np
import pandas as pd

runs_path = sys.argv[1] if len(sys.argv) > 1 else "data/clean/runs.csv"
steps_path = sys.argv[2] if len(sys.argv) > 2 else "data/clean/steps.csv"
runs = pd.read_csv(runs_path)
steps = pd.read_csv(steps_path)
pd.set_option("display.width", 200)


def section(title):
    print(f"\n=== {title} ===")


# F1: run-level slowdown, median over reps per (task, agent, runtime)
section("F1 run-level slowdown (steps_ms, runsc/runc)")
r = runs.groupby(["task_id", "agent", "runtime"])["steps_ms"].median().unstack()
ratio = (r["runsc"] / r["runc"]).rename("ratio")
print(ratio.groupby("agent").describe()[["50%", "min", "max"]].round(2))
print("geo-mean all:", round(float(np.exp(np.log(ratio).mean())), 2))
by_repo = ratio.reset_index()
by_repo["repo"] = by_repo.task_id.str.split("__").str[0]
print(by_repo.groupby("repo").ratio.median().round(2).sort_values().to_string())
print("start_ms / teardown_ms medians:")
print(runs.groupby("runtime")[["start_ms", "teardown_ms"]].median().round(0))

# Pair each executed step across runtimes (median over reps). Steps that hit the
# replay timeout are dropped: their latency is capped on both runtimes.
timed_out = steps.groupby(["task_id", "agent", "step"]).timed_out.transform("max") > 0
s = steps[(steps.kind != "skip") & ~timed_out]
keys = ["task_id", "agent", "step"]
cols = ["latency_ms", "procs_spawned", "syscalls_total"]
m = s.groupby(keys + ["runtime"])[cols].median().unstack("runtime")
meta = s[s.runtime == "runc"].groupby(keys)[["category", "kind"]].first()
d = pd.DataFrame({
    "lat_c": m["latency_ms"]["runc"],
    "lat_s": m["latency_ms"]["runsc"],
    "procs": m["procs_spawned"]["runc"],
    "sys_s": m["syscalls_total"]["runsc"],
}).join(meta).dropna(subset=["lat_c", "lat_s"])
d["add"] = d.lat_s - d.lat_c

# F2: overhead is concentrated in a few steps
section("F2 concentration of added time (shell steps)")
sh = d[d.kind == "shell"].dropna(subset=["sys_s"]).copy()
pos = sh["add"].clip(lower=0).sort_values(ascending=False)
cum = pos.cumsum() / pos.sum()
for q in (0.01, 0.05, 0.10):
    print(f"top {q:.0%} of steps -> {cum.iloc[int(len(pos) * q)]:.0%} of added time")
print(d.groupby("kind").agg(n=("add", "size"), add_med_ms=("add", "median"),
                            ratio_of_sums=("lat_s", "sum")).assign(
    ratio_of_sums=lambda x: x.ratio_of_sums / d.groupby("kind").lat_c.sum()).round(2))

# F3: process creation + syscalls explain the added time
section("F3 linear model: added_ms ~ procs + k_syscalls")
y = sh["add"].to_numpy()


def fit(features):
    X = np.column_stack([sh[f].to_numpy() for f in features] + [np.ones(len(sh))])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    r2 = 1 - ((y - X @ b) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return np.round(b, 2), round(float(r2), 3)


sh["ksys"] = sh.sys_s / 1e3
for feats in (["lat_c"], ["procs"], ["ksys"], ["procs", "ksys"]):
    print(feats, "coef+intercept", *fit(feats))
hi = sh.procs >= 50
print(f"steps with >=50 processes: {hi.mean():.1%} of steps, "
      f"{sh.loc[hi, 'add'].sum() / sh['add'].sum():.0%} of added time")

# F4: agent scaffolds differ in how process-heavy their commands are
section("F4 per-agent process usage (shell steps)")
for agent, g in sh.groupby("agent"):
    h = g.procs >= 50
    print(f"{agent:15s} share>=50 procs {h.mean():.1%}  "
          f"p99 procs {g.procs.quantile(.99):.0f}  "
          f"added from them {g.loc[h, 'add'].sum() / g['add'].sum():.0%}")

# F5: end-to-end impact vs LLM think time (only mini-swe-agent has gaps)
section("F5 end-to-end slowdown incl. recorded LLM gaps (mini-swe-agent)")
llm = (steps[(steps.runtime == "runc") & (steps.rep == 1)]
       .groupby(["task_id", "agent"]).llm_gap_ms.sum() / 1e3).rename("llm_s")
j = (r / 1e3).join(llm)
j = j[j.llm_s > 0]
e2e = (j.llm_s + j.runsc) / (j.llm_s + j.runc)
print("median tool share of wall time (runc):", round(float((j.runc / (j.llm_s + j.runc)).median()), 3))
print("median end-to-end slowdown:", round(float(e2e.median()), 3))

# F6: resource cost and behavioural fidelity
section("F6 resource cost and fidelity")
rr = runs.groupby(["task_id", "agent", "runtime"])[["cpu_user_ms", "cpu_sys_ms", "mem_peak_mb"]].median().unstack()
cpu = rr["cpu_user_ms"] + rr["cpu_sys_ms"]
print("CPU ratio median:", round(float((cpu["runsc"] / cpu["runc"]).median()), 2))
print("mem_peak ratio median:", round(float((rr["mem_peak_mb"]["runsc"] / rr["mem_peak_mb"]["runc"]).median()), 2))
print(runs.groupby("runtime")[["n_exit_known", "n_exit_match"]].sum())
