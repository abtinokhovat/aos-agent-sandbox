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
