#!/usr/bin/env python3
"""Download Suno assets and publish them to Qiaomu Music Player Web."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:3068"
DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "Suno" / "QiaomuMusicPublisher"
SUNO_MASTER = Path.home() / ".agents" / "skills" / "qiaomu-suno-master"
QIAOMU_IMAGE_GENERATOR = Path.home() / ".agents" / "skills" / "qiaomu-image-generator"


def log(message: str) -> None:
    print(message, file=sys.stderr)


def run(
    cmd: list[str],
    check: bool = True,
    quiet: bool = False,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    if not quiet:
        log("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=timeout)
    if proc.stdout and not quiet:
        print(proc.stdout, end="")
    if proc.stderr and not quiet:
        print(proc.stderr, file=sys.stderr, end="")
    if check and proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return proc


def resolve_suno_short_url(url: str) -> str:
    request = urllib.request.Request(url, method="HEAD", headers={"user-agent": "qiaomu-music-publisher/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.geturl()
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            location = exc.headers.get("Location")
            if location:
                return urllib.parse.urljoin(url, location)
        raise SystemExit(f"Could not resolve Suno short link ({exc.code}): {url}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not resolve Suno short link: {url} ({exc})") from exc


def normalize_ids(values: list[str]) -> list[str]:
    ids: list[str] = []
    for value in values:
        for part in re.split(r"[\s,]+", value.strip()):
            if not part:
                continue
            if re.match(r"^https?://([^/]+\.)?suno\.com/s/[^/?#]+", part):
                part = resolve_suno_short_url(part)
            match = re.search(
                r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
                part,
            )
            if not match:
                raise SystemExit(f"Could not parse Suno clip ID from: {part}")
            ids.append(match.group(1).lower())
    if not ids:
        raise SystemExit("No Suno clip IDs provided.")
    return ids


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "", value).strip()
    return re.sub(r"\s+", " ", cleaned) or "suno-cover"


def suno_info(clip_id: str) -> dict[str, Any]:
    proc = run(["suno", "info", "--json", clip_id], check=False, quiet=True)
    if proc.returncode != 0:
        return {}
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if isinstance(data, list) and data:
        data = data[0]
    return data if isinstance(data, dict) else {}


def clip_title(info: dict[str, Any], clip_id: str) -> str:
    return str(info.get("title") or info.get("name") or f"Suno {clip_id[:8]}").strip()


def download_url(url: str, path: Path) -> Path:
    request = urllib.request.Request(url, headers={"user-agent": "qiaomu-music-publisher/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        path.write_bytes(response.read())
    return path


def download_suno_cover(info: dict[str, Any], clip_id: str, output_dir: Path) -> Path | None:
    image_url = str(info.get("image_url") or info.get("image_large_url") or "").strip()
    if not image_url:
        return None
    ext = Path(urllib.parse.urlparse(image_url).path).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".jpg"
    title = safe_name(clip_title(info, clip_id))
    path = output_dir / f"{title}-{clip_id[:8]}-suno-cover{ext}"
    if not path.exists():
        log(f"Downloading Suno cover for {clip_id}...")
        download_url(image_url, path)
    return path


def find_asset(output_dir: Path, clip_id: str, suffixes: tuple[str, ...]) -> Path | None:
    prefix = clip_id[:8].lower()
    candidates: list[Path] = []
    for path in output_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in suffixes:
            continue
        if clip_id.lower() in path.name.lower() or prefix in path.name.lower():
            candidates.append(path)
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0] if candidates else None


def validate_lrc(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not re.search(r"^\[\d{2}:\d{2}\.\d{2}\].+", text, re.M):
        raise SystemExit(f"LRC does not contain timestamped lyric lines: {path}")


def lyric_excerpt(lrc: Path, max_lines: int = 12) -> str:
    text = lrc.read_text(encoding="utf-8", errors="replace")
    lines: list[str] = []
    for line in text.splitlines():
        cleaned = re.sub(r"^\[[^\]]+\]\s*", "", line).strip()
        if not cleaned or cleaned.startswith("["):
            continue
        lines.append(cleaned)
        if len(lines) >= max_lines:
            break
    return " / ".join(lines)


def cover_description(title: str, lrc: Path) -> str:
    excerpt = lyric_excerpt(lrc)
    theme = f"歌曲《{title}》"
    if excerpt:
        theme += f"，歌词意向：{excerpt}"
    return (
        f"{theme}。提炼成一个强记忆点的专辑封面：中心单一视觉符号，"
        "用抽象物件、轮廓、光源或空间关系表达情绪；有限色板 3 到 5 色，"
        "复古丝网印刷质感，正方形构图，周围留白，强缩略图辨识度。"
        "不要文字、不要字母、不要数字、不要 logo、不要歌名。"
    )


def generate_qiaomu_cover(
    *,
    title: str,
    clip_id: str,
    lrc: Path,
    output_dir: Path,
    provider: str,
    timeout: int,
) -> Path | None:
    script = QIAOMU_IMAGE_GENERATOR / "scripts" / "generate.py"
    if not script.exists():
        log(f"Qiaomu image generator not found, will use Suno cover fallback: {script}")
        return None

    cover_name = f"{safe_name(title)}-{clip_id[:8]}-qiaomu-cover.png"
    config_path = output_dir / f"{safe_name(title)}-{clip_id[:8]}-cover.visual.json"
    result_path = output_dir / f"{safe_name(title)}-{clip_id[:8]}-cover.result.json"
    cover_path = output_dir / cover_name
    if cover_path.exists() and cover_path.stat().st_size > 0:
        return cover_path

    config = {
        "task_id": f"qiaomu_music_cover_{clip_id[:8]}",
        "template": "album_cover",
        "output_dir": str(output_dir),
        "cover": {
            "enabled": True,
            "filename": cover_name,
            "style": "album-mondo-cover",
            "aspect_ratio": "1:1",
            "description": cover_description(title, lrc),
            "retry_count": 1,
        },
        "defaults": {
            "style": "album-mondo-cover",
            "aspect_ratio": "1:1",
            "provider": provider,
            "retry_count": 1,
        },
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    log(f"Generating Qiaomu album cover for {title} ({clip_id})...")
    try:
        proc = run(
            ["python3", str(script), str(config_path), "--workers", "1", "--no-insert", "--output", str(result_path)],
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log(f"Qiaomu cover generation timed out after {timeout}s; will use Suno cover fallback.")
        return None

    if proc.returncode != 0:
        log("Qiaomu cover generation failed; will use Suno cover fallback.")
        return None

    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        generated = result.get("cover", {}).get("path")
    except (OSError, json.JSONDecodeError, AttributeError):
        generated = None
    candidate = Path(generated) if generated else cover_path
    if candidate.exists() and candidate.stat().st_size > 0:
        if candidate != cover_path:
            shutil.copyfile(candidate, cover_path)
        return cover_path

    log("Qiaomu cover generation did not produce an image; will use Suno cover fallback.")
    return None


def ensure_suno_assets(ids: list[str], output_dir: Path, download: bool) -> None:
    if not download:
        return
    script = SUNO_MASTER / "scripts" / "download_clips.sh"
    if not script.exists():
        raise SystemExit(f"Missing qiaomu-suno-master downloader: {script}")
    run([
        "bash",
        str(script),
        "--ids",
        " ".join(ids),
        "--output-dir",
        str(output_dir),
        "--lyrics",
        "--lyrics-format",
        "lrc",
        "--require-lrc",
    ])


def post_json(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any], str]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"content-type": "application/json", "accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            text = response.read().decode("utf-8", errors="replace")
            headers = dict(response.headers.items())
            return response.status, headers, text
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return exc.code, dict(exc.headers.items()), text


def login(base_url: str, password: str) -> str:
    status, headers, text = post_json(f"{base_url.rstrip('/')}/api/login", {"password": password})
    if status >= 400:
        raise SystemExit(f"Qiaomu Music login failed ({status}): {text}")
    cookie_header = headers.get("Set-Cookie") or headers.get("set-cookie") or ""
    cookie = SimpleCookie()
    cookie.load(cookie_header)
    if "qm_admin" not in cookie:
        raise SystemExit("Qiaomu Music login did not return qm_admin cookie.")
    return f"qm_admin={cookie['qm_admin'].value}"


def guess_type(path: Path, fallback: str) -> str:
    return mimetypes.guess_type(path.name)[0] or fallback


def multipart_body(fields: dict[str, str], files: dict[str, Path]) -> tuple[bytes, str]:
    boundary = f"----qiaomu-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    def add(value: str | bytes) -> None:
        chunks.append(value if isinstance(value, bytes) else value.encode("utf-8"))

    for name, value in fields.items():
        add(f"--{boundary}\r\n")
        add(f'Content-Disposition: form-data; name="{name}"\r\n\r\n')
        add(value)
        add("\r\n")

    for name, path in files.items():
        content_type = guess_type(path, "application/octet-stream")
        add(f"--{boundary}\r\n")
        add(
            f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        )
        add(path.read_bytes())
        add("\r\n")

    add(f"--{boundary}--\r\n")
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def upload_track(
    base_url: str,
    cookie: str,
    *,
    title: str,
    artist: str,
    album: str,
    source: str,
    published: bool,
    audio: Path,
    lrc: Path,
    cover: Path,
) -> dict[str, Any]:
    fields = {
        "title": title,
        "artist": artist,
        "album": album,
        "source": source,
        "published": "true" if published else "false",
        "lyrics": lrc.read_text(encoding="utf-8", errors="replace"),
    }
    body, content_type = multipart_body(fields, {"audio": audio, "cover": cover})
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/admin/tracks",
        data=body,
        method="POST",
        headers={
            "content-type": content_type,
            "content-length": str(len(body)),
            "cookie": cookie,
            "accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            text = response.read().decode("utf-8", errors="replace")
            if response.status >= 400:
                raise SystemExit(f"Upload failed ({response.status}): {text}")
            return json.loads(text)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Upload failed ({exc.code}): {text}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", nargs="+", required=True, help="Suno clip IDs or song URLs")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--base-url", default=os.environ.get("QIAOMU_MUSIC_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument(
        "--admin-password",
        default=os.environ.get("QIAOMU_MUSIC_ADMIN_PASSWORD") or os.environ.get("ADMIN_PASSWORD", ""),
    )
    parser.add_argument("--artist", default="Qiaomu")
    parser.add_argument("--album", default="Qiaomu Radio")
    parser.add_argument("--source", default="Suno")
    parser.add_argument("--draft", action="store_true", help="Upload as unpublished draft")
    parser.add_argument("--no-download", action="store_true", help="Use existing local files only")
    parser.add_argument("--cover", type=Path, help="Use one explicit cover for all tracks")
    parser.add_argument("--no-generated-cover", action="store_true", help="Skip Qiaomu generated cover and use explicit/Suno cover")
    parser.add_argument("--cover-provider", default="jimeng", choices=["jimeng", "z-image"], help="Generated cover provider")
    parser.add_argument("--cover-timeout", type=int, default=240, help="Generated cover timeout in seconds")
    parser.add_argument("--json-out", type=Path, help="Write upload results JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not args.admin_password:
        raise SystemExit("Missing QIAOMU_MUSIC_ADMIN_PASSWORD or ADMIN_PASSWORD.")

    ids = normalize_ids(args.ids)
    ensure_suno_assets(ids, output_dir, download=not args.no_download)

    cookie = login(args.base_url, args.admin_password)
    uploaded: list[dict[str, Any]] = []

    for clip_id in ids:
        info = suno_info(clip_id)
        title = clip_title(info, clip_id)
        audio = find_asset(output_dir, clip_id, (".mp3", ".mpeg", ".m4a", ".wav"))
        lrc = find_asset(output_dir, clip_id, (".lrc",))
        if audio is None:
            raise SystemExit(f"Missing audio for {clip_id} in {output_dir}")
        if lrc is None:
            raise SystemExit(f"Missing LRC for {clip_id} in {output_dir}")
        validate_lrc(lrc)

        if args.cover:
            cover = args.cover.expanduser().resolve()
        elif args.no_generated_cover:
            cover = download_suno_cover(info, clip_id, output_dir)
        else:
            cover = generate_qiaomu_cover(
                title=title,
                clip_id=clip_id,
                lrc=lrc,
                output_dir=output_dir,
                provider=args.cover_provider,
                timeout=args.cover_timeout,
            ) or download_suno_cover(info, clip_id, output_dir)

        if cover is None or not cover.exists():
            raise SystemExit(f"Missing cover for {clip_id}; pass --cover or ensure suno info has image_url.")

        log(f"Uploading {title} ({clip_id}) to {args.base_url}...")
        track = upload_track(
            args.base_url,
            cookie,
            title=title,
            artist=args.artist,
            album=args.album,
            source=args.source,
            published=not args.draft,
            audio=audio,
            lrc=lrc,
            cover=cover,
        )
        uploaded.append({
            "suno_id": clip_id,
            "title": title,
            "audio": str(audio),
            "lrc": str(lrc),
            "cover": str(cover),
            "track": track,
        })

    result = {"base_url": args.base_url, "published": not args.draft, "uploaded": uploaded}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.json_out:
        args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
