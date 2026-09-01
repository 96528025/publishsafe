# Contributing to PublishSafe

Thanks for helping improve this local video-redaction and review prototype.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

cd frontend
npm install
cd ..
```

Run the backend:

```bash
source .venv/bin/activate
uvicorn backend.app.main:app --reload --port 8000
```

Run the frontend in another terminal:

```bash
cd frontend
npm run dev
```

## Before opening a pull request

- Keep changes focused.
- Do not commit or attach private, identifying, confidential, or unlicensed
  video, audio, frames, masks, outputs, filenames/paths, or unredacted logs.
- Use the public sample generator or synthetic test clips.
- Run `python -m compileall backend/app`.
- Install `backend/requirements-test.txt` and run `pytest`.
- Run `npm run build` from `frontend/`.
- Describe tracking, privacy, or performance tradeoffs in the PR.

## Useful contribution areas

- Person ReID and tracking recovery
- Segmentation mask stability
- MPS/GPU acceleration
- Detection-result caching
- VideoToolbox encoding
- Tests and reproducible public samples
- Accessibility and internationalization

## Privacy

Issues and pull requests must not include private media or media of people
without permission. Use generated geometry, public-domain material, or media
whose license and participant consent permit the exact use. Report
vulnerabilities privately according to [SECURITY.md](SECURITY.md).
