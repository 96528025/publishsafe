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

function App() {
  const inputRef = useRef(null);
  const [upload, setUpload] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [avatar, setAvatar] = useState("sunny");
  const [mode, setMode] = useState("blur");
  const [blurStrength, setBlurStrength] = useState(40);
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
        const response = await fetch(`${API}/api/jobs/${job.job_id}`);
        const nextJob = await response.json();
        setJob(nextJob);
        if (nextJob.status === "failed") setError(nextJob.message);
      } catch {
        setError("Lost connection while checking processing progress.");
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [job?.job_id, job?.status]);

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
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
          body: JSON.stringify({
            video_id: upload.video_id,
            selected_track_id: selectedId,
            blur_strength: blurStrength,
            people: upload.people,
          }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Could not create frame preview");
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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          video_id: upload.video_id,
          selected_track_id: selectedId,
          avatar_style: avatar,
          mode,
          blur_strength: blurStrength,
          process_scope: processScope,
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

  function reset() {
    setUpload(null);
    setSelectedId(null);
    setJob(null);
    setError("");
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#" onClick={reset}>
          <span className="brand-mark"><ShieldCheck size={23} /></span>
          <span>PublishSafe</span>
        </a>
        <div className="privacy-pill"><LockKeyhole size={14} /> Local-first privacy</div>
      </header>

      <main>
        <section className="hero">
          <div className="eyebrow"><Sparkles size={15} /> Made for creators, built for consent</div>
          <h1>Share the moment.<br /><em>Protect the crowd.</em></h1>
          <p>Keep yourself visible while automatically blurring everyone else with privacy-aware person masks.</p>
        </section>

        <nav className="steps" aria-label="Workflow progress">
          {[
            [1, "Upload"],
            [2, "Choose yourself"],
            [3, "Publish safely"],
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
              <h2>{busy ? "Finding people in your video..." : "Drop your dance video here"}</h2>
              <p>MP4, MOV, AVI, MKV, or WebM up to 500 MB</p>
              <button className="primary small" disabled={busy}>
                {busy ? "Analyzing preview" : "Choose a video"}
              </button>
            </div>
            <div className="trust-row">
              <span><LockKeyhole size={16} /> Stored locally</span>
              <span><Eye size={16} /> No facial recognition</span>
              <span><Users size={16} /> People detection only</span>
            </div>
          </section>
        )}

        {upload && !(job?.status === "complete" && job.process_scope === "full") && (
          <section className="workspace">
            <div className="preview-panel">
              <div className="panel-heading">
                <div>
                  <span className="section-label">Preview</span>
                  <h2>Which person is you?</h2>
                </div>
                <button className="text-button" onClick={reset}>Change video</button>
              </div>
              <div className="preview-frame">
                <img
                  src={framePreviewUrl || `${API}${upload.preview_url}`}
                  alt={framePreviewUrl ? "Blur effect frame preview" : "Detected people preview"}
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
                    ? <><LoaderCircle className="spin" size={16} /> Updating blur preview...</>
                    : <><ShieldCheck size={16} /> Selected creator preserved. Other people protected.</>}
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
                      {selectedId === person.track_id && <span className="you-tag">This is me <Check size={13} /></span>}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <aside className="settings-panel">
              <span className="section-label">Protection style</span>
              <h2>Cover everyone else</h2>
              <div className="mode-switch">
                <button className={mode === "blur" ? "active" : ""} onClick={() => setMode("blur")}>
                  <Eye size={17} /> Blur
                </button>
                <button className={mode === "avatar" ? "active" : ""} onClick={() => setMode("avatar")}>
                  <Image size={17} /> Avatars
                </button>
              </div>

              {mode === "avatar" && (
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
              )}

              {mode === "blur" && (
                <div className="blur-control">
                  <div className="blur-control-heading">
                    <span><strong>Blur strength</strong><small>Choose how much identity detail to remove</small></span>
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
                    <span>Gentle</span>
                    <span>Balanced</span>
                    <span>Maximum</span>
                  </div>
                  <p className="slider-hint">The frame preview updates automatically when you move the slider.</p>
                </div>
              )}

              <div className="privacy-summary">
                <ShieldCheck size={22} />
                <div>
                  <strong>Privacy mode is on</strong>
                  <span>{selectedPerson ? `Person ${selectedId} stays visible.` : "Choose yourself in the preview."} Everyone else is protected.</span>
                </div>
              </div>

              {job && (
                <div className="progress-block">
                  <div><span>{job.message}</span><strong>{job.progress}%</strong></div>
                  <progress value={job.progress} max="100" />
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
              <p className="fine-print">Test the first 10 seconds before committing to the full video.</p>
            </aside>
          </section>
        )}

        {job?.status === "complete" && (
          <section className="complete-card">
            <div className="complete-icon"><Check size={34} /></div>
            <span className="section-label">
              {job.process_scope === "preview" ? "Effect preview" : "Ready to share"}
            </span>
            <h2>
              {job.process_scope === "preview"
                ? "How does this protection look?"
                : "Your protected video is ready"}
            </h2>
            <p>
              {job.process_scope === "preview"
                ? "Review the first 10 seconds. You can adjust the style or process the full video."
                : "You stay visible. Everyone else follows your selected privacy style."}
            </p>
            <video controls src={`${API}${job.output_url}`} />
            <div className="complete-actions">
              <a className="primary" href={`${API}${job.output_url}`} download>
                <Download size={18} /> Download {job.process_scope === "preview" ? "preview" : "MP4"}
              </a>
              {job.process_scope === "preview" ? (
                <button className="primary" onClick={() => processVideo("full")}>
                  <Sparkles size={18} /> Looks good, process full video
                </button>
              ) : (
                <button className="secondary" onClick={reset}>Protect another video</button>
              )}
            </div>
          </section>
        )}
      </main>
      <footer>PublishSafe <span>•</span> Privacy that moves with you</footer>
    </div>
  );
}

export default App;
