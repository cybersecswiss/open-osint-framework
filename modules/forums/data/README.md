# Seed datasets (not shipped)

The two indexes used by module-forums are **not** part of the repository —
they are compiled from third-party sources whose terms we do not control:

| File | Source | Refresh |
|---|---|---|
| `threat_actors.json.gz` | [spmedia/Threat-Actor-Usernames-Scrape](https://github.com/spmedia/Threat-Actor-Usernames-Scrape) | `POST /threat-actors/refresh` |
| `linkbase_index.json`   | link-base.ms (public forum directory, crawled politely, ~10 min) | `POST /linkbase/refresh` |

`setup.sh` triggers both downloads after the first start; they land in the
`forums_cache` volume, not here. Until they finish, the tools
`threat_actor_check` and `linkbase_lookup` answer with "index not loaded".
Re-run at any time from the operator console (Settings → Indexes) or:

    docker compose exec module-forums curl -fsS -X POST localhost:8110/threat-actors/refresh
    docker compose exec module-forums curl -fsS -X POST localhost:8110/linkbase/refresh

A file placed in this directory is baked into the image as a fallback.
