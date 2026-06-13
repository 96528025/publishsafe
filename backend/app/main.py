import logging
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import (
    ALLOWED_EXTENSIONS,
    AVATAR_DIR,
    MAX_UPLOAD_BYTES,
    OUTPUT_DIR,
    UPLOAD_DIR,
)
from .processor import create_job, find_video, jobs, jobs_lock, process_video
from .schemas import JobResponse, ProcessRequest, UploadResponse
from .vision import PersonDetector, draw_preview, ensure_avatar_assets

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

detector: PersonDetector | None = None
detector_lock = threading.Lock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    global detector
    ensure_avatar_assets()
    detector = PersonDetector()
    yield


app = FastAPI(title="PublishSafe API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")
app.mount("/avatars", StaticFiles(directory=AVATAR_DIR), name="avatars")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": "yolov8n", "tracker": "bytetrack"}


@app.post("/api/upload", response_model=UploadResponse)
async def upload_video(file: UploadFile = File(...)) -> UploadResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type. Use: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    video_id = uuid.uuid4().hex
    destination = UPLOAD_DIR / f"{video_id}{suffix}"
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Video must be under 500 MB")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    capture = cv2.VideoCapture(str(destination))
    if not capture.isOpened():
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="The uploaded video could not be decoded")

    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    preview_index = max(0, min(frame_count // 3, int(fps * 2)))
    frame = None
    tracks = []
    ok = False
    assert detector is not None
    try:
        with detector_lock:
            detector.reset_tracking()
        for _ in range(preview_index + 1):
            ok, frame = capture.read()
            if not ok:
                break
            with detector_lock:
                tracks = detector.track(frame)
    except Exception as exc:
        logger.exception("Person detection failed")
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Person detection failed: {exc}") from exc
    capture.release()
    if not ok or frame is None:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="No readable frames were found")

    people_data = [
        (track.track_id, track.bbox, track.confidence) for track in tracks
    ]
    preview = draw_preview(frame, people_data)
    preview_path = UPLOAD_DIR / f"{video_id}_preview.jpg"
    cv2.imwrite(str(preview_path), preview)

    return UploadResponse(
        video_id=video_id,
        filename=file.filename or destination.name,
        preview_url=f"/uploads/{preview_path.name}",
        people=[
            {"track_id": track_id, "bbox": list(bbox), "confidence": confidence}
            for track_id, bbox, confidence in people_data
        ],
        width=width,
        height=height,
        fps=fps,
        frame_count=frame_count,
    )


@app.post("/api/process", response_model=JobResponse)
def start_processing(request: ProcessRequest, background_tasks: BackgroundTasks) -> dict:
    assert detector is not None
    try:
        find_video(request.video_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    job_id = create_job(request.process_scope)

    def locked_process() -> None:
        with detector_lock:
            process_video(
                job_id,
                request.video_id,
                request.selected_track_id,
                request.mode,
                request.avatar_style,
                request.blur_strength,
                request.process_scope,
                detector,
            )

    background_tasks.add_task(locked_process)
    return jobs[job_id]


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> dict:
    with jobs_lock:
        job = jobs.get(job_id)
        job = job.copy() if job else None
    if not job:
        raise HTTPException(status_code=404, detail="Processing job was not found")
    return job
