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
