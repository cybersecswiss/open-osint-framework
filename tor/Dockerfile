# Minimal, current Tor SOCKS proxy. Built from Alpine so the bundled Tor
# (and its directory-authority keys) is always up to date — the stale
# dperson/torproxy image gets stuck at 30% bootstrap ("consensus not
# signed by sufficient number of authorities") on old keys.
FROM alpine:3.20

RUN apk add --no-cache tor curl \
    && mkdir -p /var/lib/tor \
    && chown -R tor:tor /var/lib/tor

COPY torrc /etc/tor/torrc

USER tor
EXPOSE 9050

# Green once the SOCKS port is listening.
HEALTHCHECK --interval=30s --timeout=5s --retries=5 --start-period=90s \
    CMD netstat -lnt 2>/dev/null | grep -q ':9050' || exit 1

CMD ["tor", "-f", "/etc/tor/torrc"]
