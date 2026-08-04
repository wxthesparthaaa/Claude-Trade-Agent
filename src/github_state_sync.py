"""
Uses GitHub's Contents API as a free, durable state store for the small
JSON files under STATE_DIR -- Render's free tier has no persistent disk,
so anything written to local disk is wiped on every redeploy. GitHub is
already free, already the deploy source, and this way both the local
machine (where trades actually get placed) and the cloud dashboard share
one source of truth: whichever side writes state, the other picks it up
on its next pull.

Plain HTTPS calls via urllib, same style as telegram_notifier.send_message
-- no new SDK dependency. A no-op everywhere GITHUB_TOKEN/GITHUB_REPO
aren't set, so local dev/tests are completely unaffected.
"""
import base64
import json
import os
import urllib.error
import urllib.request
from typing import Optional

from state_paths import STATE_DIR, STATE_FILES

API_BASE = "https://api.github.com"


def get_github_config() -> Optional[dict]:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")
    if not token or not repo:
        return None
    return {"token": token, "repo": repo, "branch": os.environ.get("GITHUB_BRANCH", "main")}


def _github_request(method: str, url: str, token: str, body: Optional[dict] = None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return 404, None
        raise


def pull_state_from_github() -> int:
    """
    Fetches every known state file from GitHub into the local STATE_DIR.
    Returns the count actually pulled -- a file missing from the repo
    (e.g. before it's ever been written) is skipped, not an error; a
    brand-new deployment starting with nothing is the normal first run.
    """
    config = get_github_config()
    if config is None:
        return 0

    os.makedirs(STATE_DIR, exist_ok=True)
    pulled = 0
    for repo_path, local_path in STATE_FILES.items():
        url = f"{API_BASE}/repos/{config['repo']}/contents/{repo_path}?ref={config['branch']}"
        status, data = _github_request("GET", url, config["token"])
        if status == 404 or data is None:
            continue
        content = base64.b64decode(data["content"]).decode("utf-8")
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(content)
        pulled += 1
    return pulled


def push_state_to_github(local_path: str) -> bool:
    """
    Pushes one local state file back to GitHub, matched to its
    repo-relative path via state_paths.STATE_FILES. No-op (returns False)
    if GITHUB_TOKEN/GITHUB_REPO aren't configured, or if the local file
    doesn't exist yet.
    """
    config = get_github_config()
    if config is None:
        return False

    repo_path = next((rp for rp, lp in STATE_FILES.items() if lp == local_path), None)
    if repo_path is None:
        raise ValueError(f"{local_path} is not a known state file -- see state_paths.STATE_FILES")
    if not os.path.exists(local_path):
        return False

    with open(local_path, "r", encoding="utf-8") as f:
        content = f.read()

    url = f"{API_BASE}/repos/{config['repo']}/contents/{repo_path}"
    get_status, existing = _github_request("GET", f"{url}?ref={config['branch']}", config["token"])
    sha = existing["sha"] if get_status == 200 and existing else None

    body = {
        "message": f"Update {repo_path}",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": config["branch"],
    }
    if sha:
        body["sha"] = sha

    status, _ = _github_request("PUT", url, config["token"], body=body)
    return status in (200, 201)
