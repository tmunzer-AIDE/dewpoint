# Temporal's certificates: issuing and rotating them (outline)

Status: an outline for the owner (2b-4b M4). The owner ruled mutual TLS production's target and required an
operational plan for issuing and rotating its certificates **before real-target qualification**. The decisions marked
**Owner** are open; the rest follows from how the D12 server (`deploy/temporal`) and Dewpoint's processes use them.
Nothing here is proven on a real target yet.

## What needs a certificate

| Certificate | Signed by | Used by | Names |
|---|---|---|---|
| The frontend's server certificate | the client CA | the Temporal server's frontend (gRPC and HTTP API) | the address clients dial (SAN) |
| The internode certificate | the internode CA, its own | every Temporal service, as server and as client; the internal frontend | the internode name (SAN) |
| One client certificate per Dewpoint identity | the client CA | the worker, the dispatcher, the retention process, operators' CLI | its common name (CN), mapped to a role |
| The platform admin's client certificate | the client CA | registering and updating the namespace | a CN with `temporal-system:admin` |

- **Roles come from the CN.** The authorizer's roles file (`DEWPOINT_AUTHZ_CERT_ROLES`) maps each CN to its
  permissions (`<namespace>:write` for Dewpoint's processes, `temporal-system:admin` for the platform admin only:
  Temporal's cluster scope; a bare `system` is refused). A CN it
  doesn't list has no role. The server reads it at startup.
- **The internode certificate is a system-admin credential** on the internal frontend (Temporal gives it that role
  there; the namespace rules still apply). Guard it as the Temporal store's administrators are guarded (D12b): on the
  server's hosts only, never on a Dewpoint host.

## Decisions for the owner

- **Owner:** which CA issues them (your PKI, an internal CA, a certificate manager) and who operates it.
- **Owner:** the lifetimes. Temporal's server doesn't check revocation lists, so a certificate stays valid until it
  expires or its CA is distrusted: keep client certificates short-lived (for example 30 to 90 days) and rotate them
  routinely.
- **Owner:** where the keys live (a secret manager mounted as files, readable by the process's user only) and how a
  host gets its certificate (a CSR from the host, the key never leaving it, is the default proposed).
- **Owner:** the CN convention, proposed `dewpoint-<process>-<deployment>`, one per process kind, not per host.

## Rotation

1. **A client certificate** (a Dewpoint process): issue the new one with the same CN, replace the files, restart the
   process (Dewpoint reads its certificate when it connects; unlike the bearer token file, a certificate isn't
   reloaded live). Roll processes one at a time; the old certificate keeps working until it expires.
2. **The frontend's server certificate:** issue it with the same names, replace the files on the server, restart (or
   rely on Temporal's own reload, **to verify on v1.32.0** before it's relied on).
3. **The internode certificate:** as the server's, all services in one process: one restart.
4. **A CA** (scheduled, or after a compromise): add the new CA beside the old in every trust bundle first (the
   server's `clientCaFiles` and `rootCaFiles`, each process's `DEWPOINT_TEMPORAL_TLS_CA`), restart; then reissue every
   certificate from the new CA and roll them out; then remove the old CA everywhere.
5. **Revoking one identity:** remove its CN from the roles file and restart the server (it then has no role), then let
   the certificate expire. For a compromised CA, rotate the CA (4).

## Monitoring

- Temporal's own certificate-expiry checks (`global.tls.expirationChecks`) warn ahead of expiry, sent to the same
  owner-chosen alert destination as the audit monitor's.
- A Dewpoint process that can't connect after a rotation fails its startup visibly (exit 2 on unreadable files); the
  worker's health and `dewpoint temporal check` show it.

## Before real-target qualification

- This plan's decisions made and written into the deployment guide.
- One rehearsal on the real target, in an isolated test namespace: a client certificate rotated with a rolling
  restart, the server's certificate rotated, and a revoked CN shown to have no role afterwards.
