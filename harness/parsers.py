#!/usr/bin/env python3
"""Normalize agent trajectories into a common step list.

Step: {step, kind, command, edit, orig_exit, orig_out_sha, llm_gap_ms, src_index}
  kind: "shell"  -> run `command` (bash) in the container
        "edit"   -> run file-edit `edit` = {op, path, ...} via the in-container editor (see editor.py)
        "skip"   -> LLM-only / terminal turn (think, finish, submit); recorded, not executed

Usage: parsers.py <agent> <traj_file> > steps.jsonl
Agents: mini-swe-agent | openhands | sweagent
"""
import hashlib
import json
import re
import shlex
import sys

# Repo location inside the SWE-bench image is /testbed. Other scaffolds used other paths.
OH_REPO_RE = re.compile(r"/workspace/[A-Za-z0-9_.\-]+__[A-Za-z0-9_.\-]+__[0-9.]+")


def out_sha(s):
    """Hash of output with line endings / trailing whitespace normalized."""
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n").rstrip()
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()


def remap(s):
    return OH_REPO_RE.sub("/testbed", s) if isinstance(s, str) else s


def _text(content):
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") for p in content or [] if isinstance(p, dict))


# ---------------------------------------------------------------- mini-swe-agent
def parse_mini(path):
    d = json.load(open(path))
    msgs = d["messages"]
    steps, last_created = [], None
    for i, m in enumerate(msgs):
        if m["role"] != "assistant":
            continue
        text = _text(m["content"])
        blocks = re.findall(r"```bash\s*\n(.*?)```", text, re.S)
        created = (m.get("extra", {}).get("response", {}) or {}).get("created")
        gap = None
        if created is not None and last_created is not None:
            gap = max(0, int((created - last_created) * 1000))
        if created is not None:
            last_created = created
        if not blocks:
            steps.append(dict(kind="skip", command=None, orig_exit=None, orig_out=None, gap=gap, idx=i))
            continue
        obs = _text(msgs[i + 1]["content"]) if i + 1 < len(msgs) else ""
        rc = re.search(r"<returncode>(-?\d+)</returncode>", obs)
        out = re.search(r"<output>\n?(.*)</output>", obs, re.S)
        truncated = "<warning>\nThe output of your last command was too long" in obs
        steps.append(dict(kind="shell", command=blocks[0].strip("\n"), orig_exit=int(rc.group(1)) if rc else None,
                          orig_out=None if truncated else (out.group(1) if out else obs), gap=gap, idx=i))
    return steps


# ---------------------------------------------------------------- OpenHands
def parse_openhands(path):
    h = json.load(open(path))
    steps = []
    results = {e.get("tool_call_id"): e for e in h if e.get("role") == "tool"}
    for i, e in enumerate(h):
        if e.get("role") != "assistant":
            continue
        for tc in e.get("tool_calls") or []:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except Exception:
                args = {}
            res = results.get(tc["id"])
            obs = _text(res["content"]) if res else ""
            if name == "execute_bash":
                m = re.search(r"\[Command finished with exit code (-?\d+)\]", obs)
                body = re.split(r"\n\[The command (?:completed|has no new output)", obs)[0]
                steps.append(dict(kind="shell", command=remap(args.get("command", "")), orig_exit=int(m.group(1)) if m else None,
                                  orig_out=body, gap=None, idx=i, is_input=bool(args.get("is_input"))))
            elif name == "str_replace_editor":
                ed = {k: remap(v) for k, v in args.items()}
                steps.append(dict(kind="edit", edit=ed, orig_exit=None, orig_out=obs, gap=None, idx=i))
            else:  # think, finish, ...
                steps.append(dict(kind="skip", command=None, orig_exit=None, orig_out=None, gap=None, idx=i, tool=name))
    return steps


# ---------------------------------------------------------------- SWE-agent
def _parse_editor_action(action):
    argv = shlex.split(action)
    cmd, path = argv[1], argv[2]
    ed = {"command": cmd, "path": path}
    flags = {"--file_text": "file_text", "--old_str": "old_str", "--new_str": "new_str",
             "--insert_line": "insert_line"}
    i = 3
    while i < len(argv):
        a = argv[i]
        if a in flags:
            v = argv[i + 1] if i + 1 < len(argv) else ""
            ed[flags[a]] = int(v) if a == "--insert_line" else v
            i += 2
        elif a == "--view_range":
            ed["view_range"] = [int(argv[i + 1]), int(argv[i + 2])]
            i += 3
        else:
            i += 1
    return ed


def parse_sweagent(path):
    t = json.load(open(path))["trajectory"]
    steps = []
    for i, s in enumerate(t):
        a = s["action"].strip()
        if a == "submit" or not a:
            steps.append(dict(kind="skip", command=None, orig_exit=None, orig_out=s.get("observation"), gap=None, idx=i, tool="submit"))
        elif a.startswith("str_replace_editor "):
            steps.append(dict(kind="edit", edit=_parse_editor_action(a), orig_exit=None, orig_out=s.get("observation"), gap=None, idx=i))
        else:
            steps.append(dict(kind="shell", command=a, orig_exit=None, orig_out=s.get("observation"), gap=None, idx=i))
    return steps


PARSERS = {"mini-swe-agent": parse_mini, "openhands": parse_openhands, "sweagent": parse_sweagent}


def normalize(agent, path):
    out = []
    for n, s in enumerate(PARSERS[agent](path), 1):
        out.append({
            "step": n,
            "kind": s["kind"],
            "command": s.get("command"),
            "edit": s.get("edit"),
            "orig_exit": s.get("orig_exit"),
            "orig_out_sha": out_sha(s["orig_out"]) if s.get("orig_out") is not None else None,
            "llm_gap_ms": s.get("gap"),
            "src_index": s["idx"],
        })
    return out


if __name__ == "__main__":
    agent, path = sys.argv[1], sys.argv[2]
    for st in normalize(agent, path):
        print(json.dumps(st))
