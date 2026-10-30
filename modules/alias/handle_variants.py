"""Spelling variants and canonical forms for usernames and handles.

Why this exists
---------------
Cybercrime attribution runs on reuse: the same person carries the same handle
across forums, markets and messengers. But they rarely carry it *identically*
— `d4rkm4st3r`, `dark_master`, `darkmaster1` and `DarkMaster` are one actor
and four strings. Every tool in this framework used to compare those strings
exactly, so a single substituted character silently cost the hit.

Two different jobs live here, and confusing them causes false positives:

``canonical()``  collapses a handle into an equivalence class. It answers
                 "could these two strings be the same handle?" and is what you
                 want when you control both sides of the comparison — a local
                 index, a list you already hold. Cheap: one pass, no
                 combinatorics, and both sides collapse to the same key.

``variants()``   produces a short, ordered list of *other strings to try*. It
                 is for tools that query someone else's service and can only
                 ask about one concrete spelling at a time. Bounded on
                 purpose — the point is a handful of plausible spellings, not
                 an exhaustive cartesian product.

Neither function establishes identity. A hit on a variant means "a handle that
could plausibly be the same person exists here", never "this is the same
person". Callers MUST mark such hits as variant matches and carry a lower
confidence, so the analyst — and later the report — can tell a direct hit from
a derived one. Corroboration (same password, same PGP key, same forum, same
wallet) is what turns a candidate into a finding, not this module.
"""
from __future__ import annotations

import re

# Characters that read as the same glyph in handle culture. Every member of a
# class folds to the class's representative, so `1`, `i`, `l` and `|` all
# become `i`: it does not matter which one the actor typed, both sides of a
# comparison land on the same key.
#
# `6`/`9` are deliberately absent — they stand in for `b`/`g` about as often
# as they are just digits, and folding them collides ordinary numeric handles.
_CLASSES = {
    "i": "1il|!",
    "o": "0o",
    "e": "3e",
    "a": "4a@",
    "s": "5s$",
    "t": "7t+",
    "b": "8b",
    "z": "2z",
}

_FOLD = {ch: rep for rep, members in _CLASSES.items() for ch in members}

# Separators an actor sprinkles in without changing who they are.
_SEPARATORS = "_.-"
_SEP_RE = re.compile(f"[{re.escape(_SEPARATORS)}]+")
_TRAILING_DIGITS = re.compile(r"\d{1,4}$")

# Below this, folding collides too eagerly: "bob"/"b0b" is fine, but three
# characters of leetspeak match far too much to be worth an analyst's time.
MIN_FUZZY_LEN = 4

# Ceiling for variants(); a caller that fans out over ~600 platforms must not
# be handed an unbounded list.
MAX_VARIANTS = 12


def canonical(handle: str) -> str:
    """Fold a handle into its equivalence class.

    Lowercases, folds look-alike characters onto one representative and drops
    separators, so ``d4rk_m4st3r``, ``DarkMaster`` and ``dark.master`` all
    return ``darkmaster``.

    A leading ``@`` is the handle sigil (``@user`` on Telegram or X) and is
    stripped; the same character inside the word is a leet ``a``.

    Returns "" for input too short to fold safely — callers should treat that
    as "do not attempt a fuzzy match".
    """
    s = (handle or "").strip().lstrip("@").casefold()
    s = _SEP_RE.sub("", s)
    s = "".join(_FOLD.get(c, c) for c in s)
    return s if len(s) >= MIN_FUZZY_LEN else ""


def _leet(handle: str) -> str:
    """One canonical leetspeak spelling — the reverse direction of the fold."""
    swap = {"a": "4", "e": "3", "o": "0", "s": "5", "t": "7", "i": "1"}
    return "".join(swap.get(c, c) for c in handle)


def variants(handle: str, limit: int = MAX_VARIANTS) -> list[str]:
    """Plausible other spellings of `handle`, most likely first.

    The original is never included — the caller has already tried it. The list
    is deduplicated, order-stable and capped at `limit`.

    Covered: separator styles, a stripped trailing number ("darkmaster1" →
    "darkmaster"), the de-leeted form and one leeted form. Deliberately NOT
    covered: character transpositions, doubled letters and edit-distance
    neighbours — those explode combinatorially and produce candidates no
    analyst would have guessed, which is exactly where false leads come from.

    Known asymmetry: separators can be removed but not invented.
    ``tony-stark`` yields ``tonystark``, while ``tonystark`` does not yield
    ``tony-stark`` — there is no way to know that the split belongs after
    "tony" rather than after "to". Searching the more separated spelling
    therefore finds more.
    """
    base = (handle or "").strip().lstrip("@")
    # Same floor as canonical(): below it the variants are worthless as leads
    # ("b0b" for "bob" is almost certainly a different person) and the two
    # functions would otherwise disagree about what "too short" means.
    if len(_SEP_RE.sub("", base)) < MIN_FUZZY_LEN:
        return []

    out: list[str] = []

    def add(candidate: str) -> None:
        c = candidate.strip()
        if c and c.casefold() != base.casefold() and c not in out:
            out.append(c)

    low = base.casefold()
    stripped = _SEP_RE.sub("", low)
    deleeted = "".join(_FOLD.get(c, c) for c in stripped)

    # Same word, different separator habits.
    add(stripped)
    for sep in _SEPARATORS:
        if len(stripped) >= MIN_FUZZY_LEN:
            add(_SEP_RE.sub(sep, low))

    # The plain-text reading of a leeted handle, and vice versa.
    add(deleeted)
    add(_leet(deleeted))

    # Handles collect and shed trailing numbers between forums.
    trimmed = _TRAILING_DIGITS.sub("", stripped)
    if trimmed and trimmed != stripped and len(trimmed) >= MIN_FUZZY_LEN:
        add(trimmed)
        add("".join(_FOLD.get(c, c) for c in trimmed))

    return out[:limit]


# --- Cyrillic ---------------------------------------------------------------
#
# Russian-language forums are the main stage for this kind of investigation,
# and the same actor is written both ways. This is a transliteration, not a
# translation: it offers a Latin spelling to search for, and the mapping is
# lossy in both directions (Ё/Е, Й/И). Treat what comes back as a candidate.

_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

_HAS_CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def has_cyrillic(text: str) -> bool:
    return bool(_HAS_CYRILLIC.search(text or ""))


def transliterate(text: str) -> str:
    """Latin spelling of a Cyrillic string; returns "" if there is nothing
    Cyrillic to transliterate, so a caller can skip the extra lookup."""
    if not has_cyrillic(text):
        return ""
    return "".join(_CYRILLIC.get(c, _CYRILLIC.get(c.lower(), c))
                   for c in (text or ""))
