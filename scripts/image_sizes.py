#!/usr/bin/env python3
"""Report compressed size of prebuilt SWE-bench images (Docker Hub) for selected tasks, without pulling."""
import json, urllib.request, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARCH = "x86_64"


def image_name(iid):
    return f"swebench/sweb.eval.{ARCH}.{iid.replace('__', '_1776_').lower()}"


def token(repo):
    u = f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull"
    return json.load(urllib.request.urlopen(u, timeout=30))["token"]


def size(repo, tag="latest"):
    tk = token(repo)
    h = {"Authorization": f"Bearer {tk}", "Accept": "application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.docker.distribution.manifest.v2+json,application/vnd.oci.image.manifest.v1+json"}
    r = urllib.request.urlopen(urllib.request.Request(f"https://registry-1.docker.io/v2/{repo}/manifests/{tag}", headers=h), timeout=30)
    m = json.load(r)
    if "manifests" in m:
        d = next(x["digest"] for x in m["manifests"] if x["platform"]["architecture"] == "amd64")
        h["Accept"] = "application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json"
        m = json.load(urllib.request.urlopen(urllib.request.Request(f"https://registry-1.docker.io/v2/{repo}/manifests/{d}", headers=h), timeout=30))
    return sum(l["size"] for l in m["layers"])


if __name__ == "__main__":
    sel = json.load(open(ROOT / "data" / "selection.json"))
    tot = 0
    for t in sel["tasks"]:
        n = image_name(t["instance_id"])
        try:
            s = size(n); tot += s; print(f"{s/1e9:6.2f} GB  {n}")
        except Exception as e:
            print(f"  FAIL  {n}  {e}")
    print(f"TOTAL compressed: {tot/1e9:.1f} GB")
