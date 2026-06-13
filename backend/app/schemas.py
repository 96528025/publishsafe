from typing import Literal

from pydantic import BaseModel, Field


class PersonPreview(BaseModel):
    track_id: int
    bbox: list[int]
    confidence: float


class UploadResponse(BaseModel):
    video_id: str
    filename: str
    preview_url: str
    people: list[PersonPreview]
    width: int
    height: int
    fps: float
    frame_count: int


class ProcessRequest(BaseModel):
    video_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    selected_track_id: int = Field(ge=1)
    mode: Literal["avatar", "blur"] = "avatar"
    avatar_style: Literal["sunny", "cosmo", "bloom"] = "sunny"


class JobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "processing", "complete", "failed"]
    progress: int
    message: str
    output_url: str | None = None
