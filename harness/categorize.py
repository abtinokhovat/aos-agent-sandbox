"""Rule-based step categories: package install / test run / file edit / search-read / build / other."""
import re

R = lambda p: re.compile(p)  # noqa: E731
PKG = R(r"\b(pip3?|python[\d.]* -m pip|conda|mamba|apt(-get)?|npm|yarn|poetry)\s+(install|add|uninstall|update|upgrade)\b")
BUILD = R(r"\b(make|cmake|setup\.py\s+(build|build_ext|develop|install|egg_info|bdist\w*)|python[\d.]* -m build|cythonize|gcc|g\+\+)\b")
TEST = R(r"\b(pytest|py\.test|runtests\.py|tox|nosetests|unittest|manage\.py\s+test|python[\d.]*\s+-m\s+(pytest|unittest)|nox)\b")
EDIT = R(r"(\bsed\s+(-[a-zA-Z]*i|--in-place)|\bpatch\b|\bgit\s+(apply|checkout\s+--|stash|restore)|\btee\b|\bcat\s*(<<|>)|\becho\b.*>{1,2}\s*\S|\bprintf\b.*>{1,2}\s*\S|\bmv\b|\bcp\b|\brm\b|\btouch\b|\bmkdir\b|\bpython[\d.]*\s*-\s*<<|<<\s*['\"]?\w+['\"]?\s*>\s*\S)")
READ = R(r"^\s*(cd\s+\S+\s*(&&|;)\s*)?(ls|cat|head|tail|grep|egrep|fgrep|rg|find|tree|wc|file|stat|pwd|which|type|echo|git\s+(diff|log|status|show|grep|branch)|sed\s+-n|awk|sort|uniq|less|more|nl|cut|diff|readlink|du|df|env|printenv)\b|^\s*cd\s+\S+\s*$")


def categorize(kind, command, edit):
    if kind == "edit":
        return "search-read" if (edit or {}).get("command") == "view" else "file edit"
    c = command or ""
    if PKG.search(c):
        return "package install"
    if BUILD.search(c):
        return "build"
    if TEST.search(c):
        return "test run"
    if EDIT.search(c):
        return "file edit"
    if READ.search(c):
        return "search-read"
    return "other"
