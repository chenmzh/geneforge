# Security & data protection

What GeneForge does today, and what an operator still has to do. Constructs are often
unpublished IP, so treat the database as confidential.

## 1. Authentication

| Mechanism | Detail |
| --- | --- |
| Password storage | PBKDF2-HMAC-SHA256, 240 000 iterations (configurable), 16-byte random salt per password, `hmac.compare_digest` verification. No plaintext or reversible storage anywhere. |
| Password policy | Minimum length (default 8), must contain a letter and a digit. Tune with `PASSWORD_MIN_LENGTH`. |
| Access tokens | JWT HS256, `type: "access"`, 12 h default (`ACCESS_TOKEN_TTL_MINUTES`). |
| Refresh tokens | JWT HS256, `type: "refresh"`, 14 days. The type claim is verified, so a refresh token cannot be replayed as an access token. |
| API keys | `gf_<prefix>_<secret>`; only the SHA-256 digest is stored, the plaintext is displayed once. Optional expiry, revocable, `last_used_at` tracked. |
| Sessions | Stateless. Rotating `SECRET_KEY` invalidates every token immediately. |

**Operator actions:** set a strong `SECRET_KEY` (a random one is generated per boot
otherwise, so tokens die on restart), change `FIRST_SUPERUSER_PASSWORD` on first login,
and set `ALLOW_REGISTRATION=false` for closed instances.

## 2. Authorisation

Two independent axes, and the stricter one wins:

* **Global role** — `admin` (everything, incl. users/audit/registry), `editor` (normal
  user), `viewer` (read-only account: blocked from creating projects at all).
* **Project role** — `owner` (manage members, rename, delete), `editor` (edit sequences,
  features, primers), `viewer` (read).

All checks flow through `services/projects.require_access()`, reached from routes via the
`ProjectAccess` dependency, and sequence/primer/job routes resolve the owning project
first. Listing endpoints filter by membership, so a non-member cannot even enumerate a
project's existence.

## 3. Input handling

* **Uploads** are capped (`MAX_UPLOAD_BYTES`, 64 MiB) and sniffed by content, not
  extension. A SnapGene `.dna` is detected by its `0x09` header byte.
* **Sequences** are capped (`MAX_SEQUENCE_LENGTH`, 5 Mb) and cleaned to the IUPAC alphabet
  before storage — no unvalidated blob ever reaches the database.
* **Plain text** must be ≥90 % A/C/G/T/U to be accepted as a sequence, so a pasted
  document fails loudly instead of importing as nonsense DNA.
* **Feature coordinates** are clipped to the sequence length server-side; out-of-range
  requests are rejected with 422.
* **Query parameters** are typed and bounded by Pydantic (page sizes, mismatch counts,
  primer lengths, gel percentages).
* **SQL** goes exclusively through SQLAlchemy Core/ORM constructs — no string
  interpolation.

## 4. Outbound requests (SSRF)

The external-resource registry can fetch records server-side. That path is guarded:

1. `EXTERNAL_PROXY_ENABLED` must be true.
2. The resource must be flagged `allow_proxy`.
3. The scheme must be `http`/`https`.
4. The host must match `EXTERNAL_PROXY_ALLOWLIST` (exact or subdomain).
5. Every resolved address must be public — private, loopback, link-local and reserved
   ranges are refused (blocks `169.254.169.254`, `127.0.0.1`, `10/8`, …).
6. Redirects are **not** followed, timeouts are enforced, responses are size-capped.

Nothing else in the product makes outbound connections.

## 5. Auditing

`audit_logs` records `action`, `user_id`, `entity_type`, `entity_id`, `ip_address`
(honouring `X-Forwarded-For`), `user_agent` and a JSON detail blob, written in the same
transaction as the change. Covered actions include login, registration, password change,
API-key create/revoke, project create/update/delete, member add/remove, sequence
create/update/delete/edit/restore/import, feature create/update/delete, auto-annotation
and external imports. Admins query it at `GET /api/v1/audit-logs`.

Sequence history is separate and immutable: every edit appends a `sequence_versions` row
with the full snapshot; restoring appends another version rather than rewriting history.

## 6. Transport & headers

The API sets `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and
`Referrer-Policy: same-origin`, and echoes `X-Request-ID`. CORS is an explicit allow-list
(`CORS_ORIGINS`) — never `*` in production.

**TLS is the operator's job.** Terminate HTTPS at nginx or an ingress, then add HSTS and a
CSP such as:

```
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; connect-src 'self'" always;
```

(`unsafe-inline` for styles is needed by the positioned viewer elements; scripts need no
inline allowance.)

## 7. Deployment hardening checklist

- [ ] `SECRET_KEY` set from a secret manager, not the image or repo.
- [ ] `DEBUG=false`, `ENVIRONMENT=production` (stops error details leaking in responses).
- [ ] Postgres reachable only on the internal network; strong `POSTGRES_PASSWORD`.
- [ ] Redis not exposed publicly (it carries job payloads).
- [ ] TLS terminated in front, HSTS + CSP enabled.
- [ ] `ALLOW_REGISTRATION=false`; create accounts as an admin.
- [ ] `EXTERNAL_PROXY_ALLOWLIST` trimmed to the databases you actually use.
- [ ] Backups: `pg_dump` on a schedule **plus** the `storage/` volume; restore tested.
- [ ] Container runs as the non-root `geneforge` user (already the default).
- [ ] Log shipping configured (JSON logs outside development) with retention.
- [ ] Dependencies patched: `pip install -r requirements.txt --upgrade`, `pnpm update`,
      rebuild the image.

## 8. Known limitations

* No rate limiting yet — put one at the proxy or add the Redis token bucket from the
  roadmap before exposing an instance to the internet.
* No 2FA/SSO; `services/users.py` is the single place to add it.
* Database contents are not encrypted at rest by the application — use volume/disk
  encryption or Postgres TDE.
* Job payloads and results are stored as JSON in the database and may contain sequence
  data; they inherit the database's protections and are deletable per job.
* Uploaded file provenance rows (`imported_files`) keep filenames and checksums, not the
  original bytes.

Report a vulnerability privately to the maintainers rather than via a public issue.
