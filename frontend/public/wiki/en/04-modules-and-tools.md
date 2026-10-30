# Modules & Tools

A **search** runs one or more **modules**. Each module bundles several
**tools** that query real OSINT sources. You never call tools directly —
you pick a **query type**, type an indicator, and tick the modules you
want. The system automatically runs every tool that understands that
query type.

There are **14 modules** (about 85 tools, three of them off by default). Some tools need an API key
configured by your operator; without it that single tool returns a clear
"key not set" note instead of failing the search. A few modules are
opt-in and only appear if your authority is licensed for them.

| # | Module | What it's for | Needs a key? |
|---|--------|---------------|--------------|
| 1 | **Alias pivoting** (`alias`) | Find a username/alias across the web | No |
| 2 | **Leaks & breaches** (`leaks`) | Email/username in breaches + account footprint | Partly |
| 3 | **Infrastructure** (`infra`) | Domain / IP recon, phishing look-alikes | Partly |
| 4 | **Threat intel** (`threat`) | Reputation & malware attribution of an IOC | Partly |
| 5 | **Darknet & paste** (`darknet`) | Tor hidden services, pastes, **seizure watch** | No |
| 6 | **Messenger** (`messenger`) | Keyless Telegram preview, Discord, phone→messenger | Partly |
| 7 | **Crypto tracing** (`crypto`) | Bitcoin / Ethereum addresses + wallet attribution | Partly |
| 8 | **Telegram (deep)** (`telegram`) | Authenticated, in-depth Telegram collection | Session |
| 9 | **Compliance** (`compliance`) | Sanctions / PEP / watchlist screening | Partly |
| 10 | **Crime forums** (`forums`) | Forum hunting, threat-actor index, PGP, link directories | Partly |
| 11 | **Image OSINT** (`image`) | Photo EXIF/GPS + AI location estimate | Partly |
| 12 | **News & RSS** (`news`) | Full-text search across authority, police, media and cyber feeds | No |
| 13 | **Companies & people** (`corporate`) | Registers, group structure, sanctions lists, directories — see [its own page](15-companies-and-people.md) | No |
| 14 | **Dating & adult** (`dating`) | Username sweep across dating/adult sites — **off by default** | No |

---

## 1. Alias pivoting — `alias`

Turns a username or alias into a map of accounts.

| Tool | Source | Notes |
|------|--------|-------|
| `sherlock` | 600+ platforms | Checks where a username exists |
| `whatsmyname` | Live upstream site list | Always-current platform coverage |
| `user_scanner` | Multi-site | Broad username presence sweep |
| `linkook` | Connected-account graph | Follows links between a user's profiles |

**Query type:** `Username / Alias`. Every hit is re-verified to drop
false positives, so a listed account really exists.

## 2. Leaks & breaches — `leaks`

Where an email/username surfaced in breaches and which services it's
registered with.

| Tool | Source | Key |
|------|--------|-----|
| `holehe` | ~120 sites | No — is the address registered there? |
| `hibp` | HaveIBeenPwned | Yes (`HIBP_API_KEY`) |
| `intelx` | Intelligence X | No — produces a deep link |
| `ghunt` | Google account | Session — email/Gaia-ID → rich Google profile, Maps reviews |
| `hudsonrock` | Infostealer intel | Keyless — email/domain → infostealer infections |

**Query types:** `Email` (+ `hudsonrock` also username/domain,
`ghunt` also a Gaia ID).

> **Passwords** are stored only as a SHA-256 fingerprint + masked preview
> (`a••••z`) unless your operator explicitly enables cleartext.

## 3. Infrastructure — `infra`

Domain and IP recon — and finding the **phishing/look-alike** infra
around a brand.

| Tool | Source | Key |
|------|--------|-----|
| `subfinder` | Subdomain enumeration | No |
| `whois` | Registration / ownership | No |
| `crtsh` | Certificate-transparency logs | No |
| `dns_records` | A / AAAA / MX / NS / TXT / CNAME | No |
| `theharvester` | Emails/hosts for a domain | No |
| `shodan_host` | Open ports, banners, CVEs | Yes (`SHODAN_API_KEY`) |
| `favicon_pivot` | Same favicon → related hosts | Yes (Shodan) |
| `dnstwist` | **Typosquat / phishing domains** | No |
| `passive_dns` | **Historic** domain↔IP resolutions (Mnemonic) | No |
| `asn_lookup` | Who carries this address: prefix, AS, holder (RIPEstat) | No |
| `origin_resolve` | Real server behind a CDN (Cloudflare & co.), verified by direct probe — **off by default** (`ENABLE_ORIGIN_RESOLVE`) | No |

**Query types:** `Domain`, `IP address`, `URL`.
`dnstwist` turns a domain into the list of registered look-alike domains
(homoglyph/IDN, bitsquatting, TLD-swap …) that actually resolve — live
phishing/impersonation candidates to pivot on.

**`passive_dns` is the one that looks backwards.** Every other tool here
answers "what is true now" — which is precisely the state an operator
changes once they are burned. Passive DNS answers "what did this domain
point at last March", in both directions, and that is usually where the
pivot is. `asn_lookup` adds a new `asn` node so hosts carried by the same
network converge in the graph — the bulletproof-hoster pattern.

## 4. Threat intel — `threat`

Reputation, classification and **malware attribution** of an indicator.

| Tool | Source | Key |
|------|--------|-----|
| `virustotal` | VirusTotal | Yes |
| `abuseipdb` | AbuseIPDB | Yes |
| `urlhaus` | abuse.ch URLhaus | Keyless/Key |
| `greynoise` | GreyNoise community | Keyless |
| `urlscan` | urlscan.io | Keyless |
| `threatfox` | abuse.ch ThreatFox (IOC→malware) | Key |
| `malwarebazaar` | abuse.ch MalwareBazaar (hash→sample) | Key |
| `ransomware_watch` | Leak-site victims, groups, their onion sites | Optional |
| `c2_intel` | Known **command-and-control** infrastructure from Censys scans | No |
| `ioc_reputation` | **How many independent blocklists** carry this indicator | No |
| `cve_lookup` | CVE detail **plus** exploited-in-the-wild status (NVD + CISA KEV) | No |

**Query types:** `Domain`, `IP address`, `URL`, `Hash`, `CVE`, `Keyword`.

Three of these are worth understanding as a group, because they answer
different questions about the same address:

* `c2_intel` — *was this host seen serving a C2 panel, and for which malware
  family?* A hit is an observation of the software itself, not an opinion.
* `ioc_reputation` — *how many independent blocklists list this?* One list
  says little; agreement between lists that do not share a source says a lot.
  The answer states how many lists were consulted, so a small number is
  readable as coverage rather than as innocence.
* `cve_lookup` — *is this vulnerability actually being exploited?* If the
  CISA catalogue cannot be reached, "exploited" is reported as **unknown**,
  never as "no".

`ransomware_watch` runs without a key but is then limited to one request per
minute per endpoint; a free key from my.ransomware.live removes that and the
tool picks it up by itself.

## 5. Darknet & paste — `darknet`

| Tool | Query type | What it does |
|------|-----------|--------------|
| `ahmia` | `Keyword` | Live Tor hidden-service search (Torch/TorDex) |
| `paste_search` | `Keyword` | Paste-site index |
| `seizure_watch` | `Domain` (or `.onion`) | **FBI-Watchdog:** detects a law-enforcement **seizure/takedown** (seizure banner, agency names) and snapshots the infra (A/NS records, redirect) so a change can be spotted later |
| `onion_scrape` | `Onion address` | Fetches a hidden service over Tor and extracts its contacts/IOCs — **off by default** (`ENABLE_ONION_SCRAPE`) |

## 6. Messenger — `messenger`

Keyless Telegram + Discord, plus phone→messenger.

| Tool | Query type | What it does |
|------|-----------|--------------|
| `telegram_channel` | `Telegram channel` | Public channel preview |
| `tgstat` | `Telegram channel` | Channel stats/analytics |
| `telegram_username_hunt` | `Username` | Sweeps known crime channels for the alias |
| `telegram_search` / `telegram_global_search` | `Telegram search` | Public Telegram search engines |
| `telegram_message_search` | `Telegram message search` | Keyword over the public preview |
| `discord_invite` | `Discord invite` | Resolves an invite → server info |
| `discord_snowflake` | `Discord ID` | Decodes a user ID → **account creation date** (keyless) |
| `discord_deep` | `Discord ID` | **Full public profile** (name, avatar/banner, badges) — needs `DISCORD_BOT_TOKEN` |
| `phone_messenger` | `Phone` | Normalises a number (country/carrier/line-type) + a **WhatsApp deep link** to check manually |

> `phone_messenger` never claims a number "is on WhatsApp" — there's no
> compliant automated check. It gives you the verified number details
> and a link you open yourself.

## 7. Crypto tracing — `crypto`

| Tool | Source | Key |
|------|--------|-----|
| `blockchain_btc` | blockchain.info | Keyless |
| `etherscan_eth` | Etherscan | Yes (`ETHERSCAN_API_KEY`) |
| `blockscout` | Blockscout (keyless ETH fallback) | Keyless |
| `wallet_attribution` | MistTrack | Yes — wallet → exchange/mixer/scam/ransomware cluster + risk |

**Query types:** `Bitcoin address`, `Ethereum address`.

## 8. Telegram (deep) — `telegram`

Authenticated MTProto collection — full history, members, and
user/phone/geo lookups. Needs a Telegram **session** set up by your
operator. Its own page: **[Telegram tools](05-telegram.md)**.

## 9. Compliance — `compliance`

| Tool | Source | Key |
|------|--------|-----|
| `opensanctions` | OpenSanctions (OFAC/EU/UN/SECO…) | Yes, or keyless self-host |

Screens a **name, company or crypto wallet** against sanctions / PEP /
watchlists. **Query types:** `Keyword`/name, crypto address.

## 10. Crime forums — `forums`

| Tool | What it does | Key |
|------|--------------|-----|
| `crime_forum_hunt` | Dorks clearnet + darknet crime forums for a term/alias/contact-ID | Brave key helps |
| `threat_actor_check` | Looks an alias up in a large threat-actor index | Keyless |
| `linkbase_lookup` | Curated darknet link-directory lookup | Keyless |
| `pgp_lookup` | Finds/parses an actor's PGP key + fingerprint | Keyless |

**Query types:** `Keyword`, `Username`, plus contact-IDs (`Jabber`,
`Tox`, `Session`, PGP fingerprint).

## 11. Image OSINT — `image`

Pull location evidence out of a photo. **Query type:** `Image URL`.

| Tool | What it does | Key |
|------|--------------|-----|
| `exif_gps` | Reads embedded EXIF: camera make/model, timestamp, and **GPS** → a `location` node with the place name | No |
| `visual_geolocate` | When there's no GPS, an **AI estimates the location** from visible cues (signs, architecture) — clearly marked *AI-estimate*, a lead to verify | Yes (Gemini) |

> The AI estimate is a lead, not proof. If the model can't tell, it says
> so and adds nothing — it never invents a location.

## 12. News & RSS — `news`

| Tool | Query type | What it does |
|------|-----------|--------------|
| `news_search` | `Keyword` | Full-text search across the feeds your operator maintains — federal bodies, police, media, tech and cyber |

Every hit carries **date, source and source kind**. An authority release and
a newspaper article are both legitimate leads but do not carry the same
evidentiary weight, which is why official sources also get a higher
confidence. See [Running a search](03-searching.md#news--rss).

---

Next: **[Telegram tools →](05-telegram.md)** · Back: **[Searching](03-searching.md)**

## 14. Dating & adult — `dating`

**Off by default.** The operator enables it deliberately with
`ENABLE_DATING_SEARCH=true`; until then the module offers no tool.
Meant for specific leads such as sextortion, romance scams or trafficking.

> ⚠️ Whether someone has a profile on a dating or adult platform is
> information about their sex life — a special category of personal data.
> Search only with a concrete legal basis and purpose, and keep such cases
> restricted.

| Tool | Query type | What it does |
|------|-----------|--------------|
| `cupidcrawl` | `Username` | Sweeps ~50 dating/adult platforms for the username; every hit is verified against a negative control |

