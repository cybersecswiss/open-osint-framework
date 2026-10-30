from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Required at startup. Compose injects every value from .env so a
    missing field means a deployment misconfig — fail loudly rather
    than silently fall back.
    """

    # Datastores
    database_url: str
    redis_url: str

    # Keycloak
    keycloak_url: str
    keycloak_realm: str
    keycloak_client_id: str
    keycloak_client_secret: str
    # Issuer string Keycloak uses when accessed via the public URL
    # (through nginx). Used for diagnostics / logs only — token
    # verification is signature-only because the same realm presents
    # two different `iss` values depending on the inbound network.
    keycloak_public_issuer: str
    # The SEPARATE realm product owners authenticate against.
    # /api/v1/platform/* tokens are validated against this realm's issuer
    # only. `platform_kc_client_*` is a confidential service-account
    # client the backend uses to manage product-owner users via the KC
    # admin API. Defaults keep the backend booting if unset (operator
    # user-management endpoints then return a clear error).
    platform_realm: str = "platform"
    platform_kc_client_id: str = "platform-backend"
    platform_kc_client_secret: str = ""

    # Internal-network URLs of the other framework components.
    # Each *_url is `http://<service>:<port>` per docker-compose.
    license_server_url: str
    n8n_url: str
    n8n_api_key: str
    # Isolated updater sidecar (has the Docker socket; internal-only). Used
    # by the operator "update n8n" button — it can only update n8n.
    updater_url: str = "http://updater:9999"
    # AI function provider (Phase-3 scaffold: swap Gemini for a local model
    # without redeploying — data-sovereignty). "gemini" → the n8n
    # /webhook/ai-link workflow; "local" → /webhook/ai-link-local against an
    # OpenAI-compatible endpoint (Ollama/vLLM/llama.cpp) at ai_local_base_url.
    ai_provider: str = "gemini"
    ai_gemini_model: str = "gemini-3.6-flash"
    ai_local_base_url: str = ""
    ai_local_model: str = "llama3.1"
    # OSINT modules — cybercrime focus. Each module exposes /manifest;
    # backend caches manifests at startup and re-polls on demand. Add a
    # new module by appending the URL here AND a (name, attr) entry to
    # MODULE_REGISTRY in app/services/osint_orchestrator.py.
    module_alias_url: str
    module_leaks_url: str
    module_infra_url: str
    module_threat_url: str
    module_darknet_url: str
    module_messenger_url: str
    module_crypto_url: str
    module_telegram_url: str
    module_compliance_url: str = "http://module-compliance:8100"
    module_forums_url: str = "http://module-forums:8110"
    module_dating_url: str = "http://module-dating:8130"
    module_image_url: str = "http://module-image:8120"
    module_news_url: str = "http://module-news:8140"
    # Evidence capture (headless browser, own network) — capture/main.py.
    capture_url: str = "http://capture:8160"
    module_corporate_url: str = "http://module-corporate:8150"

    # Backend's master secret. Historically ONE value did four jobs
    # (KEK for stored API keys, internal service-to-service auth, the
    # updater sidecar's key, and the customer-agent key). That made the
    # blast radius of any single leak the whole platform and made
    # rotation impossible. The three below split those roles apart; each
    # falls back to `secret_key` when unset, so an existing deployment
    # keeps working untouched and can be migrated one secret at a time.
    # (The customer-agent key is no longer derived from any of these —
    # it is the per-tenant `agent_api_key` from the license server, see
    # services/tenant_registry.get_agent_key.)
    secret_key: str
    # Fernet key-encryption-key for the stored OSINT API keys.
    # ⚠️ Changing it makes stored ciphertext undecryptable — migrate with
    # `scripts/rekey-apikeys.py` (decrypts with the old, re-encrypts with
    # the new) rather than editing it in place.
    apikey_kek: str = ""
    # Shared secret for internal service-to-service calls (backend ↔
    # license-server, n8n → backend, backend → module-internal routes).
    internal_key: str = ""
    # Separate key for the updater sidecar, which holds the Docker socket.
    # Kept apart from `internal_key` so a compromise of n8n (which needs
    # the internal key) does not hand over Docker-socket-backed actions.
    updater_key: str = ""

    # Optional comma-separated allow-list of accepted `azp` (authorized
    # party) claims, e.g. "osint-frontend,platform-frontend". Empty (the
    # default) accepts any client of a trusted realm — which is the previous
    # behaviour. Set it only when every tenant IdP uses the same client-id
    # convention, otherwise a customer realm with a different client name
    # would lock its users out.
    allowed_azp: str = ""

    # Audit chain. The chain used to be a plain SHA-256 of the previous
    # hash, i.e. anyone able to write to the database could recompute the
    # whole thing and leave no trace — which is exactly the party the chain
    # is supposed to be evidence against. Keyed hashing fixes that; the key
    # must NOT be stored in the same database.
    audit_hmac_key: str = ""
    # What the operator-side audit stores for a search selector:
    #   full   — the query verbatim (default; unchanged behaviour, and what
    #            the tenant-admin audit view shows today)
    #   hashed — only a salted fingerprint, so the operator cannot read what
    #            an authority searched for while duplicate searches remain
    #            correlatable
    #   off    — no selector at all
    # Recommended for customers with strict sovereignty requirements: hashed.
    audit_selector_mode: str = "full"
    # Directory for the append-only chain anchors (see services/audit).
    # Lives outside Postgres on purpose: an anchor that no longer matches
    # the chain is how a wholesale rewrite of the audit table gets caught.
    audit_anchor_dir: str = "/var/lib/osint/audit-anchors"

    @property
    def audit_key(self) -> str:
        """Key for the audit HMAC (legacy fallback: the master secret)."""
        return self.audit_hmac_key or self.secret_key

    @property
    def kek_secret(self) -> str:
        """Key-encryption-key for API-key storage (legacy fallback)."""
        return self.apikey_kek or self.secret_key

    @property
    def internal_secret(self) -> str:
        """Internal service-to-service secret (legacy fallback)."""
        return self.internal_key or self.secret_key

    @property
    def updater_secret(self) -> str:
        """Updater-sidecar secret (falls back to the internal secret)."""
        return self.updater_key or self.internal_secret

    # Public host/port — used to build CORS origins and the deep links in
    # alert notifications. `public_scheme` has been in .env all along; it
    # was simply never read here, so anything building an absolute URL had
    # to hardcode https.
    public_host: str
    public_http_port: int
    public_https_port: int
    public_scheme: str = "https"

    @property
    def public_base_url(self) -> str:
        """Absolute base URL of this installation. One implementation, so a
        link in a mail and a link in the UI cannot disagree about the port."""
        scheme = (self.public_scheme or "https").lower()
        port = self.public_https_port if scheme == "https" else self.public_http_port
        default = 443 if scheme == "https" else 80
        host = self.public_host
        return f"{scheme}://{host}" if port in (default, 0) else f"{scheme}://{host}:{port}"

    # TLS verification when fetching JWKS / hitting Customer-KC admin
    # API. Set False in dev (self-signed certs) and True in production
    # where customer Keycloaks have real CA certs.
    tls_verify_idp: bool = True
    # Verify customer data-server certificates. false only for LAN/test
    # data servers with self-signed certificates.
    tls_verify_agent: bool = True

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


settings = Settings()
