"""
Operator-global API-key registry, store access and live validators.

ONE place defines every module API key. Adding a future key = append one
KeyDef to KEY_REGISTRY (+ optionally a validator). The Product-Owner
console Settings tab renders itself from `/platform/api-keys`, which is
built from this registry, so no frontend change is needed per new key.

Storage: license-server `platform-settings` (operator-global, survives
without editing .env). `load_keys()` merges the stored values over the
process .env as a fallback and caches briefly. The orchestrator passes
the merged dict to each module in the /run request (`options.credentials`)
so a saved key takes effect immediately, no container restart.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

log = logging.getLogger("osint.api_keys")


# ---- encryption at rest ---------------------------------------------
# API keys are stored ENCRYPTED in the license-server DB — the store only
# ever holds ciphertext, never plaintext. The Fernet key is derived from
# the framework master secret (API_SECRET_KEY), so only a holder of that
# secret can decrypt them. No new secret to manage, and the .env module
# keys become a pure fallback (the DB is the authoritative, encrypted
# source). Legacy plaintext rows decrypt to themselves (migration-safe).
#
# ⚠️ ROTATING API_SECRET_KEY INVALIDATES EVERY STORED KEY. The Fernet key is
# derived from it, so after a rotation none of the stored ciphertext can be
# decrypted any more. There is no re-encryption path: the old plaintext is
# unrecoverable and every key has to be re-entered in /glbadmin → Settings.
# Before rotating, collect the keys from their providers (or the panel, while
# the old secret is still in place). See docs/operations.en.md "Rotate .env secrets".

# Fernet tokens are base64 of a 0x80 version byte — always this prefix. Lets
# us tell a genuine legacy-plaintext row from a decrypt that actually FAILED.
_FERNET_PREFIX = "gAAAAA"


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.kek_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        # A row that LOOKS like ciphertext but won't decrypt is not legacy
        # plaintext — it is almost always API_SECRET_KEY having changed. Say
        # so loudly: returning the ciphertext as if it were the key makes
        # every tool fail with "key rejected", which sends people hunting the
        # provider instead of the secret. Never log the value itself.
        if value.startswith(_FERNET_PREFIX):
            log.error(
                "api_keys: stored value is Fernet ciphertext but cannot be "
                "decrypted — API_SECRET_KEY almost certainly changed. The key "
                "is unrecoverable and must be re-entered in /glbadmin → "
                "Settings. Tools using it will report 'key rejected'."
            )
        return value

# ---- registry -------------------------------------------------------


@dataclass(frozen=True)
class KeyDef:
    name: str            # env var name, also the storage key
    label: str           # human label in the UI
    module: str          # owning module (for grouping/enable hints)
    group: str           # UI section
    register_url: str    # where the operator obtains the key
    secret: bool = True  # masked in the UI + on GET
    help: str = ""
    validator: Optional[str] = None  # key into VALIDATORS; None = no live test


KEY_REGISTRY: list[KeyDef] = [
    # --- Leaks & breaches ---
    KeyDef("HIBP_API_KEY", "Have I Been Pwned", "leaks", "Leaks & Breaches",
           "https://haveibeenpwned.com/API/Key",
           help="Enables live breach lookups (else a deep-link is returned).",
           validator="hibp"),
    KeyDef("HUDSONROCK_API_KEY", "Hudson Rock (Infostealer)", "leaks",
           "Leaks & Breaches", "https://www.hudsonrock.com/cavalier",
           help="OPTIONAL. E-Mail/Domain/Username → infostealer infections "
                "(compromised machine, exfiltrated credentials). The tool "
                "already works keyless via the free osint-tools API; a key "
                "only raises rate limits / unlocks the full Cavalier API.",
           validator="hudsonrock"),
    # --- Threat intel ---
    KeyDef("VIRUSTOTAL_API_KEY", "VirusTotal", "threat", "Threat Intel",
           "https://www.virustotal.com/gui/my-apikey",
           help="Domain/IP/URL/hash reputation.", validator="virustotal"),
    KeyDef("ABUSEIPDB_API_KEY", "AbuseIPDB", "threat", "Threat Intel",
           "https://www.abuseipdb.com/account/api",
           help="IP abuse reputation score.", validator="abuseipdb"),
    KeyDef("URLHAUS_API_KEY", "URLhaus (abuse.ch)", "threat", "Threat Intel",
           "https://auth.abuse.ch/",
           help="abuse.ch Auth-Key for URLhaus (since 2024 required). Falls "
                "back to ABUSECH_API_KEY if that is set instead.",
           validator="urlhaus"),
    KeyDef("ABUSECH_API_KEY", "abuse.ch Auth-Key", "threat", "Threat Intel",
           "https://auth.abuse.ch/",
           help="One free key for ALL abuse.ch services — ThreatFox, "
                "MalwareBazaar and URLhaus. Enables IOC → malware/C2 "
                "attribution and hash → sample lookups.",
           validator="abusech"),
    KeyDef("OTX_API_KEY", "AlienVault OTX", "threat", "Threat Intel",
           "https://otx.alienvault.com/api", validator="otx",
           help="FREE. Open Threat Exchange (AlienVault/LevelBlue): community "
                "threat intel where indicators are grouped into named "
                "campaigns ('pulses') instead of arriving as loose IOCs. "
                "Register, then copy the key from Settings -> API Integration."),
    KeyDef("RANSOMWARE_LIVE_API_KEY", "ransomware.live (PRO)", "threat",
           "Threat Intel", "https://my.ransomware.live/",
           help="OPTIONAL and free. Without it `ransomware_watch` runs on the "
                "keyless v2 tier, which allows ONE request per minute per "
                "endpoint — too little for an orchestrator run that fires every "
                "tool of a module at once, so victim searches intermittently "
                "return a rate-limit note instead of results. A free PRO key "
                "removes the limit (500k calls/month) and the runner switches "
                "to the PRO host automatically.",
           validator="ransomware"),
    # --- AI function (KI-Verknüpfung) ---
    KeyDef("GEMINI_API_KEY", "Google Gemini (AI function)", "ai", "AI",
           "https://aistudio.google.com/apikey",
           help="Powers the licensable AI case-linking function. The key is "
                "passed to the editable n8n 'ai-link' workflow. ⚠️ With Gemini, "
                "case data leaves the sovereign boundary — enable the AI "
                "function per customer with their consent; a local model is the "
                "sovereign alternative later.",
           validator="gemini"),
    # --- Infrastructure ---
    KeyDef("SHODAN_API_KEY", "Shodan", "infra", "Infrastructure",
           "https://account.shodan.io/",
           help="Host intelligence (open ports, banners, product versions, "
                "CVEs) for IPs/domains, plus favicon-hash clustering — find "
                "every IP on the internet serving the same phishing/C2 favicon "
                "and collapse a spread-out kit onto one actor. Free membership "
                "includes a small monthly query credit.",
           validator="shodan"),
    # --- Crime forums / search ---
    KeyDef("BRAVE_API_KEY", "Brave Search API", "forums", "Search",
           "https://brave.com/search/api/",
           help="Robust clearnet crime-forum dorking (free tier ~2000/mo). "
                "Without it the forum hunt still runs the darknet (Tor) sweep; "
                "keyless clearnet search is blocked from datacenter IPs.",
           validator="brave"),
    # --- Compliance / sanctions ---
    KeyDef("OPENSANCTIONS_API_KEY", "OpenSanctions", "compliance", "Compliance",
           "https://www.opensanctions.org/api/",
           help="Sanctions / PEP / watchlist screening (OFAC, EU, UN, SECO …) "
                "for names, companies and crypto wallets. Or self-host yente "
                "(keyless) and set OPENSANCTIONS_BASE.",
           validator="opensanctions"),
    # --- Registers (Switzerland) ---
    KeyDef("ZEFIX_API_KEY", "ZEFIX (CH-Handelsregister, Web-Service)",
           "corporate", "Register (CH)",
           "https://www.zefix.admin.ch/de/search/entity/welcome",
           help="KOSTENLOS, aber Registrierung nötig. ⚠️ HTTP-Basic-Auth — "
                "der Wert ist ein `benutzer:passwort`-Paar, KEIN Token. "
                "Liefert den aktuellen Registerstand aller 26 kantonalen "
                "Handelsregister: Zweck, Kapital, frühere Firmennamen, "
                "Zweigniederlassungen, Übernahmen und Revisionsstelle. "
                "OHNE diesen Key bleibt `shab_registry` (keylos), das "
                "dieselben Firmen abdeckt — aber als veröffentlichte "
                "Ereignisse, nicht als aktuellen Zustand.",
           validator="zefix"),
    # --- Crypto ---
    KeyDef("ETHERSCAN_API_KEY", "Etherscan", "crypto", "Crypto",
           "https://etherscan.io/apis",
           help="Full ETH tx history (Blockscout is the keyless fallback).",
           validator="etherscan"),
    KeyDef("MISTTRACK_API_KEY", "MistTrack (Wallet-Attribution, kostenpflichtig)",
           "crypto", "Crypto",
           "https://dashboard.misttrack.io/apikeys",
           help="OPTIONAL, KOSTENPFLICHTIG. BTC/ETH-Wallet → Entitätslabels "
                "(Börse/Mixer/bekannter Scam- oder Ransomware-Cluster), "
                "Risikoscore, Gegenparteien und Auszahlungspunkt. "
                "⚠️ Der freie Tarif wurde eingestellt (Stand 2026) — "
                "die OpenAPI braucht Standard/Compliance/Developer. "
                "OHNE diesen Key bleiben abgedeckt: `address_risk` (GoPlus, "
                "keyless, EVM-Risiko), `sanctions_screen` (OFAC-designierte "
                "Wallets, 8 Ketten) und `ransomlook_crypto`. Nur "
                "Gegenpartei-Analyse und Auszahlungskette fehlen dann.",
           validator="misttrack"),
    # --- Telegram (credentials; the session is validated via the module) ---
    KeyDef("TELEGRAM_API_ID", "Telegram API ID", "messenger", "Telegram",
           "https://my.telegram.org/apps", secret=False,
           help="From my.telegram.org → API development tools."),
    KeyDef("TELEGRAM_API_HASH", "Telegram API Hash", "messenger", "Telegram",
           "https://my.telegram.org/apps",
           help="From my.telegram.org → API development tools."),
    KeyDef("TELEGRAM_SESSION", "Telegram StringSession", "messenger", "Telegram",
           "https://my.telegram.org/apps",
           help="Paste a pre-generated Telethon StringSession "
                "(scripts/telegram-session.py). Unlocks authenticated collection."),
    # --- Google account OSINT (GHunt) ---
    KeyDef("GHUNT_CREDS", "GHunt Google Session", "leaks", "Google",
           "https://github.com/mxrch/GHunt",
           help="Paste the Android MASTER TOKEN (starts with 'aas_et/…') of a "
                "DEDICATED BURNER Google account — get it by running "
                "scripts/ghunt-session.py (it walks you through `ghunt login` "
                "and prints the token). The full base64 creds.m is also "
                "accepted. Unlocks email → Google-account OSINT (display name, "
                "Gaia ID, profile pictures, Maps reviews). The master token is "
                "long-lived (only dies if the account revokes it); the tool "
                "degrades to a clean 'not configured' error otherwise. ⚠️ Use a "
                "throwaway account — GHunt operates AS it.",
           validator="ghunt"),
    # --- Discord (deep user profile via CordCat-style bot lookup) ---
    KeyDef("DISCORD_BOT_TOKEN", "Discord Bot Token", "messenger", "Discord",
           "https://discord.com/developers/applications",
           help="A Discord BOT token (Developer Portal → your app → Bot → "
                "Reset Token). Unlocks the 'Discord deep' tool: a user ID → "
                "full public profile (username, global name, avatar/banner, "
                "badges from public_flags, bot/system flags) via the official "
                "GET /users/{id} endpoint — ToS-compliant, read-only. Without "
                "it the keyless snowflake decode (creation date) still works.",
           validator="discord"),
]

REGISTRY_BY_NAME = {k.name: k for k in KEY_REGISTRY}


def masked(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••"
    return f"{value[:4]}…{value[-4:]}"


# ---- store access (license-server) ----------------------------------

_cache: dict[str, tuple[float, dict[str, str]]] = {}
_TTL = 20.0


async def _fetch_stored() -> dict[str, str]:
    url = f"{settings.license_server_url}/api/v1/platform-settings"
    headers = {"X-Internal-Key": settings.internal_secret}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json() or {}


async def load_keys(force: bool = False) -> dict[str, str]:
    """Merged effective keys: stored value wins, else the .env value.
    Cached briefly; `force` (or invalidate()) bypasses the cache."""
    now = time.time()
    if not force and "keys" in _cache and now - _cache["keys"][0] < _TTL:
        return _cache["keys"][1]
    try:
        raw = await _fetch_stored()
        stored = {k: _decrypt(v) for k, v in raw.items()}
    except Exception:  # noqa: BLE001 — degrade to .env-only if store is down
        stored = {}
    merged: dict[str, str] = {}
    for kd in KEY_REGISTRY:
        merged[kd.name] = (stored.get(kd.name) or "").strip() or os.environ.get(kd.name, "").strip()
    _cache["keys"] = (now, merged)
    return merged


def invalidate() -> None:
    _cache.pop("keys", None)


async def save_keys(values: dict[str, str]) -> None:
    """Persist only known registry keys. An empty string clears a key
    (module then falls back to .env)."""
    # Encrypt every non-empty value before it leaves the backend; an empty
    # string clears the key (stored as-is so the module falls back to .env).
    clean: dict[str, str] = {}
    for k, v in values.items():
        if k not in REGISTRY_BY_NAME:
            continue
        # Trim on the way in, matching validate_key: a pasted key with a
        # trailing newline would otherwise be stored, and the masked preview
        # would show a value that differs from the one that was tested.
        v = (v or "").strip()
        clean[k] = _encrypt(v) if v else ""
    url = f"{settings.license_server_url}/api/v1/platform-settings"
    headers = {"X-Internal-Key": settings.internal_secret}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.put(url, headers=headers, json={"values": clean})
        r.raise_for_status()
    invalidate()


async def describe() -> list[dict]:
    """UI-facing view: registry metadata + set/effective flags. Never
    returns secret values in clear — only a mask and an is_set flag."""
    keys = await load_keys(force=True)
    stored: dict[str, str] = {}
    try:
        stored = await _fetch_stored()
    except Exception:  # noqa: BLE001
        pass
    out = []
    for kd in KEY_REGISTRY:
        effective = keys.get(kd.name, "")
        out.append({
            "name": kd.name,
            "label": kd.label,
            "module": kd.module,
            "group": kd.group,
            "register_url": kd.register_url,
            "help": kd.help,
            "secret": kd.secret,
            "testable": kd.validator is not None,
            "is_set": bool(effective),
            "from_env": bool(effective) and not (stored.get(kd.name) or "").strip(),
            "preview": masked(effective) if kd.secret else effective,
        })
    return out


# ---- live validators ------------------------------------------------

Result = dict  # {"valid": bool, "message": str}


async def _v_hibp(v: str) -> Result:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://haveibeenpwned.com/api/v3/breachedaccount/test@example.com",
                        headers={"hibp-api-key": v, "user-agent": "OOF"})
    if r.status_code in (200, 404):
        return {"valid": True, "message": "Key accepted (HTTP %s)." % r.status_code}
    if r.status_code == 401:
        return {"valid": False, "message": "Invalid key (401 Unauthorized)."}
    return {"valid": False, "message": f"Unexpected HTTP {r.status_code}."}


async def _v_virustotal(v: str) -> Result:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://www.virustotal.com/api/v3/domains/google.com",
                        headers={"x-apikey": v})
    if r.status_code == 200:
        return {"valid": True, "message": "Key accepted."}
    if r.status_code == 401:
        return {"valid": False, "message": "Invalid key (401)."}
    if r.status_code == 429:
        return {"valid": True, "message": "Key valid but rate-limited (429)."}
    return {"valid": False, "message": f"Unexpected HTTP {r.status_code}."}


async def _v_abuseipdb(v: str) -> Result:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://api.abuseipdb.com/api/v2/check",
                        params={"ipAddress": "8.8.8.8", "maxAgeInDays": "30"},
                        headers={"Key": v, "Accept": "application/json"})
    if r.status_code == 200:
        remaining = r.headers.get("X-RateLimit-Remaining")
        extra = f" Quota remaining: {remaining}." if remaining else ""
        return {"valid": True, "message": "Key accepted." + extra}
    if r.status_code == 401:
        return {"valid": False, "message": "Invalid key (401)."}
    return {"valid": False, "message": f"Unexpected HTTP {r.status_code}."}


async def _v_urlhaus(v: str) -> Result:
    # abuse.ch key auth: a valid Auth-Key is accepted on the v1 host lookup.
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post("https://urlhaus-api.abuse.ch/v1/host/",
                         headers={"Auth-Key": v}, data={"host": "google.com"})
    if r.status_code == 200:
        return {"valid": True, "message": "Key accepted (abuse.ch reachable)."}
    if r.status_code in (401, 403):
        return {"valid": False, "message": f"Invalid Auth-Key (HTTP {r.status_code})."}
    return {"valid": False, "message": f"Unexpected HTTP {r.status_code}."}


async def _v_etherscan(v: str) -> Result:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://api.etherscan.io/v2/api",
                        params={"chainid": "1", "module": "stats",
                                "action": "ethprice", "apikey": v})
    if r.status_code != 200:
        return {"valid": False, "message": f"HTTP {r.status_code}."}
    data = r.json()
    if str(data.get("status")) == "1":
        return {"valid": True, "message": "Key accepted."}
    return {"valid": False, "message": str(data.get("result") or data.get("message") or "Invalid key.")}


async def _v_abusech(v: str) -> Result:
    # One abuse.ch Auth-Key covers all their services; validate it against
    # the ThreatFox API (a valid key returns 200 even with no IOC match).
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post("https://threatfox-api.abuse.ch/api/v1/",
                         headers={"Auth-Key": v},
                         json={"query": "search_ioc", "search_term": "1.1.1.1"})
    if r.status_code == 200:
        return {"valid": True, "message": "Auth-Key accepted (abuse.ch reachable)."}
    if r.status_code in (401, 403):
        return {"valid": False, "message": f"Invalid Auth-Key (HTTP {r.status_code})."}
    return {"valid": False, "message": f"Unexpected HTTP {r.status_code}."}


async def _v_opensanctions(v: str) -> Result:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://api.opensanctions.org/search/default",
                        params={"q": "test", "limit": "1"},
                        headers={"Authorization": f"ApiKey {v}"})
    if r.status_code == 200:
        return {"valid": True, "message": "Key accepted."}
    if r.status_code in (401, 403):
        return {"valid": False, "message": f"Invalid key (HTTP {r.status_code})."}
    return {"valid": False, "message": f"Unexpected HTTP {r.status_code}."}


async def _v_misttrack(v: str) -> Result:
    # A known address; a valid key returns success=true, a bad key 401/403.
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://openapi.misttrack.io/v1/risk_score",
                        params={"coin": "ETH",
                                "address": "0x0000000000000000000000000000000000000000",
                                "api_key": v})
    if r.status_code in (401, 403):
        return {"valid": False, "message": f"Key refused (HTTP {r.status_code})."}
    if r.status_code == 200:
        try:
            j = r.json()
        except ValueError:
            return {"valid": False, "message": "Non-JSON response."}
        # MistTrack signals a bad key via success=false + a message too.
        if j.get("success") is False and "key" in str(j.get("msg", "")).lower():
            return {"valid": False, "message": str(j.get("msg"))}
        return {"valid": True, "message": "Key accepted (MistTrack reachable)."}
    if r.status_code == 429:
        return {"valid": True, "message": "Key valid but rate-limited (429)."}
    return {"valid": False, "message": f"Unexpected HTTP {r.status_code}."}


async def _v_hudsonrock(v: str) -> Result:
    # Hudson Rock's osint-tools API is keyless, so a key can't be rejected
    # with a 401 there. We confirm the service is reachable and that the
    # key (sent as `api-key`) is not actively refused. A dedicated full
    # Cavalier endpoint would 401 a bad key; the free path cannot.
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-email",
                        params={"email": "test@example.com"},
                        headers={"api-key": v, "User-Agent": "OOF"})
    if r.status_code in (401, 403):
        return {"valid": False, "message": f"Key refused (HTTP {r.status_code})."}
    if r.status_code == 200:
        return {"valid": True, "message": "Hudson Rock reachable, key accepted "
                                          "(free API is keyless — the tool also runs without a key)."}
    if r.status_code == 429:
        return {"valid": True, "message": "Reachable but rate-limited (429)."}
    return {"valid": False, "message": f"Unexpected HTTP {r.status_code}."}


async def _v_gemini(v: str) -> Result:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://generativelanguage.googleapis.com/v1beta/models",
                        params={"key": v})
    if r.status_code == 200:
        return {"valid": True, "message": "Key accepted (Gemini reachable)."}
    if r.status_code in (400, 401, 403):
        return {"valid": False, "message": f"Invalid key (HTTP {r.status_code})."}
    return {"valid": False, "message": f"Unexpected HTTP {r.status_code}."}


async def _v_shodan(v: str) -> Result:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://api.shodan.io/api-info", params={"key": v})
    if r.status_code == 200:
        try:
            j = r.json()
            return {"valid": True, "message": "Key accepted (plan: %s, query "
                    "credits: %s)." % (j.get("plan", "?"), j.get("query_credits"))}
        except ValueError:
            return {"valid": True, "message": "Key accepted."}
    if r.status_code == 401:
        return {"valid": False, "message": "Invalid key (401 Unauthorized)."}
    return {"valid": False, "message": f"Unexpected HTTP {r.status_code}."}


async def _v_brave(v: str) -> Result:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://api.search.brave.com/res/v1/web/search",
                        params={"q": "test", "count": "1"},
                        headers={"X-Subscription-Token": v, "Accept": "application/json"})
    if r.status_code == 200:
        return {"valid": True, "message": "Key accepted."}
    if r.status_code in (401, 403):
        return {"valid": False, "message": f"Invalid key (HTTP {r.status_code})."}
    if r.status_code == 429:
        return {"valid": True, "message": "Key valid but rate-limited (429)."}
    return {"valid": False, "message": f"Unexpected HTTP {r.status_code}."}


async def _v_discord(v: str) -> Result:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://discord.com/api/v10/users/@me",
                        headers={"Authorization": f"Bot {v}"})
    if r.status_code == 200:
        try:
            j = r.json()
            return {"valid": True, "message": "Token accepted (bot: %s)." %
                    (j.get("username", "?"))}
        except ValueError:
            return {"valid": True, "message": "Token accepted."}
    if r.status_code == 401:
        return {"valid": False, "message": "Invalid bot token (401 Unauthorized)."}
    return {"valid": False, "message": f"Unexpected HTTP {r.status_code}."}


async def _v_ransomware(v: str) -> Result:
    # ransomware.live PRO publishes a dedicated /validate route, which is what
    # this must use: it is the provider's own answer to "is this key good",
    # and it distinguishes the failure modes itself ("Missing X-API-KEY
    # header" 401 vs "Invalid API key" 403). Testing some data endpoint
    # instead cannot tell a bad key from a route the plan does not include.
    # The provider's message is passed through verbatim — the operator can act
    # on "Invalid API key" but not on a bare status code.
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://api-pro.ransomware.live/validate",
                        headers={"X-API-KEY": v, "Accept": "application/json"})
    detail = ""
    try:
        body = r.json()
        if isinstance(body, dict):
            detail = str(body.get("message") or body.get("detail") or "").strip()
    except ValueError:
        detail = (r.text or "").strip()[:120]

    if r.status_code == 200:
        return {"valid": True, "message": "Key accepted" + (f" — {detail}." if detail else ".")}
    if r.status_code in (401, 403):
        hint = (" Note that the key must be the API key from "
                "my.ransomware.live → API, not your account password, and it "
                "is only issued once the account's e-mail is confirmed.")
        return {"valid": False,
                "message": f"Key refused (HTTP {r.status_code})"
                           + (f": {detail}." if detail else ".") + hint}
    if r.status_code == 429:
        return {"valid": True, "message": "Key valid but rate-limited (429)."}
    return {"valid": False,
            "message": f"Unexpected HTTP {r.status_code}" + (f": {detail}" if detail else ".")}


async def _v_otx(v: str) -> Result:
    """AlienVault/LevelBlue OTX. `/user/me` is the cheapest authenticated
    call and it returns the account, so the operator sees WHICH account the
    key belongs to rather than a bare "valid"."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://otx.alienvault.com/api/v1/user/me",
                        headers={"X-OTX-API-KEY": v})
    if r.status_code == 200:
        try:
            who = r.json().get("username") or "?"
        except Exception:  # noqa: BLE001
            who = "?"
        return {"valid": True, "message": f"OTX key accepted (account: {who})."}
    if r.status_code in (401, 403):
        return {"valid": False, "message": "OTX rejected the key."}
    return {"valid": False, "message": f"OTX returned HTTP {r.status_code}."}


async def _v_zefix(v: str) -> Result:
    """ZEFIX web service. HTTP Basic — measured: the service answers an
    unauthenticated call with `401 WWW-Authenticate: Basic realm=
    "ZefixPublicREST"`, so the credential is a user:password pair.

    The search route is used rather than a data lookup because it is the
    cheapest call that still requires auth, and a colon-less value is called
    out here: that is the mistake an operator pasting a "key" will make, and
    a bare 401 would not tell them.
    """
    if ":" not in v:
        return {"valid": False,
                "message": "ZEFIX uses HTTP Basic auth — the value must be "
                           "`username:password`, not a single token."}
    token = base64.b64encode(v.encode()).decode()
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            "https://www.zefix.admin.ch/ZefixPublicREST/api/v1/company/search",
            json={"name": "Migros"},
            headers={"Authorization": f"Basic {token}",
                     "Accept": "application/json"})
    if r.status_code == 200:
        try:
            n = len(r.json() or [])
        except ValueError:
            n = 0
        return {"valid": True, "message": f"Credentials accepted ({n} test hits)."}
    if r.status_code in (401, 403):
        return {"valid": False,
                "message": f"ZEFIX refused the credentials (HTTP {r.status_code}). "
                           "Register the web service at zefix.admin.ch and use the "
                           "issued `username:password`."}
    if r.status_code == 429:
        return {"valid": True, "message": "Credentials valid but rate-limited (429)."}
    return {"valid": False, "message": f"Unexpected HTTP {r.status_code}."}


VALIDATORS: dict[str, Callable] = {
    "zefix": _v_zefix,
    "otx": _v_otx,
    "ransomware": _v_ransomware,
    "discord": _v_discord,
    "hibp": _v_hibp,
    "virustotal": _v_virustotal,
    "abuseipdb": _v_abuseipdb,
    "urlhaus": _v_urlhaus,
    "etherscan": _v_etherscan,
    "abusech": _v_abusech,
    "opensanctions": _v_opensanctions,
    "brave": _v_brave,
    "hudsonrock": _v_hudsonrock,
    "misttrack": _v_misttrack,
    "shodan": _v_shodan,
    "gemini": _v_gemini,
}


async def validate_key(name: str, value: str) -> Result:
    kd = REGISTRY_BY_NAME.get(name)
    if not kd:
        return {"valid": False, "message": f"Unknown key {name}."}
    # Trim before testing. A pasted key routinely carries a trailing newline or
    # a leading space, and an untrimmed value goes into an HTTP header — which
    # fails with "Illegal header value" rather than anything the operator could
    # act on. `save_keys` stores what the field holds, so testing the trimmed
    # form also matches what `credential()` resolves at run time.
    value = (value or "").strip()
    if not value:
        return {"valid": False, "message": "No value to test."}
    # GHunt is validated by the leaks module (it has ghunt), not a plain
    # provider HTTP call — route it there.
    if name == "GHUNT_CREDS":
        return await validate_ghunt(value)
    fn = VALIDATORS.get(kd.validator or "")
    if not fn:
        return {"valid": False, "message": "This key has no live validator."}
    try:
        return await fn(value)
    except httpx.TimeoutException:
        return {"valid": False, "message": "Timed out contacting the provider."}
    except Exception as e:  # noqa: BLE001
        return {"valid": False, "message": f"Test error: {type(e).__name__}: {e}"}


async def validate_telegram(api_id: str, api_hash: str, session: str) -> Result:
    """Proxy to module-messenger, which has Telethon and can actually open
    the session. Returns {valid, message, account?}."""
    url = f"{settings.module_messenger_url}/validate-telegram"
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, json={"api_id": api_id, "api_hash": api_hash,
                                        "session": session})
            if r.status_code != 200:
                return {"valid": False, "message": f"Module HTTP {r.status_code}."}
            return r.json()
    except Exception as e:  # noqa: BLE001
        return {"valid": False, "message": f"Could not reach messenger module: {e}"}


async def validate_ghunt(creds: str) -> Result:
    """Proxy to module-leaks (it has ghunt) to check a Google session's
    master token. Accepts a master token or base64 creds.m."""
    url = f"{settings.module_leaks_url}/validate-ghunt"
    try:
        async with httpx.AsyncClient(timeout=40) as c:
            r = await c.post(url, json={"creds": creds})
            if r.status_code != 200:
                return {"valid": False, "message": f"Module HTTP {r.status_code}."}
            return r.json()
    except Exception as e:  # noqa: BLE001
        return {"valid": False, "message": f"Could not reach leaks module: {e}"}


async def derive_ghunt(companion: str) -> dict:
    """Proxy to module-leaks: turn a GHunt Companion base64 blob / oauth_token
    into a long-lived master token (server-side `ghunt login`)."""
    url = f"{settings.module_leaks_url}/ghunt/derive"
    try:
        async with httpx.AsyncClient(timeout=40) as c:
            r = await c.post(url, json={"companion": companion})
            if r.status_code != 200:
                return {"ok": False, "message": f"Module HTTP {r.status_code}."}
            return r.json()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"Could not reach leaks module: {e}"}
