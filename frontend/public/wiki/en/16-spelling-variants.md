# Spelling variants

Cybercrime investigations rarely start with a person's name. They start with a
**handle** — and handles are never written the same way twice. The same actor
is `d4rkc1ph3r` on one forum, `darkcipher` on the next, `dark_cipher` on a
third, and `darkcipher1` after a ban.

Searching only for exactly the string you typed loses the hit on a single
substituted character, and nothing says so. The platform therefore searches
spelling variants alongside your input.

## What is now searched alongside your input

| Pattern | Example |
|---|---|
| Leetspeak | `d4rkc1ph3r` ↔ `darkcipher` |
| Separators | `dark_cipher`, `dark.cipher`, `dark-cipher` |
| Trailing numbers | `darkcipher1` → `darkcipher` |
| Cyrillic → Latin | `Пётр` → `petr` |

These work in **both directions**: searching `darkcipher` also finds
`d4rkc1ph3r`, and the other way round.

## The rule that matters: a candidate is not an identity

A hit under a variant means:

> An account exists whose spelling matches your search.

It does **not** mean:

> This is the same person.

`darkcipher` on Reddit and `d4rkc1ph3r` on XSS may be two people who both like
the word. The platform therefore keeps them visibly apart:

* variant hits carry **`match_type: variant`** and name the spelling that
  produced them
* they are **rated lower** than a direct hit
* their graph relationship is `possible_handle_variant` or
  `possible_account_of` — never `is_account_of`
* a note above the result list says how many hits came from variants

**What turns a candidate into a finding is a second signal:** the same
password, the same PGP key, the same forum, the same wallet, the same writing
habits. That is what corroboration is for (see *Assessing findings*). Record
the reasoning in the node's notes field — it appears next to the finding in
the report.

## Where it applies

**Automatically, at no cost**

*Known actors* (`threat_actor_check`) checks your handle and its variants
against an index of 830,000 usernames from 25 crime forums. The index is
local, so variant lookup costs nothing and takes milliseconds.

**On request, because it takes time**

*Handle sweep (spelling variants)* in the **Alias** module probes roughly 600
platforms — once per spelling. A run therefore takes one to three minutes
instead of fifty seconds. Pick the tool deliberately when a handle sits at the
centre of a case.

The payoff is real: in testing, `d4rkc1ph3r` alone returned 8 accounts; with
variants it returned 54.

## Limits worth knowing

**Separators can be removed but not invented.** `tony-stark` finds
`tonystark`. The reverse does not work — there is no way to know the split
belongs after `tony` rather than after `to`. **When in doubt, search the more
separated spelling**; it finds more.

**Short handles get no variants.** Below four characters every hit would be
noise: `b0b` for `bob` is almost certainly a different person.

**The number of spellings is capped.** The handle sweep probes at most four.
That is deliberate — an unbounded variant list produces candidates no
investigator would have thought of, and that is exactly where false leads come
from.

## People's names

Personal names follow different mechanics than handles:
sanctions screening compares **whole words, in any order**. "Vladimir Putin"
and "Putin Vladimir" now return the same result — previously one of the two
official lists dropped out depending on how you typed it, because the EU
writes "Vladimir PUTIN" and the US writes "PUTIN, Vladimir". The check is
still explicitly not fuzzy: only **whole words** are compared, so nobody ends
up on a sanctions list by accident.
