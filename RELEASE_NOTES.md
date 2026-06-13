# PublishSafe v0.1.0

Initial public MVP release.

## Highlights

- Local-first video upload and MP4 export
- YOLOv8n-seg person detection and instance masks
- ByteTrack person IDs with creator appearance recovery
- Select one creator to preserve
- Adjustable 10-100 privacy blur
- Instant single-frame effect preview
- Faster 10-second video preview
- Experimental mascot avatar mode
- Docker Compose one-command startup

## Known limitations

- Full-resolution processing is CPU intensive and can be slow on 4K footage.
- Tracking can fail after long occlusions or when people wear similar clothing.
- Avatar overlays still use bounding boxes.
- This release is intended for local use, not direct public internet exposure.
