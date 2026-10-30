import logging
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.types import InputPhoneContact
from schemas import Finding, PhoneLookupOptions

logger = logging.getLogger(__name__)


def _user_finding(user, phone: str | None) -> Finding:
    username = getattr(user, "username", None) or str(user.id)
    return Finding(
        entity_type="telegram_user",
        label=f"@{username}",
        url=f"https://t.me/{username}" if getattr(user, "username", None) else None,
        data={
            "id": user.id,
            "username": username,
            "first_name": getattr(user, "first_name", "") or "",
            "last_name": getattr(user, "last_name", "") or "",
            "phone": getattr(user, "phone", None),
            "matched_phone": phone,
            "is_bot": getattr(user, "bot", False),
            "is_scam": getattr(user, "scam", False),
            "is_premium": getattr(user, "premium", False),
            "status": "telegram_account_found",
        },
    )


async def run(client, query: str, options_dict: dict):
    options = PhoneLookupOptions(**(options_dict or {}))
    findings: list[Finding] = []
    edges: list = []
    errors: list[str] = []

    phones = [p.strip() for p in query.replace("\n", ",").split(",") if p.strip()]
    if not phones:
        return findings, edges, ["no phone numbers provided"]

    contacts = [
        InputPhoneContact(client_id=i, phone=p, first_name=f"osint{i}", last_name="lookup")
        for i, p in enumerate(phones)
    ]

    imported_users = []
    try:
        result = await client(ImportContactsRequest(contacts))
        imported_users = result.users
        matched_client_ids = set()
        client_id_to_user = {}
        for imp in result.imported:
            matched_client_ids.add(imp.client_id)
            client_id_to_user[imp.client_id] = imp.user_id

        user_by_id = {u.id: u for u in result.users}
        for client_id, user_id in client_id_to_user.items():
            user = user_by_id.get(user_id)
            if user is not None:
                findings.append(_user_finding(user, phones[client_id]))

        for i, phone in enumerate(phones):
            if i not in matched_client_ids:
                findings.append(Finding(
                    entity_type="telegram_user",
                    label=phone,
                    data={"status": "no_telegram_account", "query": phone},
                ))
    except Exception as ex:
        errors.append(str(ex))
    finally:
        if imported_users:
            try:
                await client(DeleteContactsRequest(id=[u.id for u in imported_users]))
                logger.info("Cleaned up %d imported contacts", len(imported_users))
            except Exception as e:
                logger.warning("Contact cleanup failed: %s", e)

    return findings, edges, errors
