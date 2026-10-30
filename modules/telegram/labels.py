"""
Canonical graph-node labels for Telegram entities.

CRITICAL for graph dedup: the framework merges entities by
(entity_type, label). Both this authenticated module AND the keyless
`module-messenger` can surface the SAME public channel, so they must
produce an IDENTICAL label for it or the graph shows two nodes for one
channel. The shared convention is `@<handle>`, lower-cased (Telegram
handles are case-insensitive: @Durov and @durov are the same channel).

Channels without a public username (private/ID-only) can only ever be
seen by the authenticated module, so they get a stable id-based label
that never collides with a public handle.
"""
from __future__ import annotations


def canonical_channel_label(entity) -> str:
    username = getattr(entity, "username", None)
    if username:
        return f"@{username.lower()}"
    return f"tg_channel:{getattr(entity, 'id', '?')}"
