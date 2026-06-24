"""Push a per-run summary to GitHub so reviewers get a login-free link.

The DigitalOcean scheduled job's runtime logs are behind the dashboard login
and Better Stack live tail requires team membership. Pushing a tiny artefact
to a side branch (`logs`) of this public repo solves the "share a link with a
stranger" problem without adding a third-party service.

Design choices:
- Best-effort. Any failure here logs a warning but does NOT fail the job
  (the artefact is observability, not the work).
- A separate `logs` branch — DO autodeploy watches `main`, so writes here
  don't rebuild the app, and `main`'s history stays clean.
- Two files per run: `runs/latest.log` (overwritten, stable link) and
  `runs/<UTC-iso>.log` (history).
- Uses `httpx` (already in deps) instead of `requests`.
"""

from __future__ import annotations

import logging
import os
from base64 import b64encode
from datetime import datetime, timezone

import httpx

log = logging.getLogger("megatronbot")

GH_API = "https://api.github.com"
DEFAULT_LOG_BRANCH = "logs"
DEFAULT_BASE_BRANCH = "main"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _ensure_branch(client: httpx.Client, repo: str, branch: str, base: str, token: str) -> None:
    """Create `branch` from `base` if it doesn't exist yet."""
    r = client.get(f"{GH_API}/repos/{repo}/git/ref/heads/{branch}", headers=_headers(token))
    if r.status_code == 200:
        return
    if r.status_code != 404:
        r.raise_for_status()
    # Fork from base
    base_ref = client.get(
        f"{GH_API}/repos/{repo}/git/ref/heads/{base}", headers=_headers(token)
    )
    base_ref.raise_for_status()
    base_sha = base_ref.json()["object"]["sha"]
    create = client.post(
        f"{GH_API}/repos/{repo}/git/refs",
        headers=_headers(token),
        json={"ref": f"refs/heads/{branch}", "sha": base_sha},
    )
    create.raise_for_status()


def _put_file(
    client: httpx.Client,
    repo: str,
    branch: str,
    path: str,
    content: str,
    message: str,
    token: str,
) -> str:
    """Create or update a file on `branch`. Returns the blob HTML URL."""
    # Need the existing SHA to update; omit for create.
    sha = None
    head = client.get(
        f"{GH_API}/repos/{repo}/contents/{path}",
        params={"ref": branch},
        headers=_headers(token),
    )
    if head.status_code == 200:
        sha = head.json()["sha"]
    elif head.status_code != 404:
        head.raise_for_status()

    body: dict = {
        "message": message,
        "branch": branch,
        "content": b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        body["sha"] = sha
    r = client.put(
        f"{GH_API}/repos/{repo}/contents/{path}",
        headers=_headers(token),
        json=body,
    )
    r.raise_for_status()
    return r.json()["content"]["html_url"]


def publish_run_log(counts: dict, chunks_embedded: int, *, scraped: int | None = None) -> str | None:
    """Push a summary to GitHub. Returns the public URL, or None if disabled/failed.

    Required env: GITHUB_TOKEN, GITHUB_REPO ("owner/repo").
    Optional env: GITHUB_LOG_BRANCH (default "logs"), GITHUB_BASE_BRANCH (default "main").
    """
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPO")
    if not token or not repo:
        log.info("[runlog] GITHUB_TOKEN/GITHUB_REPO not set — skipping artefact push")
        return None

    branch = os.getenv("GITHUB_LOG_BRANCH", DEFAULT_LOG_BRANCH)
    base = os.getenv("GITHUB_BASE_BRANCH", DEFAULT_BASE_BRANCH)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

    lines = [
        f"# Daily sync run @ {ts}",
        "",
        f"RESULT: {counts} | chunks_embedded={chunks_embedded}",
    ]
    if scraped is not None:
        lines.append(f"scraped: {scraped}")
    body = "\n".join(lines) + "\n"

    try:
        with httpx.Client(timeout=30.0) as client:
            _ensure_branch(client, repo, branch, base, token)
            latest_url = _put_file(
                client, repo, branch, "runs/latest.log",
                body, f"chore(logs): update latest run {ts}", token,
            )
            _put_file(
                client, repo, branch, f"runs/{ts}.log",
                body, f"chore(logs): archive run {ts}", token,
            )
        log.info("[runlog] published -> %s", latest_url)
        return latest_url
    except Exception as e:
        log.warning("[runlog] publish failed (non-fatal): %s", e)
        return None
