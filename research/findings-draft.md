# Findings Draft: Where Does gVisor's Overhead on Coding Agents Come From?

Data: `data/clean/runs.csv` (720 runs) and `data/clean/steps.csv` (47,028 step rows):
40 SWE-bench Verified tasks × 3 agents × 2 runtimes (runc, runsc) × 3 reps. Run
`python3 scripts/analyze_overhead.py` to reproduce every number below. Step-level
numbers are medians over the 3 reps, paired by (task, agent, step) across runtimes.
Timed-out steps are excluded.

## Candidate thesis

> The cost of a strong agent sandbox is set less by *what* the agent works on than
> by *how the agent scaffold issues commands*. Process creation explains most of
> gVisor's added latency. A small fraction of process-heavy steps produces most of
> it, and scaffolds differ several-fold in how often they emit such steps. For an
> interactive agent the user barely notices (~2.5 % end-to-end), but the host pays
> roughly 2× CPU.

## Findings

**F1. Average slowdown is moderate, and the spread is wide.**
- gVisor makes tool execution **1.59×** slower (geometric mean over 120 task-agent pairs). The range is **0.99× to 3.41×**.
- Median by agent: mini-swe-agent 1.37×, SWE-agent 1.50×, OpenHands 1.58×.
- By repo: from pytest 1.20× up to Django 1.94× and xarray 1.96×.
- Container start and teardown are *not* where the cost is: start 329 ms vs 317 ms, teardown 195 ms vs 202 ms.

**F2. Overhead is concentrated in a few steps.**
- The top **1 %** of shell steps contribute **31 %** of all added time, and the top **10 %** contribute **78 %**.
- File edits are actually slightly *faster* under runsc (median −9 ms, 0.89× in total).
- Short commands (< 100 ms on runc) are unaffected (median ratio 0.91).

**F3. Process creation, not native work, predicts the added time.**

Linear fits of added ms per shell step (n = 5,247):

| Predictor(s) | R² |
|---|---|
| native runc latency | 0.26 |
| syscalls (×1000) | 0.53 |
| processes spawned | 0.68 |
| processes + syscalls | **0.84** |

- Fitted cost: about **3.8 ms per process** plus **6.6 ms per 1,000 syscalls**.
- The fit is robust to dropping the 10 largest steps. Processes-only R² then rises to 0.80.
- Steps that spawn ≥ 50 processes are **2.8 %** of steps but cause **45 %** of the added time.
- The extreme case is a family of search steps (OpenHands and SWE-agent on Django) that spawn about 2,750 processes. Each goes from **3.6 s to 17 s** (4.8×), and its CPU time rises from 3.5 s to 30 s.

**F4. Scaffolds differ in how process-heavy their commands are.**

| Agent | Shell steps with ≥ 50 processes | p99 processes per step | Share of the agent's added time from those steps |
|---|---|---|---|
| mini-swe-agent | 1.2 % | 61 | 25 % |
| SWE-agent | 3.8 % | 2,554 | 51 % |
| OpenHands | 4.1 % | 2,363 | 52 % |

All three agents use the same model family on the same tasks, so the difference comes from the scaffolds.

**F5. For an interactive agent, users barely see it.**
- Using the LLM gaps recorded in the original mini-swe-agent trajectories, tool execution is only **6.2 %** of wall time.
- gVisor's end-to-end slowdown is therefore **~1.025×**.
- The overhead matters where LLM time disappears: replay-based evaluation, RL rollouts, and tree search (see the DeltaBox and SpecBox papers).

**F6. The cost moves to the host, and behaviour is unchanged.**
- Median CPU is **1.99×** and peak memory is **1.49×** under runsc.
- Exit-code fidelity is identical on both runtimes: 11,207 / 11,493 matches each. The mismatches come from the environment, not from isolation (see `notes.md`).

## Caveats (must address before writing)

1. **LLM gaps exist only for mini-swe-agent and have 1-second resolution** (minimum 2 s). F5 needs gap data for the other agents, or should be stated for mini-swe-agent only.
2. **CPU and memory accounting under runsc:** check whether the container cgroup includes the Sentry and Gofer. If not, F6 underestimates the cost; if so, it measures something different from runc.
3. **We haven't checked what the 2,750-process steps actually run.** Look up their commands in the trajectories. One process per file (e.g. `find … -exec grep … \;`) is a guess.
4. **One machine** (Haswell i5, `env/mitigations.txt`) and **one gVisor platform.** Per-syscall and per-process costs depend heavily on the platform (systrap vs KVM) and on CPU mitigations.
5. The process count is a PID delta measured on runc. The syscall count for numpy/BLAS tasks is inflated by `sched_yield` spinning (see `notes.md`).
6. Linear R² on heavy-tailed data is fragile. Report it alongside a rank correlation and the leave-top-10-out check.

## What would make this paper-worthy

1. **Explain the mechanism.** Find the commands behind F3/F4 and break a process spawn under runsc into its parts (`fork`/`execve`/`mmap`, Sentry vs Gofer).
2. **Show the insight is actionable (the key experiment).**
   - Rewrite the process-heavy command patterns, e.g. `-exec … \;` → `-exec … +` or `grep -r`, at the scaffold level. Re-measure: does gVisor's overhead collapse toward the 1.2–1.3× of the other steps?
   - Also try `runsc --platform=kvm` (the machine has KVM) to see how much of the per-process cost is platform-dependent.
3. **Generalise.** Add one more agent or model, or a second machine, to show F3 is not specific to this setup.
4. **Release the replay harness and dataset.** A replayable, LLM-free benchmark of real agent trajectories is itself a contribution.
