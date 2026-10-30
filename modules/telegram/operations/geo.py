import logging
from telethon.tl.functions.contacts import GetLocatedRequest
from telethon.tl.types import InputGeoPoint, UpdatePeerLocated, PeerUser, PeerChannel
from schemas import Finding, EdgeResult, GeoOptions

logger = logging.getLogger(__name__)


def _parse_coords(query: str):
    parts = query.replace(";", ",").split(",")
    if len(parts) < 2:
        raise ValueError("expected 'lat,long'")
    return float(parts[0].strip()), float(parts[1].strip())


async def _resolve_peer(client, peer, distance, options: GeoOptions):
    label = None
    data = {"distance_m": distance}
    entity_type = "telegram_user"

    if isinstance(peer, PeerUser):
        data["peer_type"] = "user"
        data["peer_id"] = peer.user_id
        ref = peer.user_id
    elif isinstance(peer, PeerChannel):
        data["peer_type"] = "channel"
        data["peer_id"] = peer.channel_id
        entity_type = "telegram_channel"
        ref = peer.channel_id
    else:
        return None, None

    if options.resolve_entities:
        try:
            entity = await client.get_entity(peer)
            username = getattr(entity, "username", None) or str(entity.id)
            data["username"] = username
            data["title"] = getattr(entity, "title", "") or ""
            data["first_name"] = getattr(entity, "first_name", "") or ""
            data["last_name"] = getattr(entity, "last_name", "") or ""
            label = f"@{username}" if entity_type == "telegram_user" else f"t.me/{username}"
        except Exception as e:
            logger.warning("Could not resolve located peer: %s", e)

    if label is None:
        label = f"{data['peer_type']}_{ref}"

    return Finding(entity_type=entity_type, label=label, data=data), None


async def run(client, query: str, options_dict: dict):
    options = GeoOptions(**(options_dict or {}))
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    try:
        lat, long = _parse_coords(query)
    except Exception as ex:
        return findings, edges, [f"invalid coordinates: {ex}"]

    try:
        result = await client(GetLocatedRequest(geo_point=InputGeoPoint(lat=lat, long=long)))
    except Exception as ex:
        return findings, edges, [f"geo lookup failed: {ex}"]

    for update in getattr(result, "updates", []):
        if not isinstance(update, UpdatePeerLocated):
            continue
        for located in update.peers:
            peer = getattr(located, "peer", None)
            distance = getattr(located, "distance", None)
            if peer is None:
                continue
            try:
                finding, _ = await _resolve_peer(client, peer, distance, options)
                if finding is not None:
                    findings.append(finding)
            except Exception as e:
                errors.append(str(e))

    return findings, edges, errors
