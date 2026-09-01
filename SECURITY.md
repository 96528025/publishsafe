# Security and sensitive-media policy

PublishSafe is a local-first MVP, not a hosted service or a security-certified
anonymization system. Use the current `main` branch or latest published release
when reproducing a problem. The project does not currently promise a security
support window or response-time SLA.

## Report a vulnerability privately

Use a [private GitHub Security Advisory](https://github.com/96528025/publishsafe/security/advisories/new)
for vulnerabilities or privacy failures that could put users or media at risk.
Include a minimal, sanitized description, affected commit/release, impact, and
reproduction steps. If possible, reproduce with generated geometry or public,
properly licensed sample media.

Do not open a public issue for an unpatched vulnerability.

## Never upload private media

**Do not attach or link private, confidential, identifying, or unlicensed
videos, audio, extracted frames, preview images, masks, or outputs to a GitHub
issue, pull request, discussion, or security report.** Do not include real
names, precise locations, private filenames/paths, access tokens, credentials,
or unredacted logs.

Describe the failure with non-identifying frame numbers, geometric boxes, or a
small synthetic fixture. If a maintainer needs more information, agree on a
safe process first; an unsolicited private-media upload is not an acceptable
reproduction.

## Deployment boundary

The current local workflow issues a video-scoped bearer session capability for
preview, process, job, and delete APIs. Derived media uses five-minute
HMAC-signed URLs with private/no-store response headers; raw uploads are not
mounted as public static routes. Sessions expire after a default 24-hour TTL and
can be removed earlier through the delete API. Docker Compose binds the web
entry point to localhost by default.

These controls do not provide user accounts, identity-aware multi-user
authorization, TLS termination, tenant isolation, secure erase, or protection
after a live capability is copied. Ordinary deletion cannot remove browser
caches, open handles, backups, snapshots, or downstream copies. Run only on a
trusted host; do not expose the service directly to the public internet.

For privacy limitations and the pre-publication review checklist, read the
[threat model](docs/threat-model.md).
