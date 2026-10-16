#!/usr/bin/env python3
"""Select SWE-bench Verified tasks attempted by all chosen agents. Deterministic (seeded).

Writes data/selection.json. Needs: pyarrow (pip install pyarrow). Run on the measurement box.
"""
import json, random, re, sys, urllib.request, pathlib

SEED = 20261016
N_TASKS = 40
B = "https://swe-bench-submissions.s3.amazonaws.com"
HF = "https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified/resolve/main/data/test-00000-of-00001.parquet"
AGENTS = {
    "mini-swe-agent": "bash-only/20250929_mini-v1.13.3_sonnet-4-5-20250929",
    "openhands": "verified/20250524_openhands_claude_4_sonnet",
    "sweagent": "verified/20250522_sweagent_claude-4-sonnet-20250514",
}
ROOT = pathlib.Path(__file__).resolve().parent.parent


def list_instances(prefix):
    ids, token = set(), None
    while True:
        url = f"{B}/?list-type=2&prefix={prefix}/trajs/&max-keys=1000"
        if token:
            url += "&continuation-token=" + urllib.parse.quote(token, safe="")
        x = urllib.request.urlopen(url, timeout=60).read().decode()
        for k in re.findall(r"<Key>([^<]*)</Key>", x):
            m = re.search(r"/trajs/(?:([^/]+)/)?([^/]+?)(?:\.traj(?:\.json)?|\.json)$", k)
            if m:
                ids.add(m.group(2).split(".")[0] if "/" not in k.split("/trajs/")[1] else m.group(1))
        nt = re.search(r"<NextContinuationToken>([^<]*)</NextContinuationToken>", x)
        if not nt:
            return ids
        token = nt.group(1)


def main():
    import urllib.parse  # noqa
    import pyarrow.parquet as pq
    data = ROOT / "data" / "raw" / "swebench_verified.parquet"
    data.parent.mkdir(parents=True, exist_ok=True)
    if not data.exists():
        urllib.request.urlretrieve(HF, data)
    tbl = pq.read_table(data, columns=["instance_id", "repo", "version"]).to_pylist()
    verified = {r["instance_id"]: r for r in tbl}
    per_agent = {a: list_instances(p) & verified.keys() for a, p in AGENTS.items()}
    common = sorted(set.intersection(*per_agent.values()))
    rng = random.Random(SEED)
    chosen = sorted(rng.sample(common, min(N_TASKS, len(common))))
    out = {
        "seed": SEED, "n_requested": N_TASKS, "agents": AGENTS,
        "verified_total": len(verified),
        "attempted_per_agent": {a: len(s) for a, s in per_agent.items()},
        "attempted_by_all": len(common),
        "tasks": [{"instance_id": i, "repo": verified[i]["repo"], "version": verified[i]["version"]} for i in chosen],
    }
    (ROOT / "data" / "selection.json").write_text(json.dumps(out, indent=2) + "\n")
    print({k: v for k, v in out.items() if k != "tasks"}, len(chosen))


if __name__ == "__main__":
    import urllib.parse
    main()
