# PublishSafe release notes

## v0.2.0 — private media and fail-closed defaults

- Replaced raw upload/output routes with video-scoped bearer APIs and
  five-minute HMAC-signed derived-media URLs carrying private/no-store headers.
- Added a default 24-hour media-session TTL, early `DELETE`, restricted file
  permissions, active frame/FFmpeg cancellation, and localhost-only Compose
  binding. These are local capability controls, not multi-user authentication,
  TLS, or secure erase.
- Moved preview candidates and boxes behind a server-owned private manifest.
  Client-supplied candidate geometry is rejected, and full rendering starts
  from the selected upload-preview appearance anchor instead of trusting a
  recycled tracker integer.
- Added session-authorized preview-capability refresh, fixed-name attachment
  downloads, and UI reporting when deletion is not confirmed.
- Changed the default audio policy to removal. Explicit preservation fails the
  job if it cannot be honored instead of silently changing policy.
- Added conservative padded-box fallback for obviously corrupt/missing masks
  and blur-all-detected-people fallback for ambiguous creator ReID. The guard
  thresholds are defensive and uncalibrated, not measured privacy guarantees.
- Added a model-independent privacy evaluation harness for annotated ground
  truth and redaction-candidate predictions.
- Added deterministic maximum-cardinality matching, person recall, longest
  consecutive missed-redaction runs per ground-truth person/track, and explicit
  `occlusion`, `low_light`, `crowd`, and `profile` slices.
- Added synthetic fixture tests that validate metric calculations only. They are
  not model-performance results and no real-video benchmark is claimed.
- Added an optional YOLO prediction runner whose documented scope is detector
  box coverage, not the complete PublishSafe render pipeline.
- Added dataset consent/licensing guidance, a threat model, a full-video human
  review checklist, sensitive-media reporting rules, and safe issue forms.
- Reordered the README around a recruiter review path and separated automated
  evidence from unverified ML, privacy, performance, and deployment claims.
- Refreshed transitive frontend build dependencies. On 2026-09-01,
  `npm audit --audit-level=low` against the npm registry reported zero known
  vulnerabilities for the prepared lockfile; this is a time-bound release
  check, not a permanent guarantee.

This release keeps jobs in memory and uses FastAPI background tasks; it does
not add the deferred durable-worker/PostgreSQL control plane. No real-video
privacy benchmark is claimed.

## v0.1.0

Initial public MVP release.

## Highlights

- Local-first video upload and MP4 export
- YOLOv8n-seg person detection and instance masks
- ByteTrack person IDs with creator appearance recovery
- Select one creator to preserve
- Adjustable person-mask blur control
- Instant single-frame effect preview
- Faster 10-second video preview
- Experimental mascot avatar mode
- Docker Compose one-command startup

## Known limitations

- Full-resolution processing is CPU intensive and can be slow on 4K footage.
- Tracking can fail after long occlusions or when people wear similar clothing.
- Blur is weak de-identification, and avatar overlays still use bounding boxes.
- Audio, text, plates, reflections, gait, clothing, and context are not
  automatically de-identified.
- Detection, masks, and tracking can miss people or expose frames; human review
  of the complete export is required.
- This release is intended for local use, not direct public internet exposure.
