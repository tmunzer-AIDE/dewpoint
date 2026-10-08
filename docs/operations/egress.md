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

### Mail (SMTP)

An `email` connection names an SMTP server, which the runtime speaks itself (plugins-3 D20): a step names neither the
server nor the sender, and never holds the password.

- **Security.** `starttls` (port 587, RFC 6409): the server must offer STARTTLS, or nothing more is sent. `tls` (port
  465, RFC 8314): TLS from the first byte. `none`: only to an allowlisted address, and never with a password. TLS is
  1.2 or later, the certificate checked against the server's name.
- **Signing in.** With a username and password, the runtime signs in once TLS is up, with PLAIN or else LOGIN (never
  CRAM-MD5); both must be ASCII. A server offering neither fails the step, having sent nothing.
- **What's sent.** The connection's sender, 1 to 50 recipients, each once, and a plain-text message the runtime puts on
  the wire whole: a message with a bare CR or LF, a NUL or a line past 998 octets is refused before connecting. EHLO
  names the sender's domain, never the worker's host name.
- **Outcomes.** A server's refusal before the message's end sends nothing: a 4yz is retried, a 5yz fails. After it, a
  250 is sent and a 4yz or 5yz is the server's definite refusal (RFC 5321 §4.2.5); a connection lost before the
  server's answer leaves the step `outcome_unknown`, never retried. Recipients refused while others were accepted are
  named in the step's output.
- **Bounds.** A server's reply is at most 100 lines and 64 KiB, and a session at most 120 s (aborted past it). Mail
  sessions run on a pool of 8 threads of their own, so a slow server never delays the rest of the worker's egress;
  when all 8 are busy, further sends wait. A cancelled step aborts its send wherever it is.
- **Verify.** Connects, greets, secures and signs in, then quits; it never sends MAIL.
- **Firewalls.** Allow the server's host on its port (587 or 465; 25 for an allowlisted relay).

### Syslog

A `syslog` connection names a receiver (plugins-3 D21): `tls` (the default, port 6514, octet counting, TLS 1.2 or
later, the certificate checked; RFC 5425), `udp` (port 514, one message a datagram; RFC 5426) or `tcp` (octet counting,
or LF framing for legacy receivers; RFC 6587). UDP and TCP are plaintext: their receiver needs an allowlist entry.
There are no client certificates. A message is at most 2048 octets over UDP and 8192 over TCP and TLS, cut to fit.
Syslog has no acknowledgement: a sent message was handed over, not necessarily received, and a send is never retried
once a byte may have left.

### PagerDuty

A `pagerduty` connection sends alert events through PagerDuty's Events API v2 (plugins-3 D22). It names the service
region, which picks the host, and holds the integration key.

- **Hosts.** `us`: `https://events.pagerduty.com/v2/enqueue`; `eu`: `https://events.eu.pagerduty.com/v2/enqueue`.
  PagerDuty documents only the EU host; its path is taken to be the US one. A US host forwards an EU key's events.
- **The integration key.** The 32-character key of a service's Events API v2 integration. The runtime puts it into
  each event as `routing_key`; a step never holds it, can't set that field and can't send any body but a JSON object.
  No authentication header is sent.
- **Nothing is sent to test a connection.** Checking a key means sending an event, which would page someone: a wrong
  key fails at its first send.
- **A retry pages once.** A trigger's `dedup_key` is its config's, else one derived from the run and the step (64
  hex characters), so a retried trigger joins the alert it opened. If that alert was resolved meanwhile, PagerDuty
  opens a new one. Acknowledge and resolve name the alert by its `dedup_key`; with no open alert, PagerDuty drops
  them.
- **Order isn't promised.** PagerDuty processes events asynchronously and doesn't document their order: an
  acknowledge or resolve sent right after its trigger may be processed first and dropped, leaving the alert open.
- **Outcomes.** A 202 means PagerDuty accepted the event. A 400 (`pagerduty.invalid_event`) or another 4xx
  (`pagerduty.refused`) fails the step; a 408 or 425 is retried. A 429, a 5xx, or a 2xx other than 202 is retried
  too, as PagerDuty advises, after 30 s, then 60 s, then 120 s: four attempts in three and a half minutes, unless the
  step sets its own number. A 429's or 503's `Retry-After` is waited out within the attempt, at most 3 times and 20 s
  in all.
- **Bounds.** An event is at most 500,000 bytes as sent (PagerDuty takes 512 KB); the text and the fields' values are
  cut to fit, and the step names what it cut. A summary is one line of at most 1024 bytes (PagerDuty's 1024 in
  whichever unit it counts); a title cut to fit is named too.
- **Firewalls.** Allow the region's host on port 443.

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
- **Teams.** One scope a tenant (`teams.tenant`): bursts of 5, then 20 more in 300 s, so never more than 25 posts in
  any 300 s. That's Teams' limit for one Teams connection posting as the flow bot; a webhook URL doesn't name the
  connection, so a tenant's flows share it.
  Microsoft turns off a flow that stays throttled for 14 days.
- **Google Chat.** One scope a space (`google_chat.space`), read from the URL: 1 a second, no burst, shared by all the
  space's webhooks.
- **Webhook.** One scope a receiver's host (`webhook.host`): bursts of 5, then 1 a second.
- **Email.** One scope a server host (`email.server`): bursts of 5, then 1 a second. Syslog has none.
- **PagerDuty.** One scope an integration key (`pagerduty.integration`): bursts of 20, then 100 a minute, so never
  more than 120 events in any 60 s (PagerDuty's limit a key). Its account's own limits apply too.
- **When no token is available.** A step waits up to 10 s. After that it fails with `cooldown` and sends nothing.
- **When the provider sends `Retry-After`.** That scope is blocked for every run, for up to an hour.
- **Seeing a block.** `GET /api/v1/t/{tenant}/connections/{id}` lists each blocked scope's current cooldown, shown
  by its kind (`mist.org`, `mist.token`, `mist.stream`, `slack.tenant`, `teams.tenant`, `google_chat.space`,
  `webhook.host`, `email.server`, `pagerduty.integration`). That end time is live: it moves if the provider extends
  or lifts the block. A stream's opening refused with a 429 or 503 and a `Retry-After` blocks its stream scopes the
  same way.
