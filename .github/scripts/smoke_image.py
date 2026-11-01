#!/usr/bin/env python3
"""Check authentication, embedded frontend and workspace limits on a disposable server."""

import json
import time
import urllib.error
import urllib.request


BASE = "http://127.0.0.1:8000"


def request(path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def main():
    for attempt in range(120):
        try:
            if request("/api/version")[0] == 200:
                break
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(5)
    else:
        raise RuntimeError("Image did not start within ten minutes")

    status, html = request("/")
    assert status == 200 and "<html" in html.lower(), "Embedded frontend is unavailable"
    status, body = request("/api/workspaces/create", {"id": "unauth", "name": "unauth"})
    assert status in (401, 403), f"Unauthenticated workspace creation was not refused: {status} {body}"
    status, token = request("/api/auth/login", {"email": "admin@windmill.dev", "password": "changeme"})
    assert status == 200 and token, f"Password login failed: {status}"
    for index in range(4):
        name = f"fork-smoke-{index}"
        status, body = request("/api/workspaces/create", {"id": name, "name": name}, token)
        assert status == 200, f"Creating workspace {index + 1} failed: {status} {body}"
    for index in range(2):
        status, body = request(f"/api/w/fork-smoke-{index}/workspaces/archive", {}, token)
        assert status == 200, f"Archiving workspace failed: {status} {body}"
    status, body = request("/api/workspaces/unarchive/fork-smoke-0", {}, token)
    assert status == 200, f"Restoring workspace above the old cap failed: {status} {body}"
    status, body = request("/api/workspaces/list", token=token)
    assert status == 200, f"Listing workspaces failed: {status}"
    ids = {workspace["id"] for workspace in json.loads(body)}
    assert {"fork-smoke-0", "fork-smoke-2", "fork-smoke-3"} <= ids
    print("Image smoke checks passed: authentication, frontend, create/archive/restore")


if __name__ == "__main__":
    main()
