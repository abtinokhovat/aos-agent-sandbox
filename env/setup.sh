#!/usr/bin/env bash
# Rebuild the measurement machine (Ubuntu 24.04, x86_64). Idempotent. Run as a sudo-capable user.
set -euo pipefail

# --- DNS fix needed on the original box: router DNS cannot serve DNSSEC data, and the
# --- global Iranian upstreams (178.22.122.100, 185.51.200.2) returned SERVFAIL.
# sudo sed -i 's/^#\?DNSSEC=.*/DNSSEC=no/' /etc/systemd/resolved.conf
# sudo sed -i 's/^DNS=178.22.122.100 185.51.200.2/#DNS=/' /etc/systemd/resolved.conf
# sudo systemctl restart systemd-resolved

sudo apt-get update
sudo apt-get install -y \
  ca-certificates curl gnupg git jq \
  strace sysstat bpftrace \
  linux-tools-common "linux-tools-$(uname -r)" \
  golang-go python3 python3-venv python3-pip

# Docker Engine (docker-ce + containerd.io) was preinstalled; if missing, install per docs.docker.com/engine/install/ubuntu
# (do NOT apt install docker.io: it conflicts with containerd.io).

# --- gVisor (runsc), registered as Docker runtime; default platform is systrap.
# Official release: release-20261005.0 (tarball sha256 bd4eb2ca0ee74f0fbbb5f5273ba011e79c56a29fbb047393b88b981cd3230ede).
# On the original box storage.googleapis.com was blocked (403) from the VM, so the tarball was
# downloaded on another machine and scp'd to GVISOR_TARBALL_DIR (extracted: runsc, containerd-shim-runsc-v1, gvisor-bin/).
# URL: https://storage.googleapis.com/gvisor/releases/release/20261005.0/x86_64/gvisor.tar.bz2
GVISOR_DIR="${GVISOR_DIR:-/tmp/gv}"
if [ ! -d "$GVISOR_DIR" ]; then
  curl -fsSL -o /tmp/gvisor.tar.bz2 https://storage.googleapis.com/gvisor/releases/release/20261005.0/x86_64/gvisor.tar.bz2
  mkdir -p "$GVISOR_DIR" && tar xjf /tmp/gvisor.tar.bz2 -C "$GVISOR_DIR"
fi
sudo install -m 755 "$GVISOR_DIR/runsc" "$GVISOR_DIR/containerd-shim-runsc-v1" /usr/local/bin/
sudo mkdir -p /usr/local/bin/gvisor-bin && sudo install -m 755 "$GVISOR_DIR"/gvisor-bin/* /usr/local/bin/gvisor-bin/
sudo /usr/local/bin/runsc install   # adds "runsc" runtime to /etc/docker/daemon.json
sudo systemctl restart docker

# --- checks
stat -fc %T /sys/fs/cgroup | grep -q cgroup2fs && echo "cgroup v2: OK"
docker run --rm --runtime=runc  hello-world >/dev/null && echo "runc: OK"
docker run --rm --runtime=runsc hello-world >/dev/null && echo "runsc: OK"
go version; python3 --version; runsc --version | head -1
