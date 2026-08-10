from __future__ import annotations

import json
import mimetypes
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import httpx


class PlanningCenterMediaCache:
    """Mirror tagged Planning Center media for authenticated local viewing."""

    def __init__(self, data_file: Path):
        self.directory = data_file.parent / "planning-center-media"
        self.manifest_path = self.directory / "manifest.json"

    def _manifest(self) -> dict[str, dict[str, Any]]:
        try:
            value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_manifest(self, value: dict[str, dict[str, Any]]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="manifest-", suffix=".json", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2)
                handle.write("\n")
            os.replace(temporary, self.manifest_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _cache_name(resource: dict[str, Any], content_type: str) -> str:
        requested = Path(str(resource.get("filename") or resource.get("title") or "resource")).name
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(requested).stem).strip("-.")[:80] or "resource"
        suffix = Path(requested).suffix.lower()
        if not suffix:
            suffix = mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) or ""
        return f"{re.sub(r'[^A-Za-z0-9_-]+', '-', str(resource.get('id') or 'media'))}-{stem}{suffix}"

    async def sync(
        self,
        client: Any,
        tagged_resources: dict[str, list[dict[str, Any]]],
    ) -> dict[str, list[dict[str, Any]]]:
        self.directory.mkdir(parents=True, exist_ok=True)
        old = self._manifest()
        current: dict[str, dict[str, Any]] = {}
        async with httpx.AsyncClient(timeout=45, follow_redirects=True) as downloader:
            for resources in tagged_resources.values():
                for resource in resources:
                    media_id = str(resource.get("id") or "")
                    action_url = str(resource.get("download_action_url") or "")
                    url = str(resource.get("url") or "")
                    source_fingerprint = f"{action_url or url}|{resource.get('updated_at') or ''}"
                    if not media_id or not (action_url or url.startswith(("https://", "http://"))):
                        continue
                    cached = old.get(media_id) or {}
                    cached_path = self.directory / str(cached.get("filename") or "")
                    if cached.get("source_url") != source_fingerprint or not cached_path.is_file():
                        # Planning Center attachment links may first require the
                        # PAT and then redirect to signed object storage.
                        download_url = await client.attachment_download_url(action_url) if action_url else url
                        if not download_url.startswith(("https://", "http://")):
                            raise RuntimeError(f"Planning Center did not provide a download URL for {resource.get('title') or media_id}")
                        response = await downloader.get(download_url)
                        response.raise_for_status()
                        content_type = response.headers.get("content-type") or str(resource.get("content_type") or "application/octet-stream")
                        expected_type = str(resource.get("content_type") or "")
                        if content_type.casefold().startswith("text/html") and expected_type and not expected_type.casefold().startswith("text/html"):
                            raise RuntimeError(f"Planning Center returned a sign-in page instead of {resource.get('title') or media_id}")
                        filename = self._cache_name(resource, content_type)
                        target = self.directory / filename
                        target.write_bytes(response.content)
                        if cached_path.is_file() and cached_path != target:
                            cached_path.unlink(missing_ok=True)
                        cached = {
                            "filename": filename,
                            "source_url": source_fingerprint,
                            "content_type": content_type.split(";", 1)[0],
                            "display_name": str(resource.get("filename") or resource.get("title") or filename),
                        }
                    current[media_id] = cached
                    resource["cached"] = True
                    resource["cached_filename"] = cached["filename"]
                    resource["content_type"] = cached.get("content_type") or resource.get("content_type")
        for media_id, cached in old.items():
            if media_id not in current:
                (self.directory / str(cached.get("filename") or "")).unlink(missing_ok=True)
        self._save_manifest(current)
        return tagged_resources

    def file_for(self, media_id: str) -> tuple[Path, dict[str, Any]] | None:
        metadata = self._manifest().get(str(media_id))
        if not metadata:
            return None
        path = self.directory / str(metadata.get("filename") or "")
        try:
            path.resolve().relative_to(self.directory.resolve())
        except ValueError:
            return None
        return (path, metadata) if path.is_file() else None
