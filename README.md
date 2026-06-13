# PublishSafe

PublishSafe is a hackathon MVP for privacy-preserving social video publishing.
It detects and tracks people, keeps the selected creator visible, and protects
everyone else with a moving mascot or blur.

## What it does

1. Upload an MP4, MOV, AVI, MKV, or WebM video.
2. YOLOv8n detects people and ByteTrack assigns stable IDs.
3. Select yourself from an annotated preview.
4. Choose a mascot or strong anonymizing blur protection style.
5. Process and download the protected MP4.

The default privacy rule is **protect everyone except the selected creator**.
Uploads and outputs stay in local `uploads/` and `outputs/` directories.

## Project structure

```text
publishsafe/
├── assets/avatars/       # Generated transparent mascot PNGs
├── backend/
│   ├── app/
│   │   ├── main.py       # FastAPI routes and upload analysis
│   │   ├── processor.py  # Background video processing jobs
│   │   ├── tracker.py    # Small fallback tracking utilities
│   │   └── vision.py     # YOLO detection and privacy rendering
│   └── requirements.txt
├── frontend/             # Vite + React UI
├── outputs/
└── uploads/
```

## Setup

Requirements:

- Python 3.10+
- Node.js 18+
- Optional: `ffmpeg` to preserve source audio in the exported MP4

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
```

The first backend start downloads the open-source YOLOv8 nano weights
(`yolov8n.pt`). No model is trained by this project.

## Run

Terminal 1:

```bash
source .venv/bin/activate
uvicorn backend.app.main:app --reload --port 8000
```

Terminal 2:

```bash
cd frontend
npm run dev
```

Open `http://localhost:5173`. API documentation is available at
`http://localhost:8000/docs`.

## Fast testing

Use a short, low-resolution clip while tuning blur or tracking:

```bash
./scripts/make_test_clip.sh /path/to/video.mp4
```

To test a specific section, pass the start time and duration in seconds:

```bash
./scripts/make_test_clip.sh /path/to/video.mp4 10 5
```

The script creates a 960x540, 15 FPS clip in `test-clips/`. Upload that clip
through the normal UI. Five seconds is about 75 frames and processes much
faster than a full 4K video.

## API

- `POST /api/upload`: validate, store, analyze, and create a preview
- `POST /api/process`: start a protected-video job
- `GET /api/jobs/{job_id}`: poll status and frame progress
- `GET /api/health`: detector/tracker health summary

## MVP notes

- Bounding boxes are intentionally used instead of segmentation.
- Tracking uses ByteTrack with a longer occlusion buffer. A clothing-appearance
  fallback recovers the selected creator when IDs switch during crossings.
- Processing is serialized around the YOLO model for demo reliability.
- OpenCV writes video frames. When `ffmpeg` is installed, source audio is
  automatically merged into the final file.
- Tracking can still struggle after a long full-body occlusion. A polished
  version should use learned ReID embeddings and persist analyzed tracks before
  rendering.

## Privacy

PublishSafe performs person detection, not face identification. It does not
attempt to infer names or identities. This MVP stores media locally and does
not upload it to an external service.
