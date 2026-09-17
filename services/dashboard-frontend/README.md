# LogSentinel Dashboard Frontend

React + Vite frontend for the LogSentinel operations dashboard.

## Local development

```bash
npm ci
npm run dev
```

## Build

```bash
npm run build
```

## Deploy on Vercel

The repository root includes `vercel.json`, so importing the GitHub repo into
Vercel can deploy this frontend directly.

Use these settings if Vercel asks for them:

- Framework Preset: `Vite`
- Install Command: `cd services/dashboard-frontend && npm ci`
- Build Command: `cd services/dashboard-frontend && npm run build`
- Output Directory: `services/dashboard-frontend/dist`

The root `.vercelignore` uploads only this frontend and the Vercel config.
