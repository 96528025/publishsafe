# Contributing to PublishSafe

Thanks for helping improve privacy-preserving video publishing.

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
- Do not commit private or identifying videos.
- Use the public sample generator or synthetic test clips.
- Run `python -m compileall backend/app`.
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

Issues and pull requests must not include videos of people without permission.
Use public-domain, appropriately licensed, or synthetic media.
