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

### Streams (websockets)

Some connections also have a stream: Mist's device utilities read a command's output over a websocket (plugins-3 D26).
A stream goes through the same guard:

- **Only the connection type's stream.** A step can't choose the URL: it's `wss://` and the host the connection's
  config maps to (for Mist, the cloud's `api-ws.` host beside its `api.` host, for example `api-ws.mist.com`), then a
  fixed path. Plain `ws://` isn't possible.
- **Checked and pinned like a request.** The guard resolves the name, checks every address and connects to a checked
  one; TLS is verified against the hostname; proxy settings in the environment are ignored; a redirect is never
  followed.
- **Credentials are the runtime's.** The connection's header (Mist: `Authorization: Token ...`) is sent with the
  opening handshake; a step can't add or change it.
- **Limits.** Opening (connect, TLS and handshake) within 5 s; text messages only, each at most 1 MiB, and at most
  10 MiB received by one attempt; a ping every 60 s, with 45 s for its answer. A step's streams are closed when it ends.
- **Firewalls.** A network that only lets Dewpoint reach listed hosts must list each Mist cloud's `api-ws.` host as
  well as its `api.` host, both on port 443.

### Incoming webhooks (Slack, Teams, Google Chat, a generic webhook)

Messaging connections post to an incoming webhook whose URL is the credential (plugins-3 D18). The whole URL is the
connection's secret.

| Type | The URL | Hosts to allow through a firewall |
| --- | --- | --- |
| `slack` | Slack's documented form only: `https://hooks.slack.com/services/T…/B…/…` | `hooks.slack.com` |
| `teams` | A Teams Workflows URL ("When a Teams webhook request is received"), its trigger set to accept "Anyone": `https://….logic.azure.com/…` or `https://….api.powerplatform.com/…`, on port 443 | the flow's host |
| `google_chat` | A space's webhook: `https://chat.googleapis.com/v1/spaces/SPACE/messages?key=…&token=…` | `chat.googleapis.com` |
| `webhook` | Any https URL: a lowercase host name or IPv4 address, an optional port, a path and query; no user name, no fragment. Not a Slack, Teams or Google Chat webhook: those take their own type, which escapes run data | the receiver's host |

- **Checked as written.** A URL of another shape is refused when the connection is created, naming its field, and
  again whenever it's read. Teams' sovereign clouds, GovSlack and Office 365 connectors (retired by Microsoft) aren't
  accepted.
- **Requests go to the URL exactly.** A step adds no path, query, header or redirect, and no authentication header
  is sent: a receiver that needs one isn't reachable yet. Plain `http` isn't possible, even to an allowlisted address.
- **Nothing is posted to test a connection.** A wrong URL fails at its first send.
- **The URL's parts are secrets.** Its path, its segments and its query values of 8 characters or more join the run's
  secret index, so an output repeating one is redacted.
- **A send may not be retried.** A send that fails once it may have arrived (a 429, a 5xx, no answer) ends
  `outcome_unknown` and is never retried automatically. A Teams 2xx means the flow accepted the message (`accepted`),
  not that it was posted.

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
  at 1.25 calls per second. Each stream opened is charged to a third scope, the token's streams (`mist.stream`): bursts
  of 50, then 0.5 a second (1,800 an hour, under Mist's 2,000 connections an hour a token).
- **Slack.** One scope a tenant (`slack.tenant`): bursts of 3, then 1 a second. A webhook URL names no documented
  workspace or channel, so a tenant's Slack webhooks share it.
- **Teams.** One scope a tenant (`teams.tenant`): bursts of 5, then 25 posts in 300 s. That's Teams' limit for one
  Teams connection posting as the flow bot; a webhook URL doesn't name the connection, so a tenant's flows share it.
  Microsoft turns off a flow that stays throttled for 14 days.
- **Google Chat.** One scope a space (`google_chat.space`), read from the URL: 1 a second, no burst, shared by all the
  space's webhooks.
- **Webhook.** One scope a receiver's host (`webhook.host`): bursts of 5, then 1 a second.
- **When no token is available.** A step waits up to 10 s. After that it fails with `cooldown` and sends nothing.
- **When the provider sends `Retry-After`.** That scope is blocked for every run, for up to an hour.
- **Seeing a block.** `GET /api/v1/t/{tenant}/connections/{id}` lists each blocked scope's current cooldown, shown
  by its kind (`mist.org`, `mist.token`, `mist.stream`, `slack.tenant`, `teams.tenant`, `google_chat.space`,
  `webhook.host`). That end time is live: it moves if the provider extends or lifts the block. A stream's opening
  refused with a 429 or 503 and a `Retry-After` blocks its stream scopes the same way.
