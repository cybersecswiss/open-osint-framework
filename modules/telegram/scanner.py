import asyncio
import logging
import os
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    ChannelPrivateError,
    UsernameNotOccupiedError,
    UsernameInvalidError,
    UserAlreadyParticipantError,
)
from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest
from telethon.tl.functions.channels import LeaveChannelRequest, JoinChannelRequest
from telethon.tl.types import (
    ChatInviteAlready,
    MessageMediaPhoto,
    MessageMediaDocument,
    MessageMediaGeo,
    MessageMediaGeoLive,
    MessageReactions,
    MessageReplyHeader,
    ChannelParticipantsAdmins,
    ChannelParticipantCreator,
    InputMessagesFilterPinned,
)
from extractors.ioc import extract_iocs
from extractors.media import hash_media
from schemas import Finding, EdgeResult, ScanOptions
from labels import canonical_channel_label

logger = logging.getLogger(__name__)


class TelegramScanner:
    def __init__(self, api_id: int, api_hash: str, session_name: str):
        self.client = TelegramClient(session_name, api_id, api_hash)

    async def connect(self):
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise RuntimeError("Not authenticated. Run auth.py first.")

    async def disconnect(self):
        await self.client.disconnect()

    async def _get_entity_with_retry(self, channel_id: str, retries: int = 3):
        for attempt in range(retries):
            try:
                return await self.client.get_entity(channel_id)
            except FloodWaitError as e:
                logger.warning("FloodWait %ds for %s", e.seconds, channel_id)
                await asyncio.sleep(e.seconds)
            except (UsernameNotOccupiedError, UsernameInvalidError, ChannelPrivateError, ValueError):
                raise
            except Exception:
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError(f"FloodWait retries exhausted for {channel_id}")

    def _build_channel_finding(self, entity) -> Finding:
        username = getattr(entity, "username", None) or str(entity.id)
        has_username = bool(getattr(entity, "username", None))
        return Finding(
            entity_type="telegram_channel",
            label=canonical_channel_label(entity),
            url=f"https://t.me/{username}" if has_username else None,
            data={
                "id": entity.id,
                "username": username,
                "title": getattr(entity, "title", "") or "",
                "description": getattr(entity, "about", "") or "",
                "member_count": getattr(entity, "participants_count", None),
                "created_at": str(getattr(entity, "date", "")),
                "is_verified": getattr(entity, "verified", False),
            },
        )

    async def _resolve_user(self, user_id: int) -> Finding | None:
        try:
            user = await self.client.get_entity(user_id)
            username = getattr(user, "username", None) or str(user.id)
            photos = await self.client.get_profile_photos(user)
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
                    "bio": getattr(user, "about", None),
                    "is_bot": getattr(user, "bot", False),
                    "is_scam": getattr(user, "scam", False),
                    "is_verified": getattr(user, "verified", False),
                    "is_fake": getattr(user, "fake", False),
                    "is_premium": getattr(user, "premium", False),
                    "profile_photos": len(photos),
                    "lang_code": getattr(user, "lang_code", None),
                },
            )
        except Exception as e:
            logger.warning("Could not resolve user %s: %s", user_id, e)
            return None

    async def _get_messages(
        self, entity, limit: int, options: ScanOptions
    ) -> tuple[list[Finding], list[EdgeResult]]:
        findings = []
        edges = []
        resolved_authors: set[int] = set()
        author_labels: dict[int, str] = {}
        channel_label = canonical_channel_label(entity)

        async for message in self.client.iter_messages(entity, limit=limit):
            if not message.text and not message.media:
                continue

            sender_id = message.sender_id
            author_id = str(sender_id) if sender_id else "unknown"
            msg_label = f"msg_{entity.id}_{message.id}"

            is_channel_post = sender_id and str(sender_id) == str(-entity.id) or \
                              sender_id and str(abs(sender_id)) == str(entity.id)
            post_author = getattr(message, "post_author", None)

            # Resolve the author FIRST (when requested and not a channel
            # self-post) so the POSTED edge and the user finding reference
            # the exact same node key (@username), instead of a numeric id.
            if options.resolve_authors and sender_id and not is_channel_post:
                if sender_id not in resolved_authors:
                    resolved_authors.add(sender_id)
                    user_finding = await self._resolve_user(sender_id)
                    if user_finding:
                        findings.append(user_finding)
                        author_labels[sender_id] = user_finding.label
                        edges.append(EdgeResult(
                            from_entity=f"telegram_user:{user_finding.label}",
                            to_entity=f"telegram_channel:{channel_label}",
                            relation="POSTED_IN",
                        ))

            author_label = author_labels.get(sender_id, str(sender_id)) if sender_id else None

            msg_data = {
                "id": message.id,
                "text": message.text or "",
                "date": str(message.date),
                "views": message.views or 0,
                "forwards": message.forwards or 0,
                "author_id": author_id,
                "signed_by": post_author,
                "channel_id": entity.id,
            }

            reply_to_id = self._extract_reply_to(message)
            if reply_to_id is not None:
                msg_data["reply_to"] = reply_to_id

            if options.include_reactions:
                reactions = self._extract_reactions(message)
                if reactions:
                    msg_data["reactions"] = reactions

            geo = self._extract_geo(message)
            if geo is not None:
                msg_data["geo"] = geo

            findings.append(Finding(
                entity_type="telegram_message",
                label=msg_label,
                data=msg_data,
            ))

            if author_label is not None and not is_channel_post:
                edges.append(EdgeResult(
                    from_entity=f"telegram_user:{author_label}",
                    to_entity=f"telegram_message:{msg_label}",
                    relation="POSTED",
                ))

            if reply_to_id is not None:
                edges.append(EdgeResult(
                    from_entity=f"telegram_message:{msg_label}",
                    to_entity=f"telegram_message:msg_{entity.id}_{reply_to_id}",
                    relation="REPLY_TO",
                ))

            if options.extract_iocs and message.text:
                for ioc in extract_iocs(message.text):
                    findings.append(Finding(
                        entity_type="telegram_ioc",
                        label=ioc["value"],
                        data={"ioc_type": ioc["type"], "source_message": msg_label},
                    ))
                    edges.append(EdgeResult(
                        from_entity=f"telegram_message:{msg_label}",
                        to_entity=f"telegram_ioc:{ioc['value']}",
                        relation="MENTIONS",
                    ))

            if options.include_media and message.media:
                media_finding = self._build_media_finding(message)
                if media_finding:
                    if options.hash_media:
                        hashes = await hash_media(self.client, message)
                        if hashes:
                            media_finding.data.update(hashes)
                    findings.append(media_finding)
                    edges.append(EdgeResult(
                        from_entity=f"telegram_message:{msg_label}",
                        to_entity=f"telegram_media:{media_finding.label}",
                        relation="HAS_MEDIA",
                    ))

            if options.include_linked and message.fwd_from:
                source = self._extract_forward_source(message.fwd_from)
                if source:
                    edges.append(EdgeResult(
                        from_entity=f"telegram_channel:{channel_label}",
                        to_entity=f"telegram_linked_channel:{source}",
                        relation="FORWARDED_FROM",
                    ))
                    findings.append(Finding(
                        entity_type="telegram_linked_channel",
                        label=source,
                        data={"mention_type": "forward"},
                    ))

        return findings, edges

    def _build_media_finding(self, message) -> Finding | None:
        if isinstance(message.media, MessageMediaPhoto):
            return Finding(
                entity_type="telegram_media",
                label=f"media_{message.id}_photo",
                data={
                    "type": "photo",
                    "date": str(message.date),
                    "poster_id": str(message.sender_id) if message.sender_id else "unknown",
                    "message_id": message.id,
                },
            )
        if isinstance(message.media, MessageMediaDocument):
            doc = message.media.document
            filename = next(
                (a.file_name for a in doc.attributes if hasattr(a, "file_name")),
                "unknown",
            )
            return Finding(
                entity_type="telegram_media",
                label=f"media_{message.id}_doc",
                data={
                    "type": "document",
                    "filename": filename,
                    "size_bytes": doc.size,
                    "date": str(message.date),
                    "poster_id": str(message.sender_id) if message.sender_id else "unknown",
                    "message_id": message.id,
                },
            )
        return None

    def _extract_reactions(self, message) -> dict | None:
        reactions = getattr(message, "reactions", None)
        if not isinstance(reactions, MessageReactions):
            return None
        out = {}
        for r in getattr(reactions, "results", []) or []:
            emoticon = getattr(getattr(r, "reaction", None), "emoticon", None)
            key = emoticon or str(getattr(getattr(r, "reaction", None), "document_id", "custom"))
            out[key] = getattr(r, "count", 0)
        return out or None

    def _extract_reply_to(self, message):
        reply = getattr(message, "reply_to", None)
        if not isinstance(reply, MessageReplyHeader):
            return None
        return getattr(reply, "reply_to_msg_id", None)

    def _extract_geo(self, message) -> dict | None:
        media = getattr(message, "media", None)
        if not isinstance(media, (MessageMediaGeo, MessageMediaGeoLive)):
            return None
        point = getattr(media, "geo", None)
        lat = getattr(point, "lat", None)
        long = getattr(point, "long", None)
        if lat is None or long is None:
            return None
        return {"lat": lat, "long": long}

    def _extract_forward_source(self, fwd_from) -> str | None:
        if getattr(fwd_from, "from_name", None):
            return fwd_from.from_name
        if getattr(fwd_from, "channel_id", None):
            return f"channel_{fwd_from.channel_id}"
        return None

    async def _get_members(
        self, entity, channel_label: str
    ) -> tuple[list[Finding], list[EdgeResult]]:
        findings = []
        edges = []
        try:
            async for user in self.client.iter_participants(entity):
                username = getattr(user, "username", None) or str(user.id)
                findings.append(Finding(
                    entity_type="telegram_user",
                    label=f"@{username}",
                    data={
                        "id": user.id,
                        "username": username,
                        "first_name": getattr(user, "first_name", "") or "",
                        "last_name": getattr(user, "last_name", "") or "",
                        "phone": getattr(user, "phone", None),
                        "is_bot": getattr(user, "bot", False),
                        "is_scam": getattr(user, "scam", False),
                    },
                ))
                edges.append(EdgeResult(
                    from_entity=f"telegram_user:@{username}",
                    to_entity=f"telegram_channel:{channel_label}",
                    relation="MEMBER_OF",
                ))
        except Exception as e:
            logger.warning("Could not get members for %s: %s", channel_label, e)
        return findings, edges

    async def _get_admins(
        self, entity, channel_label: str
    ) -> tuple[list[Finding], list[EdgeResult]]:
        findings = []
        edges = []
        try:
            async for user in self.client.iter_participants(entity, filter=ChannelParticipantsAdmins()):
                username = getattr(user, "username", None) or str(user.id)
                participant = getattr(user, "participant", None)
                role = "creator" if isinstance(participant, ChannelParticipantCreator) else "admin"
                custom_title = getattr(participant, "rank", None)
                findings.append(Finding(
                    entity_type="telegram_user",
                    label=f"@{username}",
                    url=f"https://t.me/{username}" if getattr(user, "username", None) else None,
                    data={
                        "id": user.id,
                        "username": username,
                        "first_name": getattr(user, "first_name", "") or "",
                        "last_name": getattr(user, "last_name", "") or "",
                        "phone": getattr(user, "phone", None),
                        "is_bot": getattr(user, "bot", False),
                        "is_scam": getattr(user, "scam", False),
                        "is_verified": getattr(user, "verified", False),
                        "is_admin": True,
                        "role": role,
                        "custom_title": custom_title,
                    },
                ))
                edges.append(EdgeResult(
                    from_entity=f"telegram_user:@{username}",
                    to_entity=f"telegram_channel:{channel_label}",
                    relation="ADMIN_OF",
                ))
        except Exception as e:
            logger.warning("Could not get admins for %s: %s", channel_label, e)
        return findings, edges

    async def _get_pinned(
        self, entity, channel_label: str
    ) -> tuple[list[Finding], list[EdgeResult]]:
        findings = []
        edges = []
        try:
            async for message in self.client.iter_messages(entity, filter=InputMessagesFilterPinned()):
                if not message.text and not message.media:
                    continue
                msg_label = f"pinned_{entity.id}_{message.id}"
                findings.append(Finding(
                    entity_type="telegram_message",
                    label=msg_label,
                    data={
                        "id": message.id,
                        "text": message.text or "",
                        "date": str(message.date),
                        "views": message.views or 0,
                        "forwards": message.forwards or 0,
                        "author_id": str(message.sender_id) if message.sender_id else "unknown",
                        "signed_by": getattr(message, "post_author", None),
                        "channel_id": entity.id,
                        "is_pinned": True,
                    },
                ))
                edges.append(EdgeResult(
                    from_entity=f"telegram_message:{msg_label}",
                    to_entity=f"telegram_channel:{channel_label}",
                    relation="PINNED_IN",
                ))
        except Exception as e:
            logger.warning("Could not get pinned messages for %s: %s", channel_label, e)
        return findings, edges

    async def scan_channels(
        self, channels: list[str], options: ScanOptions
    ) -> tuple[list[Finding], list[EdgeResult], list[str]]:
        all_findings: list[Finding] = []
        all_edges: list[EdgeResult] = []
        errors: list[str] = []
        delay = int(os.getenv("DELAY_BETWEEN_CHANNELS", "2"))

        for i, channel_id in enumerate(channels):
            channel_id = channel_id.strip()
            if not channel_id:
                continue
            try:
                findings, edges = await self._scan_single_channel(channel_id, options)
                all_findings.extend(findings)
                all_edges.extend(edges)
            except Exception as e:
                errors.append(f"{channel_id}: {e}")

            if i < len(channels) - 1:
                await asyncio.sleep(delay)

        return all_findings, all_edges, errors

    async def _scan_invite_link(
        self, invite_hash: str, options: ScanOptions
    ) -> tuple[list[Finding], list[EdgeResult]]:
        findings: list[Finding] = []
        edges: list[EdgeResult] = []
        hash_clean = invite_hash.lstrip("+")
        joined = False
        entity = None

        if options.auto_join:
            try:
                join_result = await self.client(ImportChatInviteRequest(hash_clean))
                entity = join_result.chats[0]
                joined = True
                logger.info("Joined channel via invite: %s", invite_hash)
            except UserAlreadyParticipantError:
                try:
                    check = await self.client(CheckChatInviteRequest(hash=hash_clean))
                    if isinstance(check, ChatInviteAlready):
                        entity = check.chat
                except Exception:
                    pass
            except Exception as e:
                findings.append(Finding(
                    entity_type="telegram_channel",
                    label=f"invite:{invite_hash}",
                    data={"status": "join_failed", "query": invite_hash, "error": str(e)},
                ))
                return findings, edges

            if entity is None:
                findings.append(Finding(
                    entity_type="telegram_channel",
                    label=f"invite:{invite_hash}",
                    data={"status": "join_failed", "query": invite_hash,
                          "error": "Could not resolve entity after join attempt"},
                ))
                return findings, edges
        else:
            try:
                result = await self.client(CheckChatInviteRequest(hash=hash_clean))
            except Exception as e:
                err = str(e)
                if "expired" in err.lower():
                    status = "invite_expired"
                    note = "Link may be expired, revoked, full, require approval, or account may be restricted"
                elif "invalid" in err.lower():
                    status = "invite_invalid"
                    note = "Invite hash is malformed"
                else:
                    status = "invite_error"
                    note = ""
                data = {"status": status, "query": invite_hash, "error": err}
                if note:
                    data["note"] = note
                findings.append(Finding(
                    entity_type="telegram_channel",
                    label=f"invite:{invite_hash}",
                    data=data,
                ))
                return findings, edges

            if isinstance(result, ChatInviteAlready):
                entity = result.chat
            else:
                findings.append(Finding(
                    entity_type="telegram_channel",
                    label=f"invite:{invite_hash}",
                    data={
                        "title": getattr(result, "title", "") or "",
                        "description": getattr(result, "about", "") or "",
                        "member_count": getattr(result, "participants_count", None),
                        "status": "invite_metadata_only",
                        "invite_hash": invite_hash,
                        "note": "Enable auto_join to access messages and members",
                    },
                ))
                return findings, edges

        channel_finding = self._build_channel_finding(entity)
        findings.append(channel_finding)
        channel_label = channel_finding.label

        try:
            if options.limit_messages > 0:
                msg_findings, msg_edges = await self._get_messages(entity, options.limit_messages, options)
                findings.extend(msg_findings)
                edges.extend(msg_edges)
                for f in msg_findings:
                    if f.entity_type == "telegram_message":
                        edges.append(EdgeResult(from_entity=f"telegram_message:{f.label}", to_entity=f"telegram_channel:{channel_label}", relation="IN_CHANNEL"))

            if options.include_members:
                member_findings, member_edges = await self._get_members(entity, channel_label)
                findings.extend(member_findings)
                edges.extend(member_edges)
            if options.include_admins:
                admin_findings, admin_edges = await self._get_admins(entity, channel_label)
                findings.extend(admin_findings)
                edges.extend(admin_edges)
            if options.include_pinned:
                pinned_findings, pinned_edges = await self._get_pinned(entity, channel_label)
                findings.extend(pinned_findings)
                edges.extend(pinned_edges)
        finally:
            if joined:
                try:
                    await self.client(LeaveChannelRequest(entity))
                    logger.info("Left channel after scan: %s", channel_label)
                except Exception as e:
                    logger.warning("Could not leave channel %s: %s", channel_label, e)

        return findings, edges

    async def _scan_single_channel(
        self, channel_id: str, options: ScanOptions
    ) -> tuple[list[Finding], list[EdgeResult]]:
        findings: list[Finding] = []
        edges: list[EdgeResult] = []

        if "t.me/" in channel_id:
            channel_id = channel_id.split("t.me/")[-1].rstrip("/").split("#")[0]

        if channel_id.startswith("+"):
            return await self._scan_invite_link(channel_id, options)

        try:
            entity = await self._get_entity_with_retry(channel_id)
        except (UsernameNotOccupiedError, UsernameInvalidError, ValueError):
            findings.append(Finding(
                entity_type="telegram_channel",
                label=channel_id,
                data={"status": "not_found", "query": channel_id},
            ))
            return findings, edges
        except ChannelPrivateError:
            findings.append(Finding(
                entity_type="telegram_channel",
                label=channel_id,
                data={"status": "access_denied", "query": channel_id},
            ))
            return findings, edges

        channel_finding = self._build_channel_finding(entity)
        findings.append(channel_finding)
        channel_label = channel_finding.label

        if options.limit_messages > 0:
            msg_findings, msg_edges = await self._get_messages(
                entity, options.limit_messages, options
            )
            findings.extend(msg_findings)
            edges.extend(msg_edges)
            for f in msg_findings:
                if f.entity_type == "telegram_message":
                    edges.append(EdgeResult(
                        from_entity=f"telegram_message:{f.label}",
                        to_entity=f"telegram_channel:{channel_label}",
                        relation="IN_CHANNEL",
                    ))

        if options.include_members:
            member_findings, member_edges = await self._get_members(entity, channel_label)
            findings.extend(member_findings)
            edges.extend(member_edges)
        if options.include_admins:
            admin_findings, admin_edges = await self._get_admins(entity, channel_label)
            findings.extend(admin_findings)
            edges.extend(admin_edges)
        if options.include_pinned:
            pinned_findings, pinned_edges = await self._get_pinned(entity, channel_label)
            findings.extend(pinned_findings)
            edges.extend(pinned_edges)

        return findings, edges
