# Resonova

Voice interaction testing platform.

## Structure

```
resonova/
├── backend/     Python FastAPI backend (uvicorn on :8765)
├── frontend/    Vue 3 + Vite frontend (pnpm dev on :5173)
└── docs/        Documentation
```

## Quick Start

### Backend (WSL)
```bash
cd backend
uv run uvicorn server:app --host 0.0.0.0 --port 8765
```

### Frontend (Windows)
```bash
cd frontend
pnpm dev
```

Frontend auto-proxies `/api` and `/ws` to `http://192.168.52.134:8765`.
