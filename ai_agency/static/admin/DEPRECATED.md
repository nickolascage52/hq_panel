# DEPRECATED — Admin Panel

**As of 2026-05-15** this folder is deprecated.

## Use `/hq/` instead

The admin panel here is the legacy interface. It is not maintained and may
have stale routes / outdated styling.

The current HQ panel is at `/hq/index.html` (served from `static/hq/`):
- CRM, projects, students, content, analytics, AI Pipeline, settings — all
  there
- Mobile-friendly
- Auth via session token (T-1-012)

## Removal timeline

- **v1.0 (now):** marked deprecated, files left in place to avoid breaking
  any unknown deep-links.
- **v2.0 (TBD):** folder will be removed entirely after a final audit
  confirms no references in code / nginx / bookmarks.

## If you find yourself here

Probably an old bookmark. Update to:
- `http://<host>/hq/` for the panel
- `http://<host>/hq/login.html` for login
