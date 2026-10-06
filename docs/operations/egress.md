# Outbound network access

Plugin steps reach the network only through Dewpoint's guard (plugins-3 D7). It works in this order:

1. **Resolve and check every address.** For each connection, the guard resolves the destination's name and checks
   every address it gets back. If any address is not a public one, the guard refuses the destination, unless an
   allowlist entry covers that address. Addresses that count as non-public:
   - every IANA special-purpose range that isn't globally reachable (the guard keeps its own table, so the
     verdict doesn't depend on the Python version), including loopback, private, link-local and CGNAT ranges;
   - multicast, reserved and site-local addresses;
   - IPv4-mapped addresses (`::ffff:a.b.c.d`), checked as the IPv4 address they carry;
   - the IPv6 forms that wrap an IPv4 address (IPv4-compatible, 6to4, Teredo, NAT64 `64:ff9b::/96` and
     `64:ff9b:1::/48`), refused even when the IPv4 address is public.

   A NAT64-only deployment therefore needs allowlist entries for its translated destinations. Prefer one entry per
   destination (`64:ff9b::808:808/128`): an entry for the whole NAT64 prefix reaches every IPv4 address the
   translator reaches, private ranges included.
2. **Connect to the checked address.** The guard connects to the exact address it checked, so a later DNS change
   can't redirect the request. TLS is still verified against the hostname.
3. **No proxies.** The guard ignores proxy, certificate and netrc settings in the environment.
4. **Plain-text traffic needs an entry.** Plain `http`, plain TCP and UDP (for example syslog) go only to addresses
   an allowlist entry covers, public or not.
5. **Redirects stay on the same origin.** Redirects are followed only when a node opts in, and only to the same
   origin.
6. **Limits.** Responses are capped at 10 MiB. Connections time out after 5 s.

## The allowlist

Only a platform admin can change the allowlist, through the `dewpoint_admin` database role. Every change is audited:
- in the tenant's audit chain, for an entry that belongs to one tenant;
- in the platform's audit chain, for an entry that applies to every tenant.

```
dewpoint platform egress add 10.20.0.0/16 --tenant <tenant-id> --ports 8443 --note "internal LLM"
dewpoint platform egress add fd00:1234::/32 --every-tenant --ports 8000-8100
dewpoint platform egress list
dewpoint platform egress remove <entry-id>
```

- **Scope.** An entry belongs to one tenant by default, so one customer's internal range never opens to another.
  `--every-tenant` must be given explicitly.
- **Network.** The network must be written exactly (no host bits set) and can't cover every address.
- **Ports.** `--ports` restricts the entry to one port or a range; without it, the entry covers any port.
- **When it takes effect.** The guard reads the allowlist on every connect, so a removal applies to the next connection.

## Rate limits

Every request through a connection takes a token from each quota scope of that connection's provider. Scopes are kept
per tenant, so connections that share a credential share one budget.

- **Mist.** Each request is charged to two scopes: its token and its org. Each scope allows bursts of 50 and refills
  at 1.25 calls per second.
- **When no token is available.** A step waits up to 10 s. After that it fails with `cooldown` and sends nothing.
- **When the provider sends `Retry-After`.** That scope is blocked for every run, for up to an hour.
- **Seeing a block.** `GET /api/v1/t/{tenant}/connections/{id}` lists each blocked scope's current cooldown, shown
  by its kind (`mist.org`, `mist.token`). That end time is live: it moves if the provider extends or lifts the block.
