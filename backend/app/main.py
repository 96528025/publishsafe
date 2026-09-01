import logging
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Header,
    HTTPException,
    Path as ApiPath,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .capabilities import (
    CapabilityError,
    issue_media_capability,
    issue_session_capability,
    verify_capability,
)
from .config import (
    ALLOWED_EXTENSIONS,
    AVATAR_DIR,
    CLEANUP_INTERVAL_SECONDS,
    MAX_UPLOAD_BYTES,
    MEDIA_CAPABILITY_TTL_SECONDS,
    MEDIA_TTL_SECONDS,
    RUNTIME_PROFILE,
    VIDEO_ENCODER,
)
from .processor import create_job, jobs, jobs_lock, process_video
from .schemas import (
    FramePreviewRequest,
    FramePreviewResponse,
    JobResponse,
    ProcessRequest,
    UploadResponse,
)
from .storage import (
    cleanup_expired_media as cleanup_storage,
    create_upload_session,
    delete_video_media,
    find_video,
    open_private_binary,
    resolve_output,
    resolve_preview,
    secure_file,
    session_exists,
    tighten_existing_permissions,
    upload_session_dir,
)
from .vision import PersonDetector, blur_person, draw_preview, ensure_avatar_assets

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)


class CapabilityAccessLogFilter(logging.Filter):
    """Keep bearer-like media capabilities out of Uvicorn access logs."""

    pattern = re.compile(r"(/api/media/)[A-Za-z0-9_.-]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                self.pattern.sub(r"\1[REDACTED]", value)
                if isinstance(value, str)
                else value
                for value in record.args
            )
        return True


logging.getLogger("uvicorn.access").addFilter(CapabilityAccessLogFilter())

detector: PersonDetector | None = None
detector_lock = threading.Lock()


def cleanup_expired_media(*, now: float | None = None) -> set[str]:
    with jobs_lock:
        active_video_ids = {
            job["video_id"]
            for job in jobs.values()
            if job.get("status") in {"queued", "processing"}
        }
    removed = cleanup_storage(now=now, preserve_video_ids=active_video_ids)
    if removed:
        with jobs_lock:
            for job_id in [
                key for key, job in jobs.items() if job.get("video_id") in removed
            ]:
                jobs.pop(job_id, None)
        logger.info("Expired media removed for %d session(s)", len(removed))
    return removed


def _cleanup_loop(stop: threading.Event) -> None:
    while not stop.wait(CLEANUP_INTERVAL_SECONDS):
        try:
            cleanup_expired_media()
        except Exception:
            logger.exception("Periodic media cleanup failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    global detector
    tighten_existing_permissions()
    cleanup_expired_media()
    cleanup_stop = threading.Event()
    cleanup_thread = threading.Thread(
        target=_cleanup_loop,
        args=(cleanup_stop,),
        name="publishsafe-media-cleanup",
        daemon=True,
    )
    cleanup_thread.start()
    try:
        ensure_avatar_assets()
        detector = PersonDetector()
        yield
    finally:
        cleanup_stop.set()
        cleanup_thread.join(timeout=2)


app = FastAPI(title="PublishSafe API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/avatars", StaticFiles(directory=AVATAR_DIR), name="avatars")


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="A session capability is required")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="A valid Bearer capability is required")
    return token


def _require_session(video_id: str, authorization: str | None) -> dict:
    try:
        claims = verify_capability(_bearer_token(authorization), "session")
    except CapabilityError as exc:
        raise HTTPException(
            status_code=401,
            detail="The session capability is invalid or expired",
        ) from exc
    if claims["video_id"] != video_id:
        raise HTTPException(
            status_code=403,
            detail="The capability does not grant access to this video",
        )
    if not session_exists(video_id):
        raise HTTPException(status_code=404, detail="Uploaded video was not found")
    return claims


def _media_url(
    video_id: str,
    artifact: str,
    *,
    job_id: str | None = None,
) -> str:
    token = issue_media_capability(
        video_id,
        artifact,
        MEDIA_CAPABILITY_TTL_SECONDS,
        job_id=job_id,
    )
    return f"/api/media/{token}"


def _write_private_image(path: Path, image) -> None:
    if not cv2.imwrite(str(path), image):
        raise RuntimeError("Could not write a private preview image")
    secure_file(path)


def _public_job(job: dict) -> dict:
    response = {
        "job_id": job["job_id"],
        "status": job["status"],
        "progress": job["progress"],
        "message": job["message"],
        "output_url": None,
        "process_scope": job["process_scope"],
        "audio_policy": job.get("audio_policy", "remove"),
        "audio_status": job.get("audio_status", "pending"),
        "conservative_fallback_frames": job.get(
            "conservative_fallback_frames", 0
        ),
    }
    if job.get("status") == "complete" and job.get("output_ready"):
        try:
            resolve_output(job["video_id"], job["job_id"])
        except FileNotFoundError:
            pass
        else:
            response["output_url"] = _media_url(
                job["video_id"], "output", job_id=job["job_id"]
            )
    return response


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "model": "yolov8n-seg",
        "tracker": "bytetrack",
        "profile": RUNTIME_PROFILE,
        "device": detector.device if detector is not None else "loading",
        "encoder": VIDEO_ENCODER,
    }


@app.post("/api/upload", response_model=UploadResponse)
async def upload_video(file: UploadFile = File(...)) -> UploadResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type. Use: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    video_id = uuid.uuid4().hex
    expires_at = int(time.time()) + MEDIA_TTL_SECONDS
    session_directory = upload_session_dir(video_id)
    destination = session_directory / f"source{suffix}"
    capture = None
    try:
        create_upload_session(video_id, expires_at)
        size = 0
        with open_private_binary(destination) as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Video must be under 500 MB")
                output.write(chunk)
        capture = cv2.VideoCapture(str(destination))
        if not capture.isOpened():
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
        with detector_lock:
            detector.reset_tracking()
        for _ in range(preview_index + 1):
            ok, frame = capture.read()
            if not ok:
                break
            with detector_lock:
                tracks = detector.track(frame)
        if not ok or frame is None:
            raise HTTPException(status_code=422, detail="No readable frames were found")

        people_data = [
            (track.track_id, track.bbox, track.confidence) for track in tracks
        ]
        for track in tracks:
            if track.mask is not None:
                mask_path = session_directory / f"preview_mask_{track.track_id}.png"
                _write_private_image(mask_path, track.mask * 255)
        raw_preview_path = session_directory / "raw_preview.jpg"
        _write_private_image(raw_preview_path, frame)
        preview = draw_preview(frame, people_data)
        preview_path = session_directory / "detected_preview.jpg"
        _write_private_image(preview_path, preview)

        return UploadResponse(
            video_id=video_id,
            session_capability=issue_session_capability(
                video_id, MEDIA_TTL_SECONDS
            ),
            expires_at=expires_at,
            filename=file.filename or destination.name,
            preview_url=_media_url(video_id, "detected-preview"),
            people=[
                {"track_id": track_id, "bbox": list(bbox), "confidence": confidence}
                for track_id, bbox, confidence in people_data
            ],
            width=width,
            height=height,
            fps=fps,
            frame_count=frame_count,
        )
    except HTTPException:
        delete_video_media(video_id)
        raise
    except Exception as exc:
        logger.exception("Upload analysis failed")
        delete_video_media(video_id)
        raise HTTPException(status_code=500, detail="Video analysis failed") from exc
    finally:
        if capture is not None:
            capture.release()
        await file.close()


@app.post("/api/frame-preview", response_model=FramePreviewResponse)
def create_frame_preview(
    request: FramePreviewRequest,
    authorization: str | None = Header(default=None),
) -> FramePreviewResponse:
    _require_session(request.video_id, authorization)
    session_directory = upload_session_dir(request.video_id)
    raw_preview_path = session_directory / "raw_preview.jpg"
    frame = cv2.imread(str(raw_preview_path))
    if frame is None:
        try:
            source = find_video(request.video_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        capture = cv2.VideoCapture(str(source))
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        preview_index = max(0, min(frame_count // 3, int(fps * 2)))
        capture.set(cv2.CAP_PROP_POS_FRAMES, preview_index)
        ok, frame = capture.read()
        capture.release()
        if not ok or frame is None:
            raise HTTPException(status_code=422, detail="Could not read the preview frame")
        _write_private_image(raw_preview_path, frame)

    for person in request.people:
        if person.track_id == request.selected_track_id:
            continue
        mask_path = session_directory / f"preview_mask_{person.track_id}.png"
        mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        if mask is not None:
            mask = (mask > 127).astype("uint8")
        blur_person(frame, tuple(person.bbox), request.blur_strength, mask)

    output_path = session_directory / "frame_preview.jpg"
    try:
        _write_private_image(output_path, frame)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500, detail="Could not create frame preview"
        ) from exc
    return FramePreviewResponse(preview_url=_media_url(request.video_id, "frame-preview"))


@app.post("/api/process", response_model=JobResponse)
def start_processing(
    request: ProcessRequest,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
) -> dict:
    _require_session(request.video_id, authorization)
    assert detector is not None
    try:
        find_video(request.video_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    job_id = create_job(
        request.video_id,
        request.process_scope,
        request.audio_policy,
    )

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
                request.audio_policy,
            )
        # DELETE is immediate from the caller's perspective. If it races an
        # already-open decoder, remove anything the worker recreated afterward.
        if not session_exists(request.video_id):
            delete_video_media(request.video_id)

    background_tasks.add_task(locked_process)
    with jobs_lock:
        job = jobs[job_id].copy()
    return _public_job(job)


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    authorization: str | None = Header(default=None),
) -> dict:
    try:
        claims = verify_capability(_bearer_token(authorization), "session")
    except CapabilityError as exc:
        raise HTTPException(
            status_code=401,
            detail="The session capability is invalid or expired",
        ) from exc
    with jobs_lock:
        job = jobs.get(job_id)
        job = job.copy() if job else None
    if not job or job.get("video_id") != claims["video_id"]:
        raise HTTPException(status_code=404, detail="Processing job was not found")
    if not session_exists(job["video_id"]):
        raise HTTPException(status_code=404, detail="Uploaded video was not found")
    return _public_job(job)


@app.delete("/api/videos/{video_id}", status_code=204)
def delete_video(
    video_id: str = ApiPath(pattern=r"^[a-f0-9]{32}$"),
    authorization: str | None = Header(default=None),
) -> Response:
    _require_session(video_id, authorization)
    delete_video_media(video_id)
    with jobs_lock:
        for job_id in [
            key for key, job in jobs.items() if job.get("video_id") == video_id
        ]:
            jobs.pop(job_id, None)
    return Response(status_code=204)


@app.get("/api/media/{capability}")
def get_private_media(capability: str) -> FileResponse:
    try:
        claims = verify_capability(capability, "media")
    except CapabilityError as exc:
        raise HTTPException(
            status_code=401, detail="The media capability is invalid or expired"
        ) from exc

    video_id = claims["video_id"]
    if not session_exists(video_id):
        raise HTTPException(status_code=404, detail="Media was not found")
    artifact = claims["artifact"]
    try:
        if artifact == "detected-preview":
            media_path = resolve_preview(video_id, "detected_preview.jpg")
            media_type = "image/jpeg"
        elif artifact == "frame-preview":
            media_path = resolve_preview(video_id, "frame_preview.jpg")
            media_type = "image/jpeg"
        else:
            media_path = resolve_output(video_id, claims["job_id"])
            media_type = "video/mp4"
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Media was not found") from exc

    return FileResponse(
        media_path,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )
