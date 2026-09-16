# Deploying to Render (free tier)

This repo includes a [`render.yaml`](render.yaml) blueprint that deploys
everything in one shot: the FastAPI backend, the Next.js frontend, and a
free Postgres database, wired together with the right environment
variables. Claude Code doesn't hold Render credentials, so this last step —
connecting your own Render account — has to happen on your end. It takes
about 3 minutes.

## Steps

1. Go to <https://dashboard.render.com/select-repo?type=blueprint> and sign
   in (or create a free account — no card required for the free tier).
2. Connect your GitHub account if you haven't already, and select the
   `vmas-yt/time-tracking-app` repository.
3. Render will detect `render.yaml` and show a preview of 3 resources:
   `time-tracking-db` (Postgres), `time-tracking-backend`, and
   `time-tracking-frontend`. Click **Apply**.
4. Wait for both services to finish building (a few minutes — the frontend
   build is the slower of the two). Render will give each service a URL
   like `https://time-tracking-backend.onrender.com` and
   `https://time-tracking-frontend.onrender.com`.
5. Open the **frontend** URL in your browser. Register an account — the
   first one becomes an admin automatically.

## If the service names were already taken

Render assigns URLs from the `name` field in `render.yaml`
(`time-tracking-backend` / `time-tracking-frontend`). If those names
happen to already be taken by someone else on Render, it'll suffix yours
(e.g. `time-tracking-frontend-ab12`). If that happens, the frontend's
`NEXT_PUBLIC_API_URL` and the backend's `CORS_ORIGINS` env vars (set in the
Render dashboard, under each service's **Environment** tab) need to be
updated to match the actual assigned URLs, then **Manual Deploy → Deploy
latest commit** on the frontend service to rebuild with the corrected
value baked in.

## Good to know

- **Free-tier cold starts**: both web services spin down after 15 minutes
  of no traffic and take 30–60 seconds to wake back up on the next
  request — the first load after a quiet period will feel slow, that's
  expected, not broken.
- **Free Postgres expiry**: Render's free databases expire after 90 days.
  Fine for trying this out; swap the plan before relying on it long-term.
- Everything here is defined in [`render.yaml`](render.yaml) — treat it as
  the config source of truth, not this doc.
