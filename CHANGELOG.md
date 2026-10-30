# Changelog

Versions follow `YYYY.MM.N`. The user-facing release notes shown in the
application live in `frontend/public/wiki/changelog.json`.

## 2026.10.0 — first public release

* Guided installation `setup.sh` (DE/EN): all-in-one on one server, or
  operator mode with a data server per organisation; IP address with a
  self-signed certificate or domain with Let's Encrypt; free choice of
  ports; unattended mode with flags.
* Data-server installer (`data-agent/install.sh`, DE/EN) with Let's Encrypt
  or self-signed (`--tls internal`) certificates and configurable ports.
* Releases for data servers are frozen copies in `data-agent/dist/`, served
  at `/agent/` with SHA-256 checksums.
* No default passwords anywhere in the repository; every credential is
  generated at install time.
* Forum indexes are downloaded at setup instead of being shipped.
