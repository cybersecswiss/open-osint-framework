#!/usr/bin/env python3
"""
LinkBase directory crawler → local index seed file.

link-base.ms exposes a keyless JSON API (`/api/v1/Board/{id}`) but rate-limits
hard (~1 request / 2s; a throttled call returns the JSON string
"Rate Limit Exceeded" with HTTP 200). A live per-search crawl is therefore
impossible. This script crawls the whole directory slowly, ONCE, and writes a
local index that the `linkbase_lookup` runner reads (no live API calls at
search time). Re-run periodically to refresh (baked seed ships in the image;
the module's `/linkbase/refresh` endpoint runs this same logic into the
`/cache` volume).

Pure stdlib so it can run on the host or in the slim module image.

Usage:  python3 linkbase_crawl.py [output.json] [--interval SECONDS] [--limit N]
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request

BASE = "https://link-base.ms"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
# Fields we keep from each board record (the API returns these + i18n HTML).
KEEP = ("Name", "Category", "TOR", "I2P", "Blockchain", "Telegram",
        "Discord", "Twitter", "Facebook", "NonFraud", "Information",
        "Screenshot", "Changed")


def _get(url: str, timeout: int = 25) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def board_ids() -> list[int]:
    _, html = _get(f"{BASE}/?lang=en")
    ids = sorted({int(x) for x in re.findall(r"/detail/Board/(\d+)", html)})
    return ids


def fetch_board(bid: int, interval: float, retries: int = 4) -> dict | None:
    """Fetch one board, retrying through the rate limiter. Returns the trimmed
    record dict, or None if it stayed throttled / was empty."""
    for attempt in range(retries):
        try:
            _, body = _get(f"{BASE}/api/v1/Board/{bid}")
            data = json.loads(body)
        except Exception:  # noqa: BLE001 — transient; back off and retry
            time.sleep(interval * (attempt + 2))
            continue
        if isinstance(data, dict) and data.get("Name"):
            rec = {k: (data.get(k) or "") for k in KEEP}
            rec = {k: (v.strip() if isinstance(v, str) else v) for k, v in rec.items()}
            rec["id"] = bid
            return rec
        # "Rate Limit Exceeded" (str) or unexpected shape → back off harder
        time.sleep(interval * (attempt + 2))
    return None


def crawl(interval: float = 2.0, limit: int | None = None) -> dict:
    ids = board_ids()
    if limit:
        ids = ids[:limit]
    records: list[dict] = []
    for i, bid in enumerate(ids, 1):
        rec = fetch_board(bid, interval)
        if rec:
            records.append(rec)
        if i % 25 == 0:
            print(f"  … {i}/{len(ids)} ids, {len(records)} records",
                  file=sys.stderr, flush=True)
        time.sleep(interval)
    return {
        "source": "link-base.ms",
        "board_count": len(records),
        "records": records,
    }


def main() -> int:
    out = "linkbase_index.json"
    interval = 2.0
    limit = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--interval":
            interval = float(args[i + 1]); i += 2
        elif a == "--limit":
            limit = int(args[i + 1]); i += 2
        else:
            out = a; i += 1
    print(f"Crawling link-base.ms → {out} (interval={interval}s)", file=sys.stderr)
    index = crawl(interval=interval, limit=limit)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    print(f"Wrote {index['board_count']} boards to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
