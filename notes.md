# Notes

## Status
- [ ] Phase 0: environment check (must run on the Ubuntu box)
- [ ] Phase 1: install
- [ ] Phase 2: data
- [ ] Phase 3: replay harness
- [ ] Phase 4: measurement
- [ ] Phase 5: export

## Decisions / problems
- Repo scaffolded from macOS dev machine; all measurements run on the Ubuntu machine.

## Phase 0 (2026-10-16, home_local)
- Ubuntu 24.04.2, kernel 6.8.0-60, i5-4460 4c, 15 GiB, 413 GB free, cgroup v2, KVM present. See env/machine_info.txt, env/mitigations.txt.
- Docker 28.0.2 preinstalled (runc only). runsc and Go missing.
- **BLOCKER: DNS broken.** IP works (ping 8.8.8.8 ok), but resolver upstreams (178.22.122.100, 185.51.200.2 global; 192.168.31.1 on wifi) return "server misbehaving". GitHub/HF/PyPI/Docker Hub unresolvable. Waiting on user decision: mirror/proxy/DNS change.

## Phase 0/1 update (2026-10-16)
- DNS fixed: removed global DNS= servers and set DNSSEC=no in /etc/systemd/resolved.conf (backup .bak on VM). GitHub/HF/PyPI/Docker Hub now reachable from VM.
- storage.googleapis.com is 403 from the VM; official gVisor tarball (release-20261005.0) fetched on the Mac and scp'd. runc + runsc both run hello-world.
- Docker preinstalled is docker-ce+containerd.io; do not apt install docker.io (conflicts).

## Phase 2 (2026-10-16)
- Agents (all Claude Sonnet family, different scaffolds): mini-swe-agent v1.13.3 (bash-only, sonnet-4-5 label, model claude-sonnet-4-20250514 in sample), OpenHands (20250524, claude-4-sonnet), SWE-agent (20250522, claude-4-sonnet).
- Trajectories are NOT in git; they live in public S3: https://swe-bench-submissions.s3.amazonaws.com/{bash-only|verified}/<submission>/trajs/ (listing + GET work from the VM).
- All 500 Verified tasks attempted by all three. 40 selected with seed 20261016 (data/selection.json via scripts/select_tasks.py).
- Images: swebench/sweb.eval.x86_64.<owner>_1776_<repo>-<n>; ~55 GB compressed for the 40 (scripts/image_sizes.py). sympy-22914 size lookup failed transiently.
- Path differences to remap in replay: mini=/testbed, OpenHands=/workspace/<repo>__<ver>, SWE-agent=TBD.

## Phase 3/4 pilot (django__django-11099, 1 rep, both runtimes, 3 agents) 2026-10-16
- Harness: harness/parsers.py (trajectory -> steps.jsonl), harness/replay (Go: container lifecycle + per-step cgroup metrics),
  harness/replay/editor.py (in-container str_replace_editor replacement), harness/categorize.py, scripts/run_matrix.py, scripts/export_csv.py.
- Each step = one `docker exec ... bash -c`. cwd carried between steps only for OpenHands/SWE-agent (persistent shells); mini-swe-agent runs each command fresh.
  Shell `export`s do not persist across steps (known limitation).
- conda `testbed` env: captured once from a login shell and passed via `-e` (a per-step `bash -lc` cost ~110 ms CPU, swamping small steps).
- Env set to match originals: PAGER=cat MANPAGER=cat LESS=-R PIP_PROGRESS_BAR=off TQDM_DISABLE=1; UTF-8 locale ON for openhands/sweagent, OFF for mini
  (original mini run had no UTF-8 locale: a script printing non-ASCII exited 1; verified exit-code match only with locale off).
- Fidelity: fidelity_ok = replay exit code == original exit code (known for mini and OpenHands shell steps only; SWE-agent records none -> blank).
  Output hash match kept separately (out_match): differs legitimately when the original output was truncated by the scaffold or depends on CPU count
  (e.g. Django runtests "up to 8 processes" vs 4).
- Metrics notes: memory.peak is cumulative since container start (kernel 6.8 cannot reset it per step). io.stat read bytes are ~0 (page cache);
  under gVisor io.stat reflects gofer/host I/O. Processes spawned = PID delta of a subshell before/after the step (-1 for the marker);
  /proc/loadavg last-pid is empty under gVisor so it was not used.
- docker cp does not reach a gVisor sandbox rootfs; files are installed via `docker exec -i ... cat >`.
- Pilot timing (steps): mini runc 5.9s / runsc 8.9s; openhands 8.2 / 20.8; sweagent 11.5 / 26.5.
- TODO: syscall counting pass (runc: bpftrace by cgroup; runsc: strace via runtimeArgs or runsc metrics), then full 40-task run.
