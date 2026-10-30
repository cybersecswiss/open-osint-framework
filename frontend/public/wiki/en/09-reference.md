# Reference & glossary

## Query types

The **query type** tells the platform how to interpret your search term
and which modules/tools can handle it. Pick it from the *Type* dropdown
in the search form.

| Query type (dropdown) | Example input | Typically handled by |
|-----------------------|---------------|----------------------|
| Username / Alias | `anonymous99` | alias, leaks (hudsonrock), messenger (username hunt) |
| Email | `max@example.com` | leaks |
| Domain | `example.com` | infra, threat |
| IP address | `1.2.3.4` | infra, threat |
| URL | `http://bad.example/x` | threat |
| Hash (MD5/SHA1/SHA256) | `sha256:…` | threat |
| Phone number | `+41790000000` | **telegram** |
| Bitcoin address | `bc1q…` | crypto |
| Ethereum address | `0x…` | crypto |
| Telegram channel | `@durov` | messenger (keyless), **telegram** (deep) |
| Telegram channel search | `ransomware` | messenger |
| Telegram message search | `@chan :: keyword` | messenger |
| Telegram user / ID | `@user` | **telegram** |
| Telegram geo (lat,long) | `47.3769,8.5417` | **telegram** |
| Discord invite | `discord.gg/abc` | messenger |
| Keyword (darknet/paste) | `acme breach` | darknet |

Only modules that understand the chosen query type appear as tickable
options in the search form.

## Entity types in the graph

Nodes are coloured by type. Unknown types render grey and still work.

| Colour | Entity type | Meaning |
|:------:|-------------|---------|
| 🔵 | `person` | A person |
| 🟢 | `social_account` | A social-media account |
| 🟠 | `organization` | An organisation |
| 🔴 | `email_address` | An email address |
| 🟣 | `domain` | A domain |
| 🩵 | `username` | A username / alias |
| 🩷 | `ip_address` | An IP address |
| 🟢 | `phone_number` | A phone number |
| 🟧 | `location` | A geographic location |
| 🔵 | `telegram_channel` | A Telegram channel/group |
| 🔵 | `telegram_message` | A Telegram message |
| 🔵 | `telegram_user` | A Telegram user |
| 🔵 | `telegram_media` | A media file in Telegram |
| 🔴 | `telegram_ioc` | An indicator (crypto/email/URL/…) found in a message |
| 🟣 | `telegram_linked_channel` | A channel referenced via a forward |

## Edge relations

Edges are labelled with the relationship. Telegram collection produces:

`POSTED` · `POSTED_IN` · `IN_CHANNEL` · `MEMBER_OF` · `ADMIN_OF` ·
`PINNED_IN` · `REPLY_TO` · `FORWARDED_FROM` · `MENTIONS` · `HAS_MEDIA` ·
`COMMON_CHAT` · `LINKED_DISCUSSION` · `SIMILAR_TO`

Other modules add their own (e.g. an alias-to-account link). Hover an
edge in the graph to see its label.

## Indicator (IOC) types extracted from Telegram text

`btc` · `eth` · `xmr` · `ltc` · `tron` (crypto addresses) · `email` ·
`url` · `telegram_link` · `phone` · `mention` (@handle) · `hashtag`.

## Glossary

- **Case** — the container for one investigation. Every search result is
  attached to a case.
- **Entity** — a node in the case graph (a person, account, channel,
  address, message, …).
- **Edge** — a labelled relationship between two entities.
- **Module** — a self-contained collector (one of the 8). You choose
  which to run per search.
- **Tool** — a single source inside a module (e.g. `virustotal`).
- **Query type** — how your search term is interpreted (see above).
- **IOC** — Indicator of Compromise: a crypto address, email, URL,
  hash, etc.
- **Tenant** — your organisation. Your data lives in your own
  organisation's storage; the platform operator cannot read it.
- **Session (Telegram)** — the authenticated Telegram login the deep
  module uses; maintained by your operator.

## Troubleshooting

| Symptom | Meaning / what to do |
|---------|----------------------|
| A tool row shows a "key not set" note | That source needs an API key your operator hasn't configured. Other tools still ran. |
| Telegram tools say "not authenticated" | The Telegram session is inactive — ask your operator to re-authenticate it. |
| No modules appear for my query type | No installed module handles that type; pick a different type or term. |
| A node looks disconnected | It's the term you searched for (the "root"), or an endpoint no tool returned full details for. |
| Search finished but few results | Normal — a clean negative (like an email with no breaches) is a valid result. |

## Authority settings (for admins)

Under **Admin → Settings** your authority's admins set, for everyone in it:

| Setting | Effect |
|---|---|
| Display name, logo | Header and report cover |
| Default language | Interface language until a user picks their own |
| Require a purpose for every search | Search and new watches need a purpose / legal basis, kept in your search log |
| Classification marking in reports | Printed in red on every page of every PDF report |
| Default playbook | Preselected in the search form where it fits |
| Disabled modules | Licensed modules your authority does not use — gone from search and from existing watches |
| Session timeout, auto-delete | Sign-out after inactivity; deletion of closed cases after N months |

Modules can only be switched **off** here; which modules are licensed is part
of your contract with the platform operator.

**Self-test.** *Admin → Self-test* checks, in one list with traffic lights,
whether your installation works: licence, your data store (reachable, key
accepted, up to date), TLS certificate, the integrity of the search-log chain,
your sign-in service, the alert channel and evidence capture — each with a
sentence saying what to do. Run it after installing or updating.

---

Back: **[Home](00-overview.md)**
