"""Phone → messenger presence (honest, best-effort).

There is NO robust, ToS-compliant, keyless oracle that says "this number is
on WhatsApp/Signal" — the automated methods scrape gated endpoints and get
you banned, and faking a hit would be worse than useless in an
investigation. So this tool does the two honest things it actually can:

1. **Offline normalisation** (libphonenumber): E.164, national format,
   validity, country/region, carrier name and line type (mobile / fixed /
   VoIP) and time zones. All local, no network, always reliable — this
   alone often narrows down a subject.

2. **Click-to-verify deep links**: a WhatsApp ``wa.me`` link (and Telegram
   guidance) the investigator opens MANUALLY to confirm presence. Clearly
   labelled as manual — the tool never asserts a registration it did not
   observe.
"""
from __future__ import annotations

import re

from schemas import EdgeResult, Finding, NOTE_PREFIX


def _digits_e164(query: str) -> str:
    q = (query or "").strip()
    q = re.sub(r"(?!^\+)[^\d]", "", q)  # keep a leading +, drop other non-digits
    return q


async def run_phone_messenger(
    query: str, query_type: str = "phone", job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    raw = (query or "").strip()
    if not raw:
        return [], [], ["phone_messenger: provide a phone number (ideally +E.164)."]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    e164 = None
    meta: dict = {"input": raw}
    try:
        import phonenumbers
        from phonenumbers import carrier, geocoder, timezone as pn_tz
        from phonenumbers import PhoneNumberType

        # No default region — require the country code to be present.
        num = phonenumbers.parse(raw, None)
        valid = phonenumbers.is_valid_number(num)
        meta["valid"] = valid
        if not valid and not phonenumbers.is_possible_number(num):
            return [], [], [f"phone_messenger: '{raw}' is not a possible phone number "
                            "(include the country code, e.g. +41 79 …)."]
        e164 = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
        _TYPE = {
            PhoneNumberType.MOBILE: "mobile",
            PhoneNumberType.FIXED_LINE: "fixed_line",
            PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_or_mobile",
            PhoneNumberType.VOIP: "voip",
            PhoneNumberType.TOLL_FREE: "toll_free",
            PhoneNumberType.PREMIUM_RATE: "premium_rate",
        }
        meta.update({
            "e164": e164,
            "national": phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.NATIONAL),
            "international": phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
            "country_code": num.country_code,
            "region": phonenumbers.region_code_for_number(num),
            "location": geocoder.description_for_number(num, "en") or None,
            "carrier": carrier.name_for_number(num, "en") or None,
            "line_type": _TYPE.get(phonenumbers.number_type(num), "unknown"),
            "timezones": list(pn_tz.time_zones_for_number(num)) or None,
        })
    except ImportError:
        errors.append(f"{NOTE_PREFIX}phonenumbers not installed — skipping "
                      "normalisation, emitting deep links only.")
        e164 = _digits_e164(raw)
    except Exception as e:  # noqa: BLE001 — parse failure → still give deep links
        errors.append(f"{NOTE_PREFIX}could not normalise '{raw}' ({type(e).__name__}); "
                      "emitting deep links only.")
        e164 = _digits_e164(raw)

    phone_label = e164 or _digits_e164(raw)
    wa_num = re.sub(r"\D", "", phone_label)  # wa.me wants digits only

    # Enriched phone node (carries the normalisation).
    findings.append(Finding(
        entity_type="phone", platform="phone_messenger", label=phone_label,
        confidence=0.9 if meta.get("valid") else 0.5,
        data={**meta, "source": "phone_messenger"},
    ))

    # WhatsApp click-to-verify deep link (manual — NOT an automated hit).
    wa_url = f"https://wa.me/{wa_num}"
    findings.append(Finding(
        entity_type="search_link", platform="whatsapp",
        label=f"whatsapp:{phone_label}", url=wa_url, confidence=0.4,
        data={"phone": phone_label, "platform": "WhatsApp", "url": wa_url,
              "verification": "manual — open in browser; a valid chat page "
                              "means the number is on WhatsApp. No automated "
                              "registration check (ToS).",
              "source": "phone_messenger"},
    ))
    edges.append(EdgeResult(from_entity=f"phone:{phone_label}",
                            to_entity=f"search_link:whatsapp:{phone_label}",
                            relation="check_on", confidence=0.4))

    errors.append(f"{NOTE_PREFIX}Messenger presence is a MANUAL check via the "
                  "deep link — no compliant automated WhatsApp/Signal oracle "
                  "exists. Telegram presence: use the authenticated Telegram "
                  "tools with a configured session.")
    return findings, edges, errors
