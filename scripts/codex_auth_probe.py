#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any
import urllib.parse

import httpx

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_ISSUER = "https://auth.openai.com"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe Codex auth.json tokens with a test /responses call."
    )
    parser.add_argument(
        "--auth-path",
        type=Path,
        help="Path to auth.json (defaults to $CODEX_HOME/auth.json or ~/.codex/auth.json).",
    )
    parser.add_argument(
        "--use",
        choices=["auto", "api_key", "access_token", "id_token"],
        default="auto",
        help="Which credential to try.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("CMTR_MODEL", "gpt-5.2"),
        help="Model to request (default: gpt-5.2).",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        help="OpenAI API base URL.",
    )
    parser.add_argument(
        "--issuer",
        default=DEFAULT_ISSUER,
        help="OAuth issuer (default: https://auth.openai.com).",
    )
    parser.add_argument(
        "--exchange",
        action="store_true",
        help="Attempt refresh + token exchange to obtain an API key.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Request timeout in seconds.",
    )
    args = parser.parse_args()

    auth_path = resolve_auth_path(args.auth_path)
    auth_data = load_auth_json(auth_path)
    api_key = auth_data.get("OPENAI_API_KEY") or auth_data.get("openai_api_key")
    tokens = auth_data.get("tokens") or {}
    access_token = tokens.get("access_token")
    id_token = tokens.get("id_token")
    if isinstance(id_token, dict):
        id_token = id_token.get("raw_jwt") or id_token.get("token") or id_token.get("id_token")

    candidates = pick_candidates(args.use, api_key, access_token, id_token)
    if not candidates:
        print("No usable credentials found in auth.json.", file=sys.stderr)
        return 1

    for label, token in candidates:
        if not token:
            continue
        ok = try_request(args.base_url, args.model, token, args.timeout, label)
        if ok:
            return 0

    if args.exchange:
        api_key = exchange_api_key(
            issuer=args.issuer,
            refresh_token=tokens.get("refresh_token"),
            id_token=id_token,
            timeout=args.timeout,
        )
        if api_key:
            ok = try_request(args.base_url, args.model, api_key, args.timeout, "exchanged_api_key")
            return 0 if ok else 1
    return 1


def resolve_auth_path(override: Path | None) -> Path:
    if override:
        return override.expanduser()
    codex_home = os.getenv("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "auth.json"
    return Path.home() / ".codex" / "auth.json"


def load_auth_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Failed to read auth.json at {path}: {exc}", file=sys.stderr)
        sys.exit(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON in {path}: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, dict):
        print(f"Unexpected auth.json structure at {path}.", file=sys.stderr)
        sys.exit(1)
    return data


def pick_candidates(
    mode: str,
    api_key: str | None,
    access_token: str | None,
    id_token: str | None,
) -> list[tuple[str, str]]:
    if mode == "api_key":
        return [("OPENAI_API_KEY", api_key or "")]
    if mode == "access_token":
        return [("access_token", access_token or "")]
    if mode == "id_token":
        return [("id_token", id_token or "")]
    candidates = []
    if api_key:
        candidates.append(("OPENAI_API_KEY", api_key))
    if access_token:
        candidates.append(("access_token", access_token))
    if id_token:
        candidates.append(("id_token", id_token))
    return candidates


def try_request(
    base_url: str, model: str, token: str, timeout: float, label: str
) -> bool:
    url = f"{base_url.rstrip('/')}/responses"
    payload = {
        "model": model,
        "input": [{"role": "user", "content": "Reply with: hello from cmtr."}],
        "max_output_tokens": 16,
    }
    headers = {"Authorization": f"Bearer {token}"}
    print(f"Trying {label}...")
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        print(f"Request failed for {label}: {exc}", file=sys.stderr)
        return False
    if response.status_code // 100 == 2:
        data = response.json()
        output_text = data.get("output_text") or ""
        output_text = output_text.strip().replace("\n", " ")
        print(f"Success with {label}. Output: {output_text[:120]}")
        return True
    try:
        error_body = response.json()
    except ValueError:
        error_body = response.text
    print(
        f"{label} failed with status {response.status_code}: {error_body}",
        file=sys.stderr,
    )
    return False


def exchange_api_key(
    issuer: str,
    refresh_token: str | None,
    id_token: str | None,
    timeout: float,
) -> str | None:
    tokens = refresh_tokens(issuer, refresh_token, timeout)
    if tokens:
        id_token = tokens.get("id_token") or id_token
    if not id_token:
        print("No id_token available for token exchange.", file=sys.stderr)
        return None
    url = f"{issuer.rstrip('/')}/oauth/token"
    body = (
        "grant_type=urn:ietf:params:oauth:grant-type:token-exchange"
        f"&client_id={urlencode(CLIENT_ID)}"
        f"&requested_token={urlencode('openai-api-key')}"
        f"&subject_token={urlencode(id_token)}"
        f"&subject_token_type={urlencode('urn:ietf:params:oauth:token-type:id_token')}"
    )
    print("Attempting token exchange for API key...")
    try:
        response = httpx.post(
            url,
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        print(f"Token exchange failed: {exc}", file=sys.stderr)
        return None
    if response.status_code // 100 != 2:
        print(
            f"Token exchange failed with status {response.status_code}: {response.text}",
            file=sys.stderr,
        )
        return None
    data = response.json()
    return data.get("access_token")


def refresh_tokens(
    issuer: str, refresh_token: str | None, timeout: float
) -> dict[str, str] | None:
    if not refresh_token:
        return None
    url = f"{issuer.rstrip('/')}/oauth/token"
    body = (
        f"grant_type=refresh_token&client_id={urlencode(CLIENT_ID)}"
        f"&refresh_token={urlencode(refresh_token)}"
        f"&scope={urlencode('openid profile email offline_access')}"
    )
    print("Refreshing tokens...")
    try:
        response = httpx.post(
            url,
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        print(f"Refresh failed: {exc}", file=sys.stderr)
        return None
    if response.status_code // 100 != 2:
        print(
            f"Refresh failed with status {response.status_code}: {response.text}",
            file=sys.stderr,
        )
        return None
    data = response.json()
    tokens: dict[str, str] = {}
    for key in ("id_token", "access_token", "refresh_token"):
        value = data.get(key)
        if isinstance(value, str) and value:
            tokens[key] = value
    return tokens


def urlencode(value: str) -> str:
    return urllib.parse.quote(value, safe="")


if __name__ == "__main__":
    raise SystemExit(main())
