"""Trusted media URL conversions for post detail pages."""

import re
from urllib.parse import parse_qs, urlsplit


SAFE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,128}$")
SAFE_BILIBILI_ID = re.compile(r"^BV[0-9A-Za-z]+$")


def _safe_video_id(value):
    return value if SAFE_VIDEO_ID.fullmatch(value or "") else None


def video_embed_url(value: str) -> str | None:
    """Return a provider-owned iframe URL for a known video URL, if safe."""
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname.lower() if parsed.hostname else ""
        query = parse_qs(parsed.query, max_num_fields=20)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"}:
        return None

    path_parts = [part for part in parsed.path.split("/") if part]
    video_id = None
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            video_id = _safe_video_id((query.get("v") or [None])[0])
        elif len(path_parts) == 2 and path_parts[0] in {"embed", "shorts"}:
            video_id = _safe_video_id(path_parts[1])
        if video_id:
            return f"https://www.youtube-nocookie.com/embed/{video_id}"

    if host == "youtu.be" and len(path_parts) == 1:
        video_id = _safe_video_id(path_parts[0])
        if video_id:
            return f"https://www.youtube-nocookie.com/embed/{video_id}"

    if host in {"bilibili.com", "www.bilibili.com", "m.bilibili.com"} and len(path_parts) == 2 and path_parts[0] == "video":
        bvid = path_parts[1]
        if SAFE_BILIBILI_ID.fullmatch(bvid):
            return f"https://player.bilibili.com/player.html?bvid={bvid}"

    if host in {"v.qq.com", "www.v.qq.com"}:
        video_id = _safe_video_id((query.get("vid") or [None])[0])
        if not video_id:
            match = re.fullmatch(r"/x/(?:page|cover/[A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)\.html", parsed.path)
            if match:
                video_id = _safe_video_id(match[1])
        if video_id:
            return f"https://v.qq.com/txp/iframe/player.html?vid={video_id}"

    return None
