#!/usr/bin/env python3
"""Flag PR additions that re-introduce lines a recent fix commit removed.

This is the check that would have caught the 0.16.2 release merge silently
undoing the RingBuffer::push() fix from #697.

Algorithm:
  1. List recent merged commits on the base branch whose subject suggests they
     fixed something (configurable keyword list, default: 'fix', 'bug',
     'regression', 'crash', 'race').
  2. For each, collect the *non-trivial* lines those commits removed.
  3. Inspect the PR diff (HEAD against the merge base with the target branch).
     If any line the PR is ADDING matches a line a recent fix REMOVED, flag it.

Trivial lines (blank, single brace, comments, includes, etc.) are filtered out
to avoid false positives. The window of "recent" commits is configurable; the
default 200 covers a comfortable release cycle.

Exits 0 if no regressions are detected. Exits 1 (failing CI) otherwise, with a
human-readable summary listing the offending lines and the fix commits whose
work is being undone.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable


FIX_KEYWORDS = ("fix", "bug", "regression", "crash", "race", "leak", "deadlock")

# Lines that are too generic to flag — they recur naturally in any C++/Python diff.
_TRIVIAL_RE = re.compile(
    r"^\s*(//.*|#.*|/\*.*|\*.*|\*/.*|}|{|\)|;|else|return;|return 0;|pass|"
    r"continue|break|}\;|return;)\s*$"
)


def _git(*args: str) -> str:
    return subprocess.check_output(("git",) + args, text=True)


def _git_lines(*args: str) -> list[str]:
    return _git(*args).splitlines()


def _is_trivial(line: str) -> bool:
    s = line.strip()
    if len(s) < 8:
        return True
    if _TRIVIAL_RE.match(line):
        return True
    return False


@dataclass(frozen=True)
class Removal:
    commit: str
    subject: str
    path: str
    line: str


def _looks_like_fix(subject: str) -> bool:
    head = subject.lower().split(":", 1)[0]
    return any(kw in head for kw in FIX_KEYWORDS) or any(
        f" {kw} " in subject.lower() for kw in FIX_KEYWORDS
    )


def collect_recent_fix_removals(
    base_ref: str, window: int
) -> dict[tuple[str, str], list[Removal]]:
    """For each (path, removed_line) recently removed by a fix commit on the
    base branch, return one or more Removal records."""
    revs = _git_lines("rev-list", "--no-merges", "-n", str(window), base_ref)
    out: dict[tuple[str, str], list[Removal]] = defaultdict(list)
    for sha in revs:
        subject = _git("log", "-1", "--format=%s", sha).strip()
        if not _looks_like_fix(subject):
            continue
        diff = _git("show", "--no-color", "--format=", sha)
        current_path: str | None = None
        for line in diff.splitlines():
            if line.startswith("+++ b/"):
                current_path = line[6:]
                continue
            if line.startswith("--- ") or line.startswith("diff "):
                current_path = None
                continue
            if (
                current_path
                and line.startswith("-")
                and not line.startswith("---")
            ):
                content = line[1:]
                if _is_trivial(content):
                    continue
                key = (current_path, content)
                out[key].append(
                    Removal(sha[:10], subject, current_path, content)
                )
    return out


def collect_pr_additions(base_ref: str, head_ref: str) -> Iterable[tuple[str, str]]:
    merge_base = _git("merge-base", base_ref, head_ref).strip()
    diff = _git("diff", "--no-color", f"{merge_base}...{head_ref}")
    current_path: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[6:]
            continue
        if line.startswith("--- ") or line.startswith("diff "):
            current_path = None
            continue
        if (
            current_path
            and line.startswith("+")
            and not line.startswith("+++")
        ):
            content = line[1:]
            if _is_trivial(content):
                continue
            yield current_path, content


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default="origin/master",
        help="Base branch (default: origin/master)",
    )
    parser.add_argument(
        "--head",
        default="HEAD",
        help="Head ref to compare (default: HEAD)",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=200,
        help="Number of recent commits on base to scan for fix removals",
    )
    args = parser.parse_args(argv)

    removals = collect_recent_fix_removals(args.base, args.window)
    if not removals:
        print(
            f"check-revert-regression: no fix-removals found in last "
            f"{args.window} commits on {args.base}; nothing to check."
        )
        return 0

    hits: list[tuple[str, str, list[Removal]]] = []
    for path, line in collect_pr_additions(args.base, args.head):
        match = removals.get((path, line))
        if match:
            hits.append((path, line, match))

    if not hits:
        print("check-revert-regression: PR does not re-introduce any recently "
              "fixed lines.")
        return 0

    print(
        "check-revert-regression: this PR re-introduces lines that a recent "
        "fix commit removed. Please rebase or cherry-pick the fix forward."
    )
    print()
    for path, line, removals_for_line in hits:
        print(f"  {path}:")
        print(f"    + {line.rstrip()}")
        for r in removals_for_line:
            print(f"      ↳ removed by {r.commit}  {r.subject}")
        print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
