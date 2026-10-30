#!/usr/bin/env python3
"""
Threat-actor username index builder.

Downloads spmedia/Threat-Actor-Usernames-Scrape (25 per-forum .txt files,
~773k unique cybercrime-forum usernames: BreachForums, Cracked, HackForums,
XSS, OGUsers, Dread, RAMP …) and builds a compact gzipped lookup index
`{username_lower: [forum, …]}` that the `threat_actor_check` runner reads to
answer "is this username a known cybercrime-forum actor, and where?".

Pure stdlib. Run once to bake the seed (`data/threat_actors.json.gz`); the
module's `POST /threat-actors/refresh` re-runs it into the /cache volume.

Usage: python3 threat_actor_crawl.py [output.json.gz]
"""
from __future__ import annotations

import gzip
import json
import re
import sys
import urllib.parse
import urllib.request

REPO = "spmedia/Threat-Actor-Usernames-Scrape"
TREE = f"https://api.github.com/repos/{REPO}/git/trees/main?recursive=1"
RAW = f"https://raw.githubusercontent.com/{REPO}/main/"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# Reasonable per-username bound so a pathological line can't bloat the index.
MAX_USERNAME_LEN = 80


def _get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _forum_label(path: str) -> tuple[str, bool]:
    """(clean forum name, is_dead) from a filename like
    dead_forum_users_ramp.txt / forum_users_cracked.txt."""
    name = path.rsplit("/", 1)[-1]
    name = re.sub(r"\.txt$", "", name, flags=re.I)
    dead = name.startswith("dead_")
    name = re.sub(r"^dead_forum_users_", "", name)
    name = re.sub(r"^forum_users_", "", name)
    return name.strip("_") or name, dead


def list_txt_files() -> list[str]:
    tree = json.loads(_get(TREE).decode("utf-8", "replace"))
    return [t["path"] for t in tree.get("tree", [])
            if t["path"].lower().endswith(".txt")]


def build() -> dict:
    files = list_txt_files()
    index: dict[str, list[str]] = {}
    dead_forums: set[str] = set()
    forum_count = 0
    for path in files:
        forum, dead = _forum_label(path)
        if dead:
            dead_forums.add(forum)
        try:
            raw = _get(RAW + urllib.parse.quote(path)).decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            print(f"  ! {path}: {e}", file=sys.stderr)
            continue
        forum_count += 1
        n = 0
        for line in raw.splitlines():
            u = line.strip()
            if not u or u.startswith("#") or len(u) > MAX_USERNAME_LEN:
                continue
            key = u.lower()
            bucket = index.get(key)
            if bucket is None:
                index[key] = [forum]
            elif forum not in bucket:
                bucket.append(forum)
            n += 1
        print(f"  + {forum:<18} {n:>7} lines ({len(index)} unique so far)",
              file=sys.stderr, flush=True)
    return {
        "source": REPO,
        "forum_count": forum_count,
        "username_count": len(index),
        "dead_forums": sorted(dead_forums),
        "index": index,
    }


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "threat_actors.json.gz"
    print(f"Building threat-actor index from {REPO} → {out}", file=sys.stderr)
    data = build()
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Wrote {data['username_count']} usernames "
          f"({data['forum_count']} forums) to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
