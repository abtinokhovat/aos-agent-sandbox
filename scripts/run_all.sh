#!/bin/bash
# Full pipeline: timing matrix -> syscall trace pass -> CSV export. Run on the VM with nohup.
# Trace pass needs root for bpftrace: export SUDO_ASKPASS (and a sudo -A wrapper in PATH) before running.
set -u
cd "$(dirname "$0")/.."
python3 -I scripts/run_matrix.py --all --reps 3
python3 -I scripts/trace_pass.py --all
python3 -I scripts/export_csv.py
echo "run_all done $(date -Is)"
