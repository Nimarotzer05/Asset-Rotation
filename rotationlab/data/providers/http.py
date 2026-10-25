"""Transport for live providers, separate from parsing so every provider is testable offline.

`UrllibClient` uses only the standard library (honours HTTPS_PROXY and the system CA store),
retries transient failures (timeouts, 429, 5xx) with exponential backoff and keeps a minimum
interval between requests. `FixtureClient` serves recorded responses in tests and records every
URL it was asked for.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from rotationlab.core.errors import DataError

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) rotationlab/0.1 (+https://github.com/)"
TRANSIENT = {408, 425, 429, 500, 502, 503, 504}


class HttpClient(Protocol):
    def get(self, url: str, params: Mapping[str, str] | None = None, headers: Mapping[str, str] | None = None) -> bytes: ...
    def post_json(self, url: str, payload: Mapping[str, object]) -> bytes: ...


def build_url(url: str, params: Mapping[str, str] | None) -> str:
    if not params:
        return url
    return f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(params, safe=':,$')}"


class UrllibClient:
    def __init__(self, timeout_s: float = 30.0, retries: int = 3, backoff_s: float = 1.5,
                 min_interval_s: float = 0.0, sleep: Callable[[float], None] = time.sleep) -> None:
        self.timeout = timeout_s
        self.retries = retries
        self.backoff = backoff_s
        self.min_interval = min_interval_s
        self._sleep = sleep
        self._last = 0.0

    def get(self, url: str, params: Mapping[str, str] | None = None, headers: Mapping[str, str] | None = None) -> bytes:
        return self._request(build_url(url, params), None, headers)

    def post_json(self, url: str, payload: Mapping[str, object]) -> bytes:
        body = json.dumps(payload).encode()
        return self._request(url, body, {"Content-Type": "application/json"})

    def _request(self, full: str, data: bytes | None, headers: Mapping[str, str] | None) -> bytes:
        h = {"User-Agent": USER_AGENT, "Accept": "*/*", **(headers or {})}
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            try:
                req = urllib.request.Request(full, data=data, headers=h, method="POST" if data is not None else "GET")
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    out: bytes = r.read()
                    return out
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code not in TRANSIENT:
                    raise DataError(f"HTTP {e.code} for {_redact(full)}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last_err = e
            if attempt < self.retries:
                self._sleep(self.backoff * (2**attempt))
        raise DataError(f"giving up after {self.retries + 1} attempts: {_redact(full)} ({last_err})")


def _redact(url: str) -> str:
    return re.sub(r"(api_key=)[^&]+", r"\1***", url)


class FixtureClient:
    """Routes: regex on the full URL → bytes, a file path, or a callable(url) -> bytes."""

    def __init__(self, routes: Mapping[str, bytes | str | Path | Callable[[str], bytes]]) -> None:
        self.routes = [(re.compile(k), v) for k, v in routes.items()]
        self.requests: list[str] = []

    def get(self, url: str, params: Mapping[str, str] | None = None, headers: Mapping[str, str] | None = None) -> bytes:
        full = build_url(url, params)
        self.requests.append(full)
        for rx, v in self.routes:
            if rx.search(full):
                if callable(v):
                    return v(full)
                if isinstance(v, bytes):
                    return v
                return Path(v).read_bytes()
        raise DataError(f"no fixture for {full}")

    def post_json(self, url: str, payload: Mapping[str, object]) -> bytes:
        """Routes see the URL plus the JSON payload appended after '#', so tests can match on its content."""
        return self.get(f"{url}#{json.dumps(payload, sort_keys=True)}")


class RecordingClient:
    """Wraps a real client and stores every answer (``record-fixtures``): the raw bytes per request plus
    ``index.json`` with the redacted URL, so tests can replay real responses offline (`ReplayClient`)."""

    def __init__(self, inner: HttpClient, directory: str | Path, label: str = "") -> None:
        self.inner = inner
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.label = label

    def _save(self, key: str, raw: bytes) -> bytes:
        import hashlib

        name = f"{self.label + '-' if self.label else ''}{hashlib.sha256(key.encode()).hexdigest()[:12]}.bin"
        (self.dir / name).write_bytes(raw)
        index_path = self.dir / "index.json"
        index = json.loads(index_path.read_text()) if index_path.exists() else {}
        index[key] = {"file": name, "provider": self.label, "bytes": len(raw)}
        index_path.write_text(json.dumps(index, indent=1, sort_keys=True))
        return raw

    def get(self, url: str, params: Mapping[str, str] | None = None, headers: Mapping[str, str] | None = None) -> bytes:
        raw = self.inner.get(url, params, headers)
        return self._save(_replay_key(build_url(url, params)), raw)

    def post_json(self, url: str, payload: Mapping[str, object]) -> bytes:
        raw = self.inner.post_json(url, payload)
        clean = {k: v for k, v in payload.items() if k != "registrationkey"}
        return self._save(_replay_key(f"{url}#{json.dumps(clean, sort_keys=True)}"), raw)


class ReplayClient:
    """Serves recorded answers; unknown requests raise `DataError` (the test then knows the request changed)."""

    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)
        self.index: dict[str, dict[str, object]] = json.loads((self.dir / "index.json").read_text())
        self.requests: list[str] = []

    def get(self, url: str, params: Mapping[str, str] | None = None, headers: Mapping[str, str] | None = None) -> bytes:
        return self._load(_replay_key(build_url(url, params)))

    def post_json(self, url: str, payload: Mapping[str, object]) -> bytes:
        clean = {k: v for k, v in payload.items() if k != "registrationkey"}
        return self._load(_replay_key(f"{url}#{json.dumps(clean, sort_keys=True)}"))

    def _load(self, key: str) -> bytes:
        self.requests.append(key)
        hit = self.index.get(key)
        if hit is None:
            raise DataError(f"not recorded: {key}")
        return (self.dir / str(hit["file"])).read_bytes()


def _replay_key(url: str) -> str:
    """Redacted URL without volatile parts (keys, Yahoo's period2 = 'now')."""
    url = _redact(url)
    return re.sub(r"([?&])period2=\d+", r"\1period2=*", url)
