# TLS certificates

`setup.sh` writes `server.crt` / `server.key` here; nginx serves them.
Never commit them (this directory is gitignored except for this file).

* **IP address or `--tls selfsigned`** — a self-signed certificate for the
  configured address (825 days). Regenerated automatically when the address
  changes (`sudo ./setup.sh --reconfigure`).
* **`--tls letsencrypt`** — `setup.sh` obtains the certificate with certbot
  (webroot `acme-webroot/`) and installs a renewal hook at
  `/etc/letsencrypt/renewal-hooks/deploy/oof.sh` that copies renewed
  certificates here and reloads nginx.

Own certificate (company CA): copy the full chain to `server.crt` and the
key to `server.key` (`chmod 600`), then
`docker compose exec nginx nginx -s reload`. `setup.sh` keeps a valid
certificate whose SAN matches the address.
