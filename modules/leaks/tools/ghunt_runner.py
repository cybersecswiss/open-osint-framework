"""
GHunt (mxrch/GHunt) — Google-account OSINT for an email address or Gaia ID.

Runs GHunt's Python API in-process (not the CLI) so we can:
  * force cookie regeneration from the master token — GHunt's own
    `check_and_gen` skips it because `check_cookies` wrongly accepts our
    placeholder cookies, which left the lookup without the SAPISID cookie;
  * support BOTH selectors: email (people_lookup) and gaia id (people),
    since the `ghunt gaia` CLI is disabled upstream.

Credential (operator-global, Global-Admin → Settings → Google): GHUNT_CREDS =
the Android master token (aas_et/…) of a DEDICATED BURNER account, or a full
base64 creds.m. Emits a `google_account` node (name, Gaia ID, profile photo)
linked to the searched email/gaia.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime

from schemas import EdgeResult, Finding, NOTE_PREFIX, credential

log = logging.getLogger("module-leaks.ghunt")


_PROFILE_PATHS = [
    "person.metadata.best_display_name", "person.photo", "person.cover_photo",
    "person.interaction_settings", "person.legacy_fields", "person.metadata",
    "person.in_app_reachability", "person.name", "person.read_only_profile_info",
    "person.sort_keys", "person.email",
]
_PROFILE_CONTAINERS = [
    "AFFINITY", "PROFILE", "DOMAIN_PROFILE", "ACCOUNT", "EXTERNAL_ACCOUNT",
    "CIRCLE", "DOMAIN_CONTACT", "DEVICE_CONTACT", "GOOGLE_GROUP", "CONTACT",
]
_EXT = ["DYNAMITE_ADDITIONAL_DATA", "DYNAMITE_ORGANIZATION_INFO"]


async def _fetch_profile_raw(people, client, value: str, is_gaia: bool) -> dict:
    """Fetch the full max_details People profile as RAW JSON and return the
    person_data dict — bypassing GHunt's Person parser, which crashes on
    cover photos (KeyError 'container'). The endpoint must already be loaded
    (call people_lookup/people with just_name first)."""
    if is_gaia:
        params = {"person_id": value, "extension_set.extension_names": _EXT,
                  "request_mask.include_field.paths": _PROFILE_PATHS,
                  "request_mask.include_container": _PROFILE_CONTAINERS,
                  "core_id_params.enable_private_names": True}
        req = await people._query("people", client, "/v2/people", params=params)
    else:
        params = {"id": value, "type": "EMAIL", "match_type": "EXACT",
                  "extension_set.extension_names": _EXT,
                  "request_mask.include_field.paths": _PROFILE_PATHS,
                  "request_mask.include_container": _PROFILE_CONTAINERS,
                  "core_id_params.enable_private_names": True}
        req = await people._query("people_lookup", client, "/v2/people/lookup", params=params)
    try:
        data = json.loads(req.text)
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(data, dict):
        return {}
    # email path: {"people": {gaia: {...person...}}}
    if data.get("people"):
        return list(data["people"].values())[0]
    # gaia path: {"personResponse": [{"person": {...}}]}
    pr = data.get("personResponse")
    if isinstance(pr, list) and pr:
        return pr[0].get("person") or {}
    return {}


def _gi(arr, *idx):
    """Safe nested index into Google's protobuf-ish arrays; None on any miss."""
    cur = arr
    for i in idx:
        try:
            cur = cur[i]
        except (IndexError, KeyError, TypeError):
            return None
    return cur


# Rich `pb` string the live maps/contrib reviews page sends to the `mas`
# endpoint (captured from the live page). {gaia} = target Gaia ID, {tok} = a maps page
# token (GHunt's fixed one works for these preview calls). This returns the
# actual reviewed places (unlike GHunt's stripped stats template).
_REVIEWS_PB = (
    "%211s{gaia}%212m3%211s{tok}%217e81%2115i14414%216m2%214b1%217b1%2110m5"
    "%211b1%215b1%219m1%211e3%2111b1%2114m60%211m49%211m5%211m4%211e1%211e3"
    "%211e2%211e4%213m5%212m4%213m3%211m2%211i260%212i365%214m1%213i10%2110b1"
    "%2111m33%211m3%211e1%212b0%213e3%211m3%211e2%212b1%213e2%211m3%211e2%212b0"
    "%213e3%211m3%211e8%212b0%213e3%211m3%211e10%212b0%213e3%211m3%211e10%212b1"
    "%213e2%211m3%211e10%212b0%213e4%211m3%211e9%212b1%213e2%212b1%212m5%211e1"
    "%211e4%211e5%211e3%211e2%213b1%214b1%215m1%211e1%2117m28%211m6%211m2%211i0"
    "%212i0%212m2%211i530%212i768%211m6%211m2%211i974%212i0%212m2%211i1024"
    "%212i768%211m6%211m2%211i0%212i0%212m2%211i1024%212i20%211m6%211m2%211i0"
    "%212i748%212m2%211i1024%212i768%2118m8%211m3%211d6704485.999343019"
    "%212d7.2025119%213d51.6227278%213m2%211i1024%212i768%214f13.1%2141m14"
    "%211i10%212m9%212b1%213b1%215b1%217b1%2112m4%211b1%212b1%214m1%211e1"
    "%217m2%211m1%211e1"
)
_FIXED_TOK = "YE3rYc2rEsqOlwSHx534DA"


async def _fetch_reviews(client, gaia_id: str, cap: int = 80) -> list[dict]:
    """Extract a target's public Google-Maps reviews (place + coordinates)
    via the live maps `mas` endpoint with the real (rich) pb string captured
    from the maps/contrib reviews page. Returns the reviewed places."""
    pb = _REVIEWS_PB.format(gaia=gaia_id, tok=_FIXED_TOK)
    url = f"https://www.google.com/locationhistory/preview/mas?authuser=0&hl=en&gl=us&pb={pb}"
    try:
        r = await client.get(url)
        if r.status_code != 200:
            return []
        data = json.loads(r.text[5:])  # strip )]}'\n
    except Exception:  # noqa: BLE001
        return []
    result = {"reviews": [], "photos": [], "name": "", "counts": {}}
    # The Maps response also carries the display name + review/rating/photo
    # counts (the People API often returns an empty name for map contributors).
    result["name"] = _gi(data, 16, 0) or ""
    counts_sec = _gi(data, 16, 8, 0)
    if isinstance(counts_sec, list):
        result["counts"] = {s[6]: s[7] for s in counts_sec
                            if isinstance(s, list) and len(s) > 7}
    rows = _gi(data, 45, 0)
    for rd in (rows or []):
        loc = _gi(rd, 4)
        if not loc:
            continue
        pos = _gi(loc, 0)
        name = _gi(loc, 2)
        if not name:
            continue
        # Review timestamp lives at rd[2][1][3] in microseconds.
        micros = _gi(rd, 2, 1, 3)
        date_iso = ""
        if isinstance(micros, (int, float)) and micros > 0:
            try:
                date_iso = datetime.utcfromtimestamp(micros / 1_000_000).isoformat() + "Z"
            except (ValueError, OverflowError, OSError):
                date_iso = ""
        result["reviews"].append({
            "name": name, "address": _gi(loc, 3),
            "lat": _gi(pos, 2), "lon": _gi(pos, 3),
            "rating": _gi(rd, 2, 2, 0, 0),
            "comment": _gi(rd, 2, 2, 15, 0, 0),
            "date": date_iso,
        })
        if len(result["reviews"]) >= cap:
            break
    # Contributed photos live at data[22][1]: url + place + coords + date.
    for pd_ in (_gi(data, 22, 1) or []):
        loc = _gi(pd_, 1)
        url = _gi(pd_, 0, 6, 0)
        url = str(url).split("=")[0] if url else ""
        dparts = _gi(pd_, 0, 21, 6, 8)
        pdate = ""
        if isinstance(dparts, list) and len(dparts) >= 3:
            try:
                pdate = f"{int(dparts[0]):04d}-{int(dparts[1]):02d}-{int(dparts[2]):02d}"
            except (ValueError, TypeError):
                pdate = ""
        result["photos"].append({
            "name": _gi(loc, 2), "address": _gi(loc, 3),
            "lat": _gi(loc, 0, 2), "lon": _gi(loc, 0, 3),
            "url": url, "date": pdate,
        })
        if len(result["photos"]) >= cap:
            break
    return result


def _parse_profile(pd: dict) -> dict:
    """Extract the interesting fields from a raw max_details person_data."""
    md = pd.get("metadata") or {}
    bdn = md.get("bestDisplayName") or {}
    photos = pd.get("photo") or []
    covers = pd.get("coverPhoto") or []
    photo = next((p.get("url") for p in photos if p.get("url")), "")
    photo_default = next((p.get("isDefault") for p in photos if p.get("url")), None)
    cover = next((c.get("url") for c in covers if c.get("url")), "")
    src = (md.get("identityInfo") or {}).get("sourceIds") or []
    last_edit = (src[0].get("lastUpdated") if src else "") or ""
    # extendedData → Google Chat presence + account type (personal vs Workspace).
    ded = (pd.get("extendedData") or {}).get("dynamiteExtendedData") or {}
    org = ded.get("organizationInfo") or {}
    customer = org.get("customerInfo") or {}
    is_workspace = bool(customer)
    org_name = (customer.get("customerName") or customer.get("organizationName")
                or customer.get("domain") or "")
    return {
        "name": bdn.get("displayName") or "",
        "profile_photo": photo, "photo_is_default": photo_default,
        "cover_photo": cover, "last_profile_edit": last_edit,
        "user_type": md.get("ownerUserType") or [],
        "profile_url": f"https://www.google.com/maps/contrib/{pd.get('personId','')}",
        "chat_presence": ded.get("presence") or "",
        "chat_dnd_state": ded.get("dndState") or "",
        "entity_type": ded.get("entityType") or "",
        "account_type": "workspace" if is_workspace else "personal",
        "organization": org_name,
    }


def _walk_first(obj, keys: set[str]):
    """Depth-first search for the first value under any of `keys`."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and v not in (None, "", [], {}):
                return v
        for v in obj.values():
            r = _walk_first(v, keys)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _walk_first(v, keys)
            if r is not None:
                return r
    return None


async def run_ghunt(
    query: str, options: dict | None = None, job_id: str = "adhoc",
    query_type: str = "email",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    is_gaia = query_type in ("gaia", "gaia_id")
    value = (query or "").strip()
    if not value or (not is_gaia and "@" not in value):
        return [], [], ["ghunt: a valid email address (or Gaia ID) is required"]

    raw_cred = (credential(options, "GHUNT_CREDS") or "").strip()
    if not raw_cred:
        return [], [], [
            "GHUNT_CREDS not configured. Set it in Global-Admin → Settings → "
            "Google (master token of a burner account). Google account OSINT "
            "stays off until then."
        ]

    if raw_cred.startswith("aas_et/"):
        creds_b64 = base64.b64encode(json.dumps({
            "cookies": {"a": "a"}, "osids": {"a": "a"},
            "android": {"master_token": raw_cred, "authorization_tokens": {}},
        }).encode()).decode()
    else:
        creds_b64 = raw_cred

    home = tempfile.mkdtemp(prefix="ghunt_home_")
    cdir = os.path.join(home, ".malfrats", "ghunt")
    os.makedirs(cdir, exist_ok=True)
    creds_path = os.path.join(cdir, "creds.m")
    with open(creds_path, "w", encoding="utf-8") as f:
        f.write(creds_b64)

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []
    try:
        from ghunt.helpers import auth
        from ghunt.helpers.utils import get_httpx_client
        from ghunt.objects.base import GHuntCreds
        from ghunt.apis.peoplepa import PeoplePaHttp
        from ghunt.objects.encoders import GHuntEncoder

        client = get_httpx_client()
        try:
            creds = GHuntCreds(creds_path)
            creds.load_creds(silent=True)
            # FORCE cookie+OSID regeneration from the master token (GHunt's own
            # check would skip this and leave SAPISID missing).
            try:
                await auth.gen_cookies_and_osids(client, creds)
            except Exception as e:  # noqa: BLE001
                return [], [], [
                    f"GHunt could not regenerate a Google session from the "
                    f"master token ({type(e).__name__}: {e}). The token may be "
                    "revoked, or Google is blocking session creation from this "
                    "server's IP."]
            if "SAPISID" not in (creds.cookies or {}):
                return [], [], [
                    "GHunt got a Google session but without the SAPISID cookie "
                    "— Google is likely rate-limiting/blocking cookie creation "
                    "from this server's IP. Try again later or from another IP."]

            # NB: params_template="max_details" crashes GHunt's own parser on
            # accounts with a cover photo (KeyError 'container', parsers/
            # people.py). "just_name" returns name + Gaia ID without cover
            # photos → stable.
            people = PeoplePaHttp(creds)
            if is_gaia:
                is_found, target = await people.people(client, value, params_template="just_name")
            else:
                is_found, target = await people.people_lookup(client, value, params_template="just_name")

            if not is_found or target is None:
                kind = "Gaia ID" if is_gaia else "email"
                errors.append(f"No Google account found for this {kind} "
                              f"('{value}') — or the profile is private.")
                return findings, edges, errors

            data = json.loads(json.dumps(target, cls=GHuntEncoder))
            gaia = str(_walk_first(data, {"personId"}) or (value if is_gaia else ""))
            # Full profile via RAW max_details (bypasses GHunt's crashing parser).
            profile_raw = {}
            try:
                profile_raw = await _fetch_profile_raw(people, client, value, is_gaia)
            except Exception:  # noqa: BLE001
                profile_raw = {}
            # Public Maps reviews (place → coordinates) + the display name +
            # review/rating/photo counts that the Maps response carries.
            try:
                rev = await _fetch_reviews(client, gaia) if gaia else {}
            except Exception:  # noqa: BLE001
                rev = {}
            reviews = (rev or {}).get("reviews") or []
            # Public-calendar probe (email only): does the target expose one?
            cal_found, cal_count = False, 0
            if not is_gaia:
                try:
                    from ghunt.helpers import calendar as gcal
                    res = await gcal.fetch_all(creds, client, value)
                    if isinstance(res, tuple) and res:
                        cal_found = bool(res[0])
                        ev = res[2] if len(res) > 2 else None
                        items = getattr(ev, "items", None)
                        cal_count = len(items) if items else 0
                except Exception:  # noqa: BLE001
                    cal_found, cal_count = False, 0
        finally:
            await client.aclose()

        prof = _parse_profile(profile_raw) if profile_raw else {}
        # Name: profile bestDisplayName → Maps display name → GHunt just_name.
        name = (prof.get("name") or (rev or {}).get("name")
                or _walk_first(data, {"fullname", "displayName"}) or "")
        photo = prof.get("profile_photo") or _walk_first(data, {"url"}) or ""
        maps_url = prof.get("profile_url") or (
            f"https://www.google.com/maps/contrib/{gaia}" if gaia else "")
        label = value if not is_gaia else (gaia or value)

        findings.append(Finding(
            entity_type="google_account", platform="google",
            label=label, url=photo or maps_url or None, confidence=0.8,
            data={
                "email": (value if not is_gaia else ""),
                "name": name, "gaia_id": gaia,
                "profile_photo": photo,
                "photo_is_default": prof.get("photo_is_default"),
                "cover_photo": prof.get("cover_photo") or "",
                "last_profile_edit": prof.get("last_profile_edit") or "",
                "user_type": prof.get("user_type") or [],
                "account_type": prof.get("account_type") or "",
                "organization": prof.get("organization") or "",
                "chat_presence": prof.get("chat_presence") or "",
                "chat_dnd_state": prof.get("chat_dnd_state") or "",
                "entity_type": prof.get("entity_type") or "",
                "has_public_calendar": cal_found,
                "calendar_events": cal_count,
                "maps_profile_url": maps_url,
                "review_counts": (rev or {}).get("counts") or {},
                "query_type": query_type, "source": "ghunt",
            },
        ))
        edges.append(EdgeResult(from_entity=f"{query_type}:{value.lower()}",
                                to_entity=f"google_account:{label}",
                                relation="google_account_of", confidence=0.8))
        counts = (rev or {}).get("counts") or {}
        errors.append(f"{NOTE_PREFIX}GHunt account: "
                      + (f"{name}, " if name else "")
                      + f"Gaia {gaia}"
                      + (f", {counts}" if counts else ""))

        # Reviewed places → location nodes (feed the case Map tab).
        seen_places: set[str] = set()
        geo = 0
        for rv in reviews:
            place = (rv.get("name") or "").strip()
            if not place or place in seen_places:
                continue
            seen_places.add(place)
            lat, lon = rv.get("lat"), rv.get("lon")
            has_geo = isinstance(lat, (int, float)) and isinstance(lon, (int, float))
            if has_geo:
                geo += 1
            findings.append(Finding(
                entity_type="location", platform="google_maps",
                label=place, url=None, confidence=0.6,
                data={"place": place, "address": rv.get("address") or "",
                      "lat": lat, "lon": lon,
                      "rating": rv.get("rating"), "comment": rv.get("comment") or "",
                      "review_date": rv.get("date") or "",
                      "via": "google_maps_review", "reviewer_gaia": gaia,
                      "source": "ghunt"},
            ))
            edges.append(EdgeResult(from_entity=f"google_account:{label}",
                                    to_entity=f"location:{place}",
                                    relation="reviewed_place", confidence=0.6))
        if reviews:
            errors.append(f"{NOTE_PREFIX}GHunt: {len(seen_places)} reviewed "
                          f"place(s), {geo} with coordinates → see the Map tab.")

        # Contributed photos → location nodes (place + coords + date + image).
        photos = (rev or {}).get("photos") or []
        pgeo = 0
        for ph in photos:
            place = (ph.get("name") or "").strip()
            lat, lon = ph.get("lat"), ph.get("lon")
            if not place or not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
                continue
            pgeo += 1
            plabel = place if place not in seen_places else f"{place} (Foto)"
            seen_places.add(plabel)
            findings.append(Finding(
                entity_type="location", platform="google_maps",
                label=plabel, url=ph.get("url") or None, confidence=0.6,
                data={"place": place, "address": ph.get("address") or "",
                      "lat": lat, "lon": lon,
                      "review_date": ph.get("date") or "",
                      "photo_url": ph.get("url") or "",
                      "via": "google_maps_photo", "reviewer_gaia": gaia,
                      "source": "ghunt"},
            ))
            edges.append(EdgeResult(from_entity=f"google_account:{label}",
                                    to_entity=f"location:{plabel}",
                                    relation="photographed_place", confidence=0.6))
        if photos:
            errors.append(f"{NOTE_PREFIX}GHunt: {pgeo} photographed place(s) "
                          "with coordinates → Map tab.")
    except Exception as e:  # noqa: BLE001
        errors.append(f"GHunt error: {type(e).__name__}: {e}")
    finally:
        shutil.rmtree(home, ignore_errors=True)

    return findings, edges, errors
