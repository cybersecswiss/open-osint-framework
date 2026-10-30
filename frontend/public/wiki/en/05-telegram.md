# Telegram tools (deep)

The **Telegram (deep)** module performs *authenticated* Telegram
collection over the official MTProto API. It reads far more than the
public web preview: full message history, channel members and admins,
forwards, media, plus user, phone-number and geolocation lookups.

> **Availability.** This module works only when your operator has
> configured an active Telegram session. If it is inactive, every tool
> returns a clear *"telegram module not authenticated"* note in the
> results instead of failing the whole search. Ask your operator to
> (re)authenticate — see the operator handbook, *"Telegram deep scanner
> (module-telegram)"*.

## The six tools

| Tool | Query type | Type your query as… |
|------|-----------|---------------------|
| `telegram_scan` | `Telegram channel` | `@channel`, a `t.me/…` link, or `+inviteHash` (comma-separate several) |
| `telegram_channel_info` | `Telegram channel` | `@channel` (comma-separate several) |
| `telegram_search` | `Telegram channel search` | `@chan1,@chan2 :: keyword` |
| `telegram_user_lookup` | `Telegram user / ID` | `@user` or a numeric ID (comma-separate several) |
| `telegram_phone_lookup` | `Phone number` | E.164 numbers, e.g. `+41790000000` (comma-separate several) |
| `telegram_geo` | `Telegram geo (lat,long)` | `47.3769,8.5417` |

Because `telegram_scan` and `telegram_channel_info` both answer the
`Telegram channel` query type, selecting the module for a channel query
runs **both** — you get the full scan *and* the channel metadata.

## What each tool returns

**`telegram_scan`** — the flagship. For each channel/group/invite:
- the **channel** (title, description, member count, verified flag)
- **messages** (text, date, views, forwards, replies, reactions, geo)
- **members** and, on request, **admins** with their roles
- **pinned** messages
- **media** (filename, size; optional SHA-256 / perceptual-hash / EXIF)
- **IOCs** extracted from message text (crypto addresses, emails, URLs,
  phone numbers, @mentions, #hashtags, `t.me/` links)
- **forward sources** as linked channels

It builds a connected graph: messages *in* the channel, authors who
*posted* them, members *of* the channel, IOCs *mentioned*, media
*attached*, and forwards *from* other channels.

**`telegram_channel_info`** — full channel metadata (description, online
count, linked discussion group, slow-mode, whether participants are
viewable) plus **similar/recommended channels**.

**`telegram_search`** — server-side keyword search across the channels
you name. Syntax: channels on the left of `::`, the keyword on the right:
`@ransomwatch,@leakchannel :: bitcoin`.

**`telegram_user_lookup`** — full user profile: bio, online status /
last-seen, bot/scam/fake/verified/premium flags, and **chats you have in
common** with the target (relative to the collection account).

**`telegram_phone_lookup`** — checks whether a phone number is on
Telegram and, if so, resolves the account. Heavily rate-limited — use it
for single lookups, not bulk lists. Imported contacts are automatically
deleted afterwards.

**`telegram_geo`** — finds users/channels near a coordinate that have
enabled geo-visibility, with the distance in metres.

## Operational notes

- **A scan can be large.** Members are capped at ~10 000 by Telegram;
  message count per channel follows the operator's configured limit.
- **Private / invite-only channels** need `auto_join` (an operator
  option) — otherwise you get metadata only, cleanly noted.
- **Privacy settings** on a target can hide their phone, last-seen and
  profile photos; those fields simply won't appear.
- **Evidence.** Every Telegram run is written to a tamper-evident,
  hash-chained audit log (operator side), recording who/what/when of the
  collection.
- **Data protection (Swiss LE).** Message text and, with hashing on,
  media are collected as-is. Keep scans scoped to what the case needs.

---

Next: **[Reading the graph →](06-reading-the-graph.md)** · Back: **[Modules & tools](04-modules-and-tools.md)**
