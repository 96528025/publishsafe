# Threat model and human-review guide

Status: documentation for the current local-first MVP. This is a risk inventory,
not a security certification or a claim that processed media is anonymous.

## Intended use and non-goals

PublishSafe is a local video-redaction aid for a person who owns or is
authorized to process a clip. Its default workflow attempts to leave one
selected creator visible and obscure other detected people. It is designed for
review on the host that runs the application.

The current MVP is **not** designed for direct public-internet exposure,
multi-tenant use, unattended high-risk publishing, biometric anonymization,
evidentiary redaction, or compliance with a particular privacy regime. It uses
local bearer capabilities and expiring media links, but has no user accounts,
multi-user authorization model, TLS termination, tenant isolation, secure
erase, or guarantee that every sensitive signal is removed.

## Assets and adversaries

Assets that may require protection include:

- source videos, frames, preview images, masks, and rendered outputs;
- identities and activities of people visible or audible in a clip;
- location, time, relationships, routines, and other contextual information;
- filenames, paths, model configuration, logs, and media metadata.

Relevant observers include an ordinary viewer, someone who already knows a
person or location, a motivated re-identification attacker, another user or
process that can reach the local service, and someone who receives a forgotten
source/preview/output file.

## Current trust boundary and data flow

The browser sends the source video to the FastAPI process running on the same
host or Docker host. On upload, the backend creates a per-video local session
and returns a bearer session capability. Frame preview, processing, job status,
and deletion APIs require that capability and check that it is scoped to the
same video. Raw uploads are not mounted as public static routes.

Preview and output responses use HMAC-signed, artifact-scoped media capability
URLs that expire after five minutes. Media responses include private/no-store
cache headers. The UI refreshes an output URL through the capability-protected
job endpoint rather than relying on a permanent link. Docker Compose binds the
web entry point to `127.0.0.1` by default.

These are local capability controls, not identity-aware authentication. Anyone
who obtains a live bearer or signed media capability can exercise its scope.
They do not supply TLS, protect a compromised browser/host, isolate multiple
untrusted users, or make a deliberately reconfigured network exposure safe.

YOLO/ByteTrack and OpenCV processing run on the host. PublishSafe's application
code does not intentionally send video to an external inference service.
However, first use may download model weights, package installation contacts
dependency registries, and an operator may use external tools outside this
application. A delete endpoint removes a session on request, the UI invokes it
when resetting, and a periodic cleanup removes expired sessions after a
default 24-hour TTL. Cleanup is ordinary filesystem deletion, not secure erase;
copies can remain in open handles, browser/device caches, backups, snapshots,
or recovery storage.

## Primary privacy failures

### Detection, segmentation, and temporal coverage

- A person may be missed entirely or for one or more frames, especially when
  small, partially occluded, backlit, motion-blurred, in low light, in a crowd,
  or shown in profile.
- A segmentation mask can omit a face, hair, hand, limb, reflection, or edge.
  Dilation and feathering reduce visible seams but do not prove full coverage.
- Mask fallback can cover a bounding box rather than the exact body, yet still
  miss signals outside it.
- ByteTrack IDs can switch, disappear, or be reassigned during crossings and
  occlusions. Clothing-histogram recovery is a heuristic, not identity
  verification. It can preserve the wrong person or redact the creator.
- Frame-level flicker can expose a person even when average recall looks high.
  The evaluation harness therefore reports the longest missed run for the same
  annotated ground-truth person/track, but box coverage still does not inspect
  rendered pixels.
- Missing, malformed, empty, or implausibly small segmentation masks fall back
  to padded bounding-box blur rather than leaving the person exempt. Those
  corruption thresholds are defensive heuristics and have not been calibrated
  on an annotated privacy dataset; a plausible but incomplete mask can pass.
- When creator ReID evidence is absent or ambiguous, the current renderer
  conservatively blurs every detected person for that frame instead of guessing
  an exemption. This can protect privacy at the cost of redacting the creator,
  and the underlying appearance-distance thresholds are uncalibrated.

### Blur is weak de-identification

Blur is a visual obstruction, not cryptographic deletion. Depending on source
resolution, blur strength, movement, prior knowledge, and auxiliary footage, a
viewer may infer or reconstruct identity. A blurred person may remain
recognizable through:

- gait, posture, height, body shape, mobility aids, or characteristic movement;
- clothing, uniforms, shoes, jewelry, bags, tattoos, hair, and accessories;
- voice, names, conversations, music choices, or other source audio;
- companions, vehicles, recurring routes, homes, workplaces, landmarks, and
  event context;
- license plates, street signs, badges, mail, screens, captions, or other text;
- mirrors, windows, water, polished surfaces, shadows, and background
  reflections;
- timestamps, GPS, device information, thumbnails, filenames, or other
  metadata outside the rendered person region.

PublishSafe currently targets detected people. It does not claim to detect or
remove faces separately, plates, documents, screens, reflections, location
clues, or metadata. Source audio is removed by default. The API can explicitly
request preservation; that opt-in fails the job if audio cannot be preserved
rather than silently changing the policy. Preserved audio can disclose voices,
names, conversations, and context.

### Avatar mode boundary

Avatar mode is an experimental visual effect, not a stronger privacy mode. The
avatar is scaled to a detected bounding box and can still expose body parts,
mask gaps, movement, background reflections, shadows, audio, text, and context.
Tracking failure can place it over the wrong person or leave a target visible.
Do not describe avatar output as anonymized without independent review and
evidence appropriate to the use case.

### Storage, capabilities, and operational exposure

- Uploaded media, extracted previews/masks, and results remain on disk until
  explicit deletion or expiry cleanup; deletion is not secure erase.
- Session bearer capabilities live in the browser state. Signed derived-media
  URLs remain usable by their holder until their short expiry.
- The default TTL is a cleanup bound, not proof that every copy has vanished at
  exactly 24 hours. Active jobs can delay removal, and backups/caches are
  outside the cleanup boundary.
- Logs, screenshots, shell history, browser cache, backups, cloud-sync tools,
  and crash reports can create additional copies.
- Container bind mounts make files available to both host and container.
- A malicious or malformed video and the media/model parsing supply chain are
  outside the protection of the redaction algorithm.

Compose listens on localhost by default. Continue to run on a trusted host and
do not expose the API or frontend directly to the public internet; the bearer
capability model is not a substitute for TLS and multi-user access control.

## Current controls and their limits

| Control | What it helps with | What it does not establish |
| --- | --- | --- |
| Host-local processing | Avoids an intentional third-party inference upload | Access control, deletion, or isolation on the host |
| Video-scoped bearer capability | Restricts preview/process/job/delete APIs to a holder of the upload session secret | User identity, TLS, multi-user isolation, or safety after token theft |
| Five-minute signed media URLs + no-store headers | Replaces permanent/raw media routes and limits link lifetime/cache intent | Revocation of a copied live link, hostile clients, screenshots, or downstream copies |
| Default 24-hour TTL + `DELETE` | Bounds normal on-host session retention and supports early removal | Secure erase, exact deletion from open handles/backups, or legal retention compliance |
| Localhost-only Compose binding | Reduces accidental LAN/public exposure in the default profile | Safety if the operator changes binding/proxy rules or the host is compromised |
| Person segmentation plus dilation/feathering | Obscures many detected person pixels | Complete body coverage or irreversible anonymization |
| Corrupt-mask fallback to padded box | Avoids silently trusting an obviously broken/missing mask | Calibrated adequacy or detection of every incomplete-but-plausible mask |
| Every-frame processing | Avoids deliberate detector frame skipping | Detection success on every frame |
| Conservative ambiguous-ReID fallback | Blurs all detected people instead of guessing a creator exemption | Calibrated thresholds, detection of missed people, or correct identity association |
| Audio removed by default | Avoids retaining source voices/names unless explicitly requested | Visual/contextual anonymity or protection when preservation is opted into |
| Single-frame and short previews | Supports early visual inspection | Full-video or audio review |
| Offline evaluation harness | Reproducibly measures annotated box coverage and temporal misses | Mask/pixel, identity, audio, text, reflection, or export privacy |
| Model-free automated tests | Checks application logic without downloading weights | Real model accuracy or end-to-end video behavior |

## Required human review before publishing

Treat automated output as a draft. A reviewer should:

1. Watch the **entire exported file**, at normal speed and frame-by-frame around
   cuts, entrances, crossings, occlusions, camera motion, low light, and crowds.
2. Confirm every person who should be redacted, including people at frame edges,
   in the background, on screens, and in reflections. Check hair, hands, feet,
   and mask boundaries for flashes or flicker.
3. Verify that the intended creator remains visible and that tracking never
   switches the exemption to another person.
4. Listen to the complete audio. Remove or edit names, voices, conversations,
   announcements, and other identifying sounds with a separate tool when
   needed.
5. Inspect plates, signs, badges, mail, screens, tattoos, clothing, locations,
   shadows, mirrors, windows, and other contextual identifiers. Redact them
   separately.
6. Inspect file metadata and the filename, and review the exact copy that will
   be uploaded rather than an intermediate preview.
7. Confirm the job reports the intended audio policy. If source audio was
   explicitly preserved, treat it as unredacted until separately reviewed.
8. Have a second person review high-risk material. Do not publish when a miss is
   ambiguous; edit the source or use a tool intended for manual redaction.
9. After verifying the destination copy, use Reset/`DELETE /api/videos/{video_id}`
   for early session removal and remove unneeded logs, test clips, downstream
   copies, and backups according to the owner's retention obligations. The
   automatic TTL is a fallback, not secure erase.

If disclosure could cause material harm, do not rely on PublishSafe as the sole
control.

## Evaluation and acceptance criteria

The harness in [`evaluation/`](../evaluation/README.md) accepts dense,
frame-by-frame annotations and redaction-candidate predictions. It reports
person recall and longest consecutive misses overall and for explicit
`occlusion`, `low_light`, `crowd`, and `profile` labels. A synthetic fixture is
used only to verify the metric implementation; it is not a real-video
benchmark.

Before making any performance claim, define an annotated dataset, consent and
license basis, scenario-labeling rules, configuration, and review procedure.
Even strong box-recall results require separate mask/pixel, temporal rendering,
audio, text/reflection, creator-selection, and exported-file evaluation.

## Mitigation roadmap (not implemented)

These are future defenses, not current capabilities:

- identity-aware multi-user authentication/authorization and production TLS;
- configurable retention, stronger deletion verification, and a visible
  inventory of stored/downstream files;
- end-to-end rendered-mask coverage and temporal flicker evaluation;
- explicit face, plate, text, screen, and reflection redaction tools;
- audio transcription/muting/redaction and metadata stripping with verification;
- uncertainty warnings and fail-closed/manual masks for low-confidence frames;
- independent adversarial re-identification and high-risk use-case review;
- dependency/model provenance checks and pinned weight hashes.

Security-reporting guidance is in [`SECURITY.md`](../SECURITY.md).
