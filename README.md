# Agent Sandbox Workload Characterization (Docker vs gVisor)

Replay recorded SWE-bench Verified agent trajectories (no LLM calls) inside
Docker (runc) and gVisor (runsc), collect system-level metrics, export clean CSVs.
Advanced OS course project (Scenario 3, data-centric).

## Layout
- `env/` setup.sh, mitigations.txt, machine info
- `data/` selection.json, raw/ (immutable, gitignored), clean/ (CSVs, gitignored)
- `harness/` trajectory parsers, replay runner, metric collectors
- `scripts/` one-off helpers
- `notes.md` decisions, problems, findings

## Rules
One sandbox at a time, never parallel. One discarded warm-up per (task, runtime).
Alternate runtime order between reps. No mitigation/kernel/network changes without asking.
Target machine: Intel i5 (Haswell), 16 GB, Ubuntu. Keep >= 50 GB disk free.

See `notes.md` for progress. Phases: 0 env check, 1 install, 2 data, 3 replay harness, 4 measurement, 5 export.
