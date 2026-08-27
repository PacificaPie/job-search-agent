"""Stable, versioned job identity for local deduplication."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from boss_zhipin.domain.models import JobSnapshot

IDENTITY_VERSION = "v1"
_SPACE_RE = re.compile(r"\s+")
_TRACKING_QUERY_KEYS = {"ka", "lid", "securityid", "sessionid", "timestamp", "_"}


def normalize_text(value: str) -> str:
    """Normalize display text without changing its semantic content."""

    return _SPACE_RE.sub(" ", value).strip().casefold()


def normalize_job_url(value: str) -> str:
    """Remove fragments and known session/tracking parameters from a job URL."""

    raw = value.strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return raw
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() not in _TRACKING_QUERY_KEYS
    ]
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path.rstrip("/"),
            urlencode(sorted(query)),
            "",
        )
    )


def canonical_job_key(snapshot: JobSnapshot, platform: str | None = None) -> str:
    """Return a deterministic key using the strongest available identifier."""

    platform_name = (platform or snapshot.platform).strip().casefold()
    external_id = (snapshot.external_id or "").strip()
    if external_id:
        identity = f"external:{external_id}"
    else:
        source_url = normalize_job_url(snapshot.source_url or "")
        if source_url:
            identity = f"url:{source_url}"
        else:
            fields = (
                normalize_text(snapshot.company),
                normalize_text(snapshot.title),
                normalize_text(snapshot.location),
                normalize_text(snapshot.description),
            )
            identity = "content:" + "\x1f".join(fields)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"{IDENTITY_VERSION}:{platform_name}:{digest}"
