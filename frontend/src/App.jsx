import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  Download,
  Eye,
  Image,
  LoaderCircle,
  LockKeyhole,
  ShieldCheck,
  Sparkles,
  Timer,
  Upload,
  Users,
} from "lucide-react";

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const avatarOptions = [
  { id: "sunny", name: "Sunny", note: "Warm & playful" },
  { id: "cosmo", name: "Cosmo", note: "Dreamy & bold" },
  { id: "bloom", name: "Bloom", note: "Fresh & friendly" },
];

async function fetchJobStatus(jobId, sessionCapability) {
  const response = await fetch(`${API}/api/jobs/${jobId}`, {
    headers: { Authorization: `Bearer ${sessionCapability}` },
  });
  const nextJob = await response.json();
  if (!response.ok) throw new Error(nextJob.detail || "Could not refresh processing status");
  return nextJob;
}

function App() {
  const inputRef = useRef(null);
  const videoRef = useRef(null);
  const mediaRetryRef = useRef(0);
  const previewRetryRef = useRef(0);
  const resumePlaybackRef = useRef(null);
  const resettingRef = useRef(false);
  const [upload, setUpload] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [avatar, setAvatar] = useState("sunny");
  const [mode, setMode] = useState("blur");
  const [blurStrength, setBlurStrength] = useState(40);
  const [audioPolicy, setAudioPolicy] = useState("remove");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [framePreviewUrl, setFramePreviewUrl] = useState("");
  const [framePreviewBusy, setFramePreviewBusy] = useState(false);

  const stage = job?.status === "complete" && job.process_scope === "full" ? 3 : upload ? 2 : 1;
  const processing = job && !["complete", "failed"].includes(job.status);
  const people = upload?.people || [];
  const selectedPerson = useMemo(
    () => people.find((person) => person.track_id === selectedId),
    [people, selectedId],
  );

  useEffect(() => {
    if (!job?.job_id || ["complete", "failed"].includes(job.status)) return;
    const timer = setInterval(async () => {
      try {
        const nextJob = await fetchJobStatus(job.job_id, upload.session_capability);
        setJob(nextJob);
        if (nextJob.status === "failed") setError(nextJob.message);
      } catch {
        setError("Lost connection while checking processing progress.");
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [job?.job_id, job?.status, upload?.session_capability]);

  useEffect(() => {
    if (!upload || !selectedId || mode !== "blur") {
      setFramePreviewUrl("");
      return;
    }

    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setFramePreviewBusy(true);
      try {
        const response = await fetch(`${API}/api/frame-preview`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${upload.session_capability}`,
          },
          signal: controller.signal,
          body: JSON.stringify({
            video_id: upload.video_id,
            selected_track_id: selectedId,
            blur_strength: blurStrength,
          }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Could not create frame preview");
        previewRetryRef.current = 0;
        setFramePreviewUrl(`${API}${data.preview_url}`);
      } catch (previewError) {
        if (previewError.name !== "AbortError") setError(previewError.message);
      } finally {
        if (!controller.signal.aborted) setFramePreviewBusy(false);
      }
    }, 200);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [upload, selectedId, mode, blurStrength]);

  async function uploadFile(file) {
    if (!file) return;
    setError("");
    setUpload(null);
    setSelectedId(null);
    setJob(null);
    setFramePreviewUrl("");
    setBusy(true);
    const form = new FormData();
    form.append("file", file);
    try {
      const response = await fetch(`${API}/api/upload`, { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Upload failed");
      setUpload(data);
      if (data.people.length === 1) setSelectedId(data.people[0].track_id);
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      setBusy(false);
    }
  }

  async function processVideo(processScope = "full") {
    if (!selectedId) {
      setError("Select the person who should remain visible.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      const response = await fetch(`${API}/api/process`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${upload.session_capability}`,
        },
        body: JSON.stringify({
          video_id: upload.video_id,
          selected_track_id: selectedId,
          avatar_style: avatar,
          mode,
          blur_strength: blurStrength,
          process_scope: processScope,
          audio_policy: audioPolicy,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not start processing");
      setJob(data);
    } catch (processError) {
      setError(processError.message);
    } finally {
      setBusy(false);
    }
  }

  async function downloadOutput(event) {
    event.preventDefault();
    try {
      const refreshedJob = await fetchJobStatus(job.job_id, upload.session_capability);
      setJob(refreshedJob);
      if (!refreshedJob.output_url) throw new Error("The processed video is no longer available.");
      const link = document.createElement("a");
      link.href = `${API}${refreshedJob.output_url}?download=1`;
      link.download = "publishsafe-output.mp4";
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (downloadError) {
      setError(downloadError.message);
    }
  }

  async function refreshOutputAfterError() {
    if (mediaRetryRef.current >= 1) {
      setError("The video link could not be refreshed. Try Download to request a new link.");
      return;
    }
    mediaRetryRef.current += 1;
    const player = videoRef.current;
    resumePlaybackRef.current = {
      currentTime: player?.currentTime || 0,
      shouldPlay: Boolean(player && !player.paused),
    };
    try {
      const refreshedJob = await fetchJobStatus(job.job_id, upload.session_capability);
      if (!refreshedJob.output_url) throw new Error("The processed video is no longer available.");
      setJob(refreshedJob);
    } catch (refreshError) {
      setError(refreshError.message);
    }
  }

  function resumeRefreshedOutput() {
    const resume = resumePlaybackRef.current;
    const player = videoRef.current;
    if (!resume || !player) return;
    player.currentTime = resume.currentTime;
    if (resume.shouldPlay) player.play().catch(() => {});
    resumePlaybackRef.current = null;
    mediaRetryRef.current = 0;
  }

  async function refreshPreviewAfterError() {
    if (!upload || previewRetryRef.current >= 1) {
      setError("The short-lived preview could not be refreshed. Upload the video again.");
      return;
    }
    previewRetryRef.current += 1;
    const variant = framePreviewUrl ? "frame" : "detected";
    try {
      const response = await fetch(
        `${API}/api/videos/${upload.video_id}/preview-capability?variant=${variant}`,
        { headers: { Authorization: `Bearer ${upload.session_capability}` } },
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not refresh the preview");
      if (variant === "frame") {
        setFramePreviewUrl(`${API}${data.preview_url}`);
      } else {
        setUpload((current) => ({ ...current, preview_url: data.preview_url }));
      }
    } catch (refreshError) {
      setError(refreshError.message);
    }
  }

  function clearLocalSession() {
    setUpload(null);
    setSelectedId(null);
    setJob(null);
    setError("");
    setFramePreviewUrl("");
    setAudioPolicy("remove");
    mediaRetryRef.current = 0;
    previewRetryRef.current = 0;
    if (inputRef.current) inputRef.current.value = "";
  }

  async function reset(event) {
    event?.preventDefault?.();
    if (!upload?.session_capability) {
      clearLocalSession();
      return;
    }
    if (resettingRef.current) return;
    resettingRef.current = true;
    setError("");
    try {
      const response = await fetch(`${API}/api/videos/${upload.video_id}`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${upload.session_capability}` },
      });
      if (!response.ok && response.status !== 404) {
        let detail = "";
        try {
          detail = (await response.json()).detail;
        } catch {
          detail = "";
        }
        throw new Error(detail || "The server did not confirm deletion");
      }
      clearLocalSession();
    } catch (deleteError) {
      setError(`${deleteError.message}. Deletion was not confirmed; private media remains subject to the 24-hour TTL.`);
    } finally {
      resettingRef.current = false;
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#" onClick={reset}>
          <span className="brand-mark"><ShieldCheck size={23} /></span>
          <span>PublishSafe</span>
        </a>
        <div className="privacy-pill"><LockKeyhole size={14} /> Runs on this host</div>
      </header>

      <main>
        <section className="hero">
          <div className="eyebrow"><Sparkles size={15} /> Local video-redaction prototype</div>
          <h1>Keep the creator.<br /><em>Review every redaction.</em></h1>
          <p>Select one person to leave visible and obscure other detected people. Detection can miss—review the entire export before sharing.</p>
        </section>

        <nav className="steps" aria-label="Workflow progress">
          {[
            [1, "Upload"],
            [2, "Choose a creator"],
            [3, "Review output"],
          ].map(([number, label], index) => (
            <div className="step-wrap" key={number}>
              <div className={`step ${stage >= number ? "active" : ""}`}>
                <span>{stage > number ? <Check size={16} /> : number}</span>{label}
              </div>
              {index < 2 && <div className={`step-line ${stage > number ? "active" : ""}`} />}
            </div>
          ))}
        </nav>

        {error && <div className="error" role="alert">{error}</div>}

        {!upload && (
          <section className="upload-card">
            <div
              className={`dropzone ${dragging ? "dragging" : ""}`}
              onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                uploadFile(event.dataTransfer.files[0]);
              }}
              onClick={() => !busy && inputRef.current?.click()}
            >
              <input
                ref={inputRef}
                type="file"
                accept="video/mp4,video/quicktime,video/x-msvideo,video/webm,.mkv"
                hidden
                onChange={(event) => uploadFile(event.target.files[0])}
              />
              <div className="upload-icon">
                {busy ? <LoaderCircle className="spin" size={30} /> : <Upload size={30} />}
              </div>
              <h2>{busy ? "Finding person candidates..." : "Drop a creator video here"}</h2>
              <p>MP4, MOV, AVI, MKV, or WebM up to 500 MB</p>
              <button className="primary small" disabled={busy}>
                {busy ? "Analyzing preview" : "Choose a video"}
              </button>
            </div>
            <div className="trust-row">
              <span><LockKeyhole size={16} /> Source file has no direct route; previews are short-lived</span>
              <span><Eye size={16} /> Audio removed by default</span>
              <span><Users size={16} /> Detection + tracking, not identity proof</span>
            </div>
          </section>
        )}

        {upload && !(job?.status === "complete" && job.process_scope === "full") && (
          <section className="workspace">
            <div className="preview-panel">
              <div className="panel-heading">
                <div>
                  <span className="section-label">Preview</span>
                  <h2>Who may remain visible?</h2>
                </div>
                <button className="text-button" onClick={reset}>Change video</button>
              </div>
              <div className="preview-frame">
                <img
                  src={framePreviewUrl || `${API}${upload.preview_url}`}
                  alt={framePreviewUrl ? "Blur effect frame preview" : "Detected people preview"}
                  onError={refreshPreviewAfterError}
                  onLoad={() => { previewRetryRef.current = 0; }}
                />
                {people.map((person) => {
                  const [x1, y1, x2, y2] = person.bbox;
                  return (
                    <button
                      key={person.track_id}
                      className={`person-hitbox ${selectedId === person.track_id ? "selected" : ""}`}
                      style={{
                        left: `${(x1 / upload.width) * 100}%`,
                        top: `${(y1 / upload.height) * 100}%`,
                        width: `${((x2 - x1) / upload.width) * 100}%`,
                        height: `${((y2 - y1) / upload.height) * 100}%`,
                      }}
                      onClick={() => setSelectedId(person.track_id)}
                      aria-label={`Select person ${person.track_id}`}
                    />
                  );
                })}
                <div className="preview-caption">
                  {framePreviewBusy
                    ? <><LoaderCircle className="spin" size={16} /> Updating one-frame preview...</>
                    : mode === "avatar"
                      ? <><ShieldCheck size={16} /> Detection preview only; avatar placement appears in the render.</>
                      : <><ShieldCheck size={16} /> One-frame sample only; full-video tracking can differ.</>}
                </div>
              </div>
              {people.length === 0 ? (
                <p className="empty-note">No people were found in this preview. Try a video with a clearer full-body view.</p>
              ) : (
                <div className="people-list">
                  {people.map((person) => (
                    <button
                      key={person.track_id}
                      className={selectedId === person.track_id ? "selected" : ""}
                      onClick={() => setSelectedId(person.track_id)}
                    >
                      <span className="person-number">{person.track_id}</span>
                      <span>Person {person.track_id}</span>
                      {selectedId === person.track_id && <span className="you-tag">Selected <Check size={13} /></span>}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <aside className="settings-panel">
              <span className="section-label">Redaction style</span>
              <h2>Obscure other detections</h2>
              <div className="mode-switch">
                <button className={mode === "blur" ? "active" : ""} onClick={() => setMode("blur")}>
                  <Eye size={17} /> Blur
                </button>
                <button className={mode === "avatar" ? "active" : ""} onClick={() => setMode("avatar")}>
                  <Image size={17} /> Avatars
                </button>
              </div>

              {mode === "avatar" && (
                <>
                  <div className="avatar-grid">
                    {avatarOptions.map((option) => (
                      <button
                        key={option.id}
                        className={avatar === option.id ? "selected" : ""}
                        onClick={() => setAvatar(option.id)}
                      >
                        <img src={`${API}/avatars/${option.id}.png`} alt="" />
                        <span><strong>{option.name}</strong><small>{option.note}</small></span>
                        {avatar === option.id && <Check className="avatar-check" size={14} />}
                      </button>
                    ))}
                  </div>
                  <p className="mode-warning">Avatar mode is an experimental visual effect, not a stronger anonymity mode.</p>
                </>
              )}

              {mode === "blur" && (
                <div className="blur-control">
                  <div className="blur-control-heading">
                    <span><strong>Blur strength</strong><small>Adjust visual obstruction; blur cannot guarantee anonymity</small></span>
                    <output>{blurStrength}%</output>
                  </div>
                  <input
                    type="range"
                    min="10"
                    max="100"
                    step="5"
                    value={blurStrength}
                    onChange={(event) => setBlurStrength(Number(event.target.value))}
                    aria-label="Blur strength"
                  />
                  <div className="range-labels">
                    <span>Light</span>
                    <span>Stronger</span>
                    <span>Strongest</span>
                  </div>
                  <p className="slider-hint">The frame preview updates automatically when you move the slider.</p>
                </div>
              )}

              <fieldset className="audio-control">
                <legend>Audio in export</legend>
                <label className={audioPolicy === "remove" ? "selected" : ""}>
                  <input
                    type="radio"
                    name="audio-policy"
                    value="remove"
                    checked={audioPolicy === "remove"}
                    onChange={() => setAudioPolicy("remove")}
                  />
                  <span><strong>Remove audio (recommended)</strong><small>Avoid carrying voices, names, and conversations into the export.</small></span>
                </label>
                <label className={audioPolicy === "preserve" ? "selected warning" : "warning"}>
                  <input
                    type="radio"
                    name="audio-policy"
                    value="preserve"
                    checked={audioPolicy === "preserve"}
                    onChange={() => setAudioPolicy("preserve")}
                  />
                  <span><strong>Preserve source audio</strong><small>Explicit opt-in: sound may identify people or places.</small></span>
                </label>
              </fieldset>

              <div className="privacy-summary">
                <ShieldCheck size={22} />
                <div>
                  <strong>Conservative fallback is enabled</strong>
                  <span>{selectedPerson ? `Person ${selectedId} is the requested exemption.` : "Choose the creator in the preview."} Ambiguous tracking blurs every detected person, but detector misses remain possible.</span>
                </div>
              </div>

              {job && (
                <div className="progress-block">
                  <div><span>{job.message}</span><strong>{job.progress}%</strong></div>
                  <progress value={job.progress} max="100" />
                  {job.conservative_fallback_frames > 0 && (
                    <p className="fallback-note">Blur-all fallback used on {job.conservative_fallback_frames} processed frame{job.conservative_fallback_frames === 1 ? "" : "s"}. Review those transitions carefully.</p>
                  )}
                </div>
              )}

              <div className="process-actions">
                <button
                  className="secondary process"
                  disabled={!selectedId || busy || processing}
                  onClick={() => processVideo("preview")}
                >
                  {processing && job.process_scope === "preview"
                    ? <><LoaderCircle className="spin" size={18} /> Creating preview</>
                    : <><Timer size={18} /> Preview first 10 seconds</>}
                </button>
                <button
                  className="primary process"
                  disabled={!selectedId || busy || processing}
                  onClick={() => processVideo("full")}
                >
                  {processing && job.process_scope === "full"
                    ? <><LoaderCircle className="spin" size={19} /> Processing full video</>
                    : <><Sparkles size={19} /> Process full video</>}
                </button>
              </div>
              <p className="fine-print">The short preview is a tuning aid, not approval to publish.</p>
            </aside>
          </section>
        )}

        {job?.status === "complete" && (
          <section className="complete-card">
            <div className="complete-icon"><Check size={34} /></div>
            <span className="section-label">
              {job.process_scope === "preview" ? "Motion preview" : "Review required"}
            </span>
            <h2>
              {job.process_scope === "preview"
                ? "Inspect this short render"
                : "Your processed video is ready to inspect"}
            </h2>
            <p>
              {job.process_scope === "preview"
                ? "Use it to tune the effect, then review the complete render separately."
                : `Watch the entire file before sharing. Audio was ${job.audio_status === "preserved" ? "preserved by explicit choice" : "removed"}; people, masks, text, reflections, and context still need review.`}
            </p>
            {job.conservative_fallback_frames > 0 && (
              <p className="fallback-note">Blur-all fallback was used on {job.conservative_fallback_frames} processed frame{job.conservative_fallback_frames === 1 ? "" : "s"}. Inspect those transitions and the surrounding frames.</p>
            )}
            <video
              ref={videoRef}
              controls
              src={`${API}${job.output_url}`}
              onError={refreshOutputAfterError}
              onCanPlay={resumeRefreshedOutput}
            />
            <div className="complete-actions">
              <a
                className="primary"
                href={`${API}${job.output_url}?download=1`}
                download="publishsafe-output.mp4"
                onClick={downloadOutput}
              >
                <Download size={18} /> Download {job.process_scope === "preview" ? "preview" : "review copy"}
              </a>
              {job.process_scope === "preview" ? (
                <button className="primary" onClick={() => processVideo("full")}>
                  <Sparkles size={18} /> Continue to full render
                </button>
              ) : (
                <button className="secondary" onClick={reset}>Process another video</button>
              )}
            </div>
          </section>
        )}
      </main>
      <footer>PublishSafe <span>•</span> Local-first redaction prototype <span>•</span> Human review required</footer>
    </div>
  );
}

export default App;
