import re

PATTERNS = {
    "btc": re.compile(r"\b(?:bc1[ac-hj-np-z02-9]{11,71}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b"),
    "eth": re.compile(r"\b0x[a-fA-F0-9]{40}\b"),
    "xmr": re.compile(r"\b[48][0-9AB][1-9A-HJ-NP-Za-km-z]{93}\b"),
    "ltc": re.compile(r"\b(?:ltc1[ac-hj-np-z02-9]{11,71}|[LM][a-km-zA-HJ-NP-Z1-9]{26,33})\b"),
    "tron": re.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    "telegram_link": re.compile(r"(?:https?://)?t\.me/[A-Za-z0-9_+/]+"),
    "url": re.compile(r"https?://[^\s<>\"')]+"),
    "phone": re.compile(r"\+\d[\d\s\-().]{6,}\d"),
    "mention": re.compile(r"(?<![\w@])@[A-Za-z][A-Za-z0-9_]{3,31}\b"),
    "hashtag": re.compile(r"(?<!\w)#\w{2,}"),
}


def extract_iocs(text):
    if not text:
        return []
    results = []
    seen = set()
    for ioc_type, pattern in PATTERNS.items():
        for match in pattern.findall(text):
            value = match if isinstance(match, str) else match[0]
            value = value.strip()
            if not value:
                continue
            # The framework persists a Finding.label into a String(255)
            # column; cap long IOCs (e.g. tracking URLs) so a single
            # oversized match can never break the whole ingest batch.
            value = value[:255]
            key = (ioc_type, value)
            if key in seen:
                continue
            seen.add(key)
            results.append({"type": ioc_type, "value": value})
    return results
