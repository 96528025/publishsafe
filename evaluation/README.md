# Privacy evaluation harness

This directory contains a deterministic, offline harness for evaluating
**box-level redaction-candidate coverage**. It separates annotations,
predictions, and metrics so the same predictions can be re-scored without
loading a model or video.

This harness does not prove that a rendered video is anonymous or safe to
publish. A box match says only that a predicted redaction candidate overlaps an
annotated person. It does not measure mask holes, blur reversibility, identity
leakage, audio, text, reflections, creator-selection errors, tracking quality,
or final export correctness. See [the threat model](../docs/threat-model.md).

## Metric definitions

Only ground-truth person instances with `should_redact: true` enter the privacy
metrics. A selected creator should be annotated with `should_redact: false` and
is excluded from both the numerator and denominator.

- **Person recall** = matched redaction targets / eligible ground-truth person
  instances. Matching is one-to-one and uses bounding-box intersection over
  union (IoU) at the configured threshold. A deterministic maximum-cardinality
  bipartite matching maximizes the number of valid target/prediction pairs; one
  predicted box cannot satisfy two people. IoU only determines valid edges and
  their stable traversal order, so a single high-IoU choice cannot incorrectly
  reduce recall by blocking two valid matches.
- **Longest consecutive unredacted frames** = the longest run of consecutive,
  densely annotated frames in which the same eligible ground-truth
  `person_id`/track has no matched redaction candidate. The run resets when the
  person is absent, no longer eligible, or matched. The report records the
  video, person ID, first frame, last frame, frame count, and duration.
- **Scenario breakdown** applies the same metrics to annotations that explicitly
  carry a scenario label. The standard labels are `occlusion`, `low_light`,
  `crowd`, and `profile`. Labels are never inferred from pixels or filenames.
  Labels can overlap, so scenario counts are not expected to sum to the overall
  count. Dataset-specific labels are also preserved.

Ground truth must annotate every frame from zero through `frame_count - 1`.
This dense requirement prevents a gap in annotation from being misreported as
a detector success or from joining two non-consecutive miss runs. A missing
prediction frame is valid input and counts as having no redaction candidates.

If a standard scenario has no eligible annotated people, its recall is `null`
and its count is zero. That is “not measured,” not a perfect result.

## Run the model-independent evaluator

From the repository root:

```bash
python -m evaluation.evaluate \
  --ground-truth path/to/ground_truth.json \
  --predictions path/to/predictions.json \
  --iou-threshold 0.5 \
  --output path/to/report.json
```

Omit `--output` to write the JSON report to standard output. Given the same
input JSON and IoU threshold, the evaluator is deterministic.

Run the metric tests without any model weights or media:

```bash
pytest evaluation/tests
```

The files in `fixtures/` are hand-authored geometric test data with no media or
person information. Their scores validate the harness math and edge cases
only. **They are not model-performance results, a privacy benchmark, or evidence
that PublishSafe works on real video.** Do not publish fixture scores as product
metrics.

## Ground-truth format

Coordinates use `[x1, y1, x2, y2]` in source-frame pixels. A stable
`person_id` must follow the same annotated person through adjacent frames; it
is a ground-truth track identifier, not a runtime ByteTrack ID.

```json
{
  "schema_version": "1.0",
  "dataset": {
    "name": "dataset name",
    "version": "immutable version or date",
    "license": "license or consent basis",
    "source": "source URL or internal provenance record"
  },
  "videos": [
    {
      "video_id": "non-identifying-id",
      "media_path": "optional/local-only/video.mp4",
      "frame_count": 2,
      "fps": 30.0,
      "scene_tags": [],
      "frames": [
        {
          "frame_index": 0,
          "scene_tags": ["crowd"],
          "people": [
            {
              "person_id": "person-001",
              "bbox": [10, 20, 80, 200],
              "should_redact": true,
              "scene_tags": ["profile"]
            }
          ]
        },
        {
          "frame_index": 1,
          "scene_tags": ["occlusion", "low_light"],
          "people": []
        }
      ]
    }
  ]
}
```

Tags can be assigned at video, frame, or person-instance level. Choose the
narrowest level justified by the annotation. Define dataset-specific labeling
rules before annotation; for example, state what visible fraction qualifies as
`occlusion`, what illumination rule qualifies as `low_light`, and what person
count qualifies as `crowd`. Keep those rules with the dataset version.

The pure evaluator ignores `media_path`. It is used only by an optional runner.

## Prediction format

Predictions describe proposed person-redaction regions, not final pixels:

```json
{
  "schema_version": "1.0",
  "model": {
    "name": "model name",
    "version": "weight checksum or immutable release",
    "runner": "script/package version",
    "parameters": {
      "confidence": 0.3,
      "imgsz": 640,
      "device": "cpu"
    }
  },
  "videos": [
    {
      "video_id": "non-identifying-id",
      "frames": [
        {
          "frame_index": 0,
          "redactions": [
            {"bbox": [11, 19, 79, 201], "confidence": 0.91}
          ]
        }
      ]
    }
  ]
}
```

Prediction frames may be omitted; the evaluator treats them as empty. Unknown
videos, duplicate frames, invalid boxes, and non-dense ground truth fail closed
with an input error.

## Optional YOLO prediction runner

`evaluation.runners.yolo_seg` is a pluggable example that runs a real
Ultralytics person detector over media referenced by `media_path` and produces
prediction JSON:

```bash
python -m evaluation.runners.yolo_seg \
  --ground-truth path/to/ground_truth.json \
  --output path/to/yolo_predictions.json \
  --model yolov8n-seg.pt \
  --confidence 0.3 \
  --imgsz 640 \
  --device cpu
```

It requires the runtime dependencies in `backend/requirements.txt` and may
download weights if they are not already present. The runner records the
Ultralytics package version and, when it can resolve the loaded local weight
file, its SHA-256 digest. A `null` digest is explicitly “not resolved,” not an
immutable model identity; resolve and record the weight checksum before
reporting results.

The runner intentionally emits raw person boxes. It does **not** exercise the
selected-creator exclusion, ByteTrack, appearance fallback, segmentation-mask
coverage, blur renderer, avatar renderer, audio handling, or exported MP4.
Therefore its report is detector-coverage evidence only. A future end-to-end
runner should output actual redaction regions from the complete pipeline and
add pixel/mask and export checks rather than relabeling detector coverage as
privacy performance.

## Dataset, consent, and licensing checklist

No real evaluation media or benchmark result is included in this repository.
Before adding or reporting a dataset:

1. Use footage you own with informed participant consent, or a dataset whose
   license explicitly permits this evaluation and redistribution status.
2. Record the dataset name, immutable version, source URL, access date, license,
   redistribution restrictions, and consent/provenance notes.
3. Confirm that evaluation and publication of derived annotations/results are
   allowed; a video being publicly reachable does not by itself grant those
   rights.
4. Keep private or identifying media outside Git. Use non-identifying IDs and
   local `media_path` values. Do not upload private video, extracted frames, or
   identifying logs to an issue or pull request.
5. Define annotation instructions and perform a second-person review of a
   sample. Record ambiguous-person and ignored-region policies.
6. Pin model, runner, parameters, IoU threshold, operating system, hardware,
   dependency versions, and commit hash with every report.
7. Report every evaluated clip and scenario slice, including zero-eligible
   slices as “not measured.” Do not select only favorable clips.

Before sharing any rendered output, use the human-review checklist in the
[threat model](../docs/threat-model.md).

## What a defensible report must say

A report should state that the metric is box-level redaction-candidate recall,
name the annotated dataset and license/consent basis, and link the exact
configuration and commit. It should separately list what was not measured.

Do not describe a result as “privacy-safe,” “anonymous,” or “verified” solely
because this harness produced high person recall. The remaining privacy risks
include temporal misses, mask coverage, weak blur, identity signals outside a
person box, audio, text, reflections, tracking/creator confusion, and export
failures.
