# CSV Analysis Assistant — Frontend

React + Vite + TypeScript single-page UI for Project 1.

## Develop

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api → http://localhost:8000
```

Run the backend separately (`make dev` from the repo root) so `/api` resolves.

## Scripts

- `npm run dev` — Vite dev server with the `/api` proxy
- `npm test` — Vitest + React Testing Library (mocked fetch; no backend needed)
- `npm run build` — type-check (`tsc`) then production build
- `npm run type-check` — `tsc --noEmit`

## Configuration

`VITE_API_BASE` (see `.env.example`) sets the API base URL; defaults to `/api`.
In production, point it at the deployed backend and configure that backend's
`CORS_ALLOW_ORIGINS` to include the frontend origin.
