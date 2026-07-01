---
name: overleaf-git-latex-projects
description: Use the narrow LaTeX project tool for Overleaf Git credentials and project metadata instead of searching files.
version: 1.0.0
category: browser-overleaf
tags: [overleaf, latex, git, credentials, manuscript]
status: published
confidence: 0.95
source: user
owner: amber
created: "2026-06-30T00:00:00Z"
---

## When to Use

Use this when the user asks about Overleaf Git credentials, LaTeX project metadata, Overleaf project ids, local manuscript workspaces, project trees, Git status for a LaTeX project, or whether an Overleaf credential is configured.

## Procedure

1. For "is my Overleaf Git credential configured?", call `manage_latex_projects` with `{"action":"credential_status"}`.
2. Do not use `bash`, `grep`, `read_file`, `app_api`, database queries, or repository searches to inspect Overleaf credentials.
3. Never try to reveal or recover a token. The credential status tool only returns credential ids, usernames, and configured/not-configured state.
4. For registered projects, call `manage_latex_projects` with `{"action":"list"}` before assuming a project id.
5. For project metadata, call `manage_latex_projects` with `{"action":"metadata_read","latex_project_id":"..."}`.
6. To fetch files from Overleaf, call `manage_latex_projects` with `{"action":"pull","latex_project_id":"..."}`. This is the only approved clone/pull path because it injects the stored credential safely.
7. For a project file overview, call `manage_latex_projects` with `{"action":"tree","latex_project_id":"..."}`.
8. For local Git cleanliness, call `manage_latex_projects` with `{"action":"status","latex_project_id":"..."}`.
9. Only patch metadata or create/register projects when the user asks you to change state or gives enough project identifiers to do so.

## Pitfalls

- Do not grep the Odysseus repository or data directory for `overleaf`, `token`, or `credential`.
- Do not use `bash`, `git clone`, `git pull`, `curl`, or raw filesystem commands for Overleaf Git operations; use `manage_latex_projects` action `pull`.
- Do not tell the user the token value; it is intentionally write-only.
- Do not push changes back to Overleaf unless a separate push tool exists and the user explicitly confirms the diff.
- Do not assume Google Drive, generic browser documents, or arbitrary websites use this Overleaf-specific workflow.

## Verification

- The first smoke test should be: `manage_latex_projects {"action":"credential_status"}`.
- A passing answer reports whether credential id `overleaf` or another id is configured, without exposing a token.
