import hashlib
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MODULE_VERSION = "0.2.0"
GENESIS_HASH = "0" * 64


def collection_meta(tool: str, query: str, scanner_account_id) -> dict:
    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "scanner_account_id": scanner_account_id,
        "tool": tool,
        "query": query,
        "module_version": MODULE_VERSION,
    }


def _last_hash(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            last = None
            for line in fh:
                line = line.strip()
                if line:
                    last = line
            if last is None:
                return GENESIS_HASH
            return json.loads(last).get("entry_hash", GENESIS_HASH)
    except FileNotFoundError:
        return GENESIS_HASH
    except Exception as e:
        logger.warning("Could not read audit log tail: %s", e)
        return GENESIS_HASH


def append_audit(response_dict: dict) -> str | None:
    path = os.getenv("AUDIT_LOG_PATH")
    if not path:
        return None
    prev_hash = _last_hash(path)
    serialized = json.dumps(response_dict, sort_keys=True, default=str)
    entry_hash = hashlib.sha256((prev_hash + serialized).encode("utf-8")).hexdigest()
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": response_dict.get("tool"),
        "job_id": response_dict.get("job_id"),
        "finding_count": len(response_dict.get("findings", [])),
        "prev_hash": prev_hash,
        "entry_hash": entry_hash,
    }
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception as e:
        logger.warning("Could not write audit log: %s", e)
        return None
    return entry_hash
