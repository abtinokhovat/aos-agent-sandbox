#!/opt/miniconda3/bin/python
# In-container file editor used to replay agent edit-tool calls (str_replace_editor semantics).
# Reads one JSON request on stdin: {command, path, file_text, old_str, new_str, insert_line, view_range}.
# Exit code 0 on success, 1 on error (message on stdout, like the original tools report errors in-band).
import json, os, sys

req = json.load(sys.stdin)
cmd, path = req["command"], req["path"]
HIST = "/tmp/.aos_edit_hist"


def save_hist(p):
    os.makedirs(HIST, exist_ok=True)
    h = os.path.join(HIST, p.strip("/").replace("/", "__"))
    if os.path.exists(p):
        with open(p, "rb") as f, open(h, "wb") as g:
            g.write(f.read())


def fail(msg):
    print(msg)
    sys.exit(1)


if cmd == "view":
    if os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            depth = root[len(path):].count(os.sep)
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            if depth >= 2:
                dirs[:] = []
            for n in sorted(files):
                if not n.startswith("."):
                    print(os.path.join(root, n))
    elif os.path.isfile(path):
        lines = open(path, errors="replace").read().split("\n")
        lo, hi = 1, len(lines)
        if req.get("view_range"):
            lo = req["view_range"][0]
            hi = len(lines) if req["view_range"][1] == -1 else req["view_range"][1]
        for i in range(lo, hi + 1):
            print("%6d\t%s" % (i, lines[i - 1]))
    else:
        fail("path %s does not exist" % path)
elif cmd == "create":
    if os.path.exists(path):
        fail("file already exists at %s" % path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(req.get("file_text", ""))
    print("File created successfully at: %s" % path)
elif cmd == "str_replace":
    if not os.path.isfile(path):
        fail("path %s does not exist" % path)
    s = open(path, errors="surrogateescape").read()
    old, new = req["old_str"], req.get("new_str", "")
    n = s.count(old)
    if n != 1:
        fail("old_str occurs %d times in %s" % (n, path))
    save_hist(path)
    with open(path, "w", errors="surrogateescape") as f:
        f.write(s.replace(old, new))
    print("The file %s has been edited." % path)
elif cmd == "insert":
    if not os.path.isfile(path):
        fail("path %s does not exist" % path)
    lines = open(path, errors="surrogateescape").read().split("\n")
    save_hist(path)
    ln = req["insert_line"]
    lines[ln:ln] = req.get("new_str", "").split("\n")
    with open(path, "w", errors="surrogateescape") as f:
        f.write("\n".join(lines))
    print("The file %s has been edited." % path)
elif cmd == "undo_edit":
    h = os.path.join(HIST, path.strip("/").replace("/", "__"))
    if not os.path.exists(h):
        fail("no edit history for %s" % path)
    with open(h, "rb") as f, open(path, "wb") as g:
        g.write(f.read())
    print("Last edit to %s undone successfully." % path)
else:
    fail("unknown command %s" % cmd)
