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
8. To inspect a manuscript file, call `manage_latex_projects` with `{"action":"read_file","latex_project_id":"...","path":"bibliography.bib"}`. Use relative paths from the project tree only.
9. To edit a manuscript file, prefer `{"action":"replace_text","latex_project_id":"...","path":"...","old_text":"...","new_text":"...","expected_count":1}`. Use `write_file` only when replacing the complete file content is intentional.
10. To review local changes before committing, call `manage_latex_projects` with `{"action":"diff","latex_project_id":"...","path":"..."}`.
11. For local Git cleanliness, call `manage_latex_projects` with `{"action":"status","latex_project_id":"..."}`.
12. To commit and push user-approved local manuscript changes back to Overleaf, call `manage_latex_projects` with `{"action":"commit_and_push","latex_project_id":"...","message":"..."}`. Do not find the worktree path yourself.
13. Only patch metadata or create/register projects when the user asks you to change state or gives enough project identifiers to do so.

## Pitfalls

- Do not grep the Odysseus repository or data directory for `overleaf`, `token`, or `credential`.
- Do not use `bash`, `git clone`, `git pull`, `git push`, `curl`, or raw filesystem commands for Overleaf Git operations; use `manage_latex_projects` action `pull` or `commit_and_push`.
- Do not use generic `read_file`, `grep`, or shell paths to inspect or edit manuscript files. Use `manage_latex_projects` `tree`, `read_file`, `replace_text`, `write_file`, and `diff`.
- Do not tell the user the token value; it is intentionally write-only.
- Do not push changes back to Overleaf unless the user explicitly confirms it. After confirmation, use `manage_latex_projects` action `commit_and_push`; never use shell Git.
- Do not assume Google Drive, generic browser documents, or arbitrary websites use this Overleaf-specific workflow.

## Verification

- The first smoke test should be: `manage_latex_projects {"action":"credential_status"}`.
- A passing answer reports whether credential id `overleaf` or another id is configured, without exposing a token.
