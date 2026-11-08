"""Keeps personal details out of this public repo. (Same guard as the author's other repos.)

gitleaks catches secrets (keys, tokens); this catches identifiers: addresses, handles, logins,
hostnames. The terms live outside the repo in the denylist file (PERSONAL_GUARD_DENYLIST, default ~/.bravehelm-denylist.txt) (one regex per line,
# comments) so the list itself is never published. Fails closed: no list, no commit.

  staged          staged diff + commit author (pre-commit)
  push            every commit about to be pushed (pre-push; git passes the refs on stdin)
  history [rev]   whole history, default --all (for a periodic scan of the published repo)

staged/push also refuse author/committer emails other than GitHub noreply addresses; history
only matches them against the terms (forks carry other people's real addresses).
"""
import pathlib, re, subprocess, sys

import os
DENYLIST = pathlib.Path(os.environ.get("PERSONAL_GUARD_DENYLIST", pathlib.Path.home() / ".bravehelm-denylist.txt"))
OK_EMAIL = re.compile(r"@users\.noreply\.github\.com$")
ZERO = "0" * 40


def git(*a, check=True):
    r = subprocess.run(["git", *a], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode:
        sys.exit(f"personal-guard: git {a[0]} failed: {r.stderr.strip()}")
    return r


def load_terms():
    try:
        lines = DENYLIST.read_text(encoding="utf-8").splitlines()
    except OSError:
        sys.exit(f"personal-guard: BLOCKED, {DENYLIST} is missing (fails closed)")
    terms = [re.compile(s) for s in (l.strip() for l in lines) if s and not s.startswith("#")]
    if not terms:
        sys.exit(f"personal-guard: BLOCKED, {DENYLIST} has no terms (fails closed)")
    return terms


def scan_log(text, terms, strict_email=True):
    """Hits in `git log -p` output made with the \\x00 markers below: messages, paths, added lines."""
    hits, commit, where, field = [], "staged", "", None
    for line in text.splitlines():
        if line.startswith("\x00C "):
            commit, field, where = line[3:13], "author", "message"
            continue
        if field in ("author", "committer"):
            if strict_email and not OK_EMAIL.search(line):
                hits.append(f"{commit}: {field} email is not a GitHub noreply address")
            if any(rx.search(line) for rx in terms):
                hits.append(f"{commit}: {field} email matches a term")
            field = "committer" if field == "author" else None
            continue
        if line == "\x00E":
            where = ""
            continue
        if line.startswith("diff --git "):
            where = line.split(" b/", 1)[-1]
        elif where != "message" and (line.startswith(("-", "@@", "index ", "+++ /dev/null"))
                                     or not line.startswith(("+", "rename ", "new file"))):
            continue
        for rx in terms:
            if rx.search(line):
                hits.append(f"{commit} {where or '?'}: matches /{rx.pattern}/")
    return hits


LOG = ["log", "--format=%x00C %H%n%ae%n%ce%n%B%n%x00E", "-p", "-U0", "--no-color", "--no-ext-diff",
       "--diff-merges=first-parent"]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "staged"
    terms = load_terms()
    if mode == "staged":
        out = "\x00C staged\n"
        for v in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
            out += re.sub(r".*<(.*)>.*", r"\1", git("var", v).stdout.strip()) + "\n"
        out += "\x00E\n" + git("diff", "--cached", "-U0", "--no-color", "--no-ext-diff").stdout
        hits = scan_log(out, terms)
    elif mode == "push":
        hits = []
        for line in sys.stdin.read().splitlines():
            _, local, _, remote = line.split()
            if local == ZERO:
                continue
            known = remote != ZERO and not git("cat-file", "-e", remote, check=False).returncode
            rng = [f"{remote}..{local}"] if known else [local, "--not", "--remotes"]
            hits += scan_log(git(*LOG, *rng).stdout, terms)
    elif mode == "history":
        hits = scan_log(git(*LOG, *(sys.argv[2:] or ["--all"])).stdout, terms, strict_email=False)
    else:
        sys.exit(f"personal-guard: unknown mode {mode}")
    if hits:
        print("personal-guard: BLOCKED, personal details headed for a public repo:", file=sys.stderr)
        for h in sorted(set(hits)):
            print("  " + h, file=sys.stderr)
        print(f"  Move the value to a config file outside the repo.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
