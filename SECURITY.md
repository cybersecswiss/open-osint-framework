# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's
private vulnerability reporting (*Security* tab → *Report a vulnerability*)
or write to **info@cybersecswiss.ch**. Include the affected version (`VERSION`), the component
(framework, data server, a module) and a way to reproduce.

You will get an acknowledgement within a week. Fixes are released as a new
version; the advisory credits you unless you prefer otherwise.

## Scope

In scope: everything in this repository — the backend, frontend, data
server, license server, modules, setup and release scripts, and the default
configuration they produce.

Out of scope: vulnerabilities in third-party services queried by the
modules, and findings that require an attacker who already has root on the
server or the contents of `.env`.

## Hardening notes for operators

* `.env` contains every secret of an installation (`chmod 600`). Never
  commit it, never send it with a bug report.
* Use real certificates (Let's Encrypt) for anything reachable from the
  internet; `TLS_VERIFY_AGENT=false` / `TLS_VERIFY_IDP=false` are for
  closed networks only.
* Only nginx publishes ports. Keep it that way — Docker-published ports
  bypass host firewalls.
* Keep `AUDIT_SELECTOR_MODE=hashed` unless you need search terms in the
  operator audit log.
* Update regularly: `git pull && sudo ./setup.sh`.
