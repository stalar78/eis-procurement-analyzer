from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from radar.models import ArtifactRecord


INVALID_NAMES = {"", ".", ".."}


def safe_filename(value: str, fallback: str = "artifact") -> str:
    name = Path(str(value or "")).name
    if re.match(r"^[a-zA-Z]:", str(value or "")):
        name = ""
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    name = re.sub(r"[\x00-\x1f]+", " ", name).strip(" ._")
    if name in INVALID_NAMES:
        name = fallback
    return name[:180]


def ensure_inside(base: Path, child: Path) -> Path:
    base_resolved = base.resolve()
    child_resolved = child.resolve()
    if base_resolved != child_resolved and base_resolved not in child_resolved.parents:
        raise ValueError(f"Artifact path escapes procurement directory: {child}")
    return child


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_records(records: list[ArtifactRecord]) -> str:
    payload = [
        {
            "artifact_type": item.artifact_type,
            "source_url": item.source_url,
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
            "document_type": item.document_type,
        }
        for item in sorted(records, key=lambda row: (row.artifact_type, row.source_url, row.sha256))
    ]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ArtifactRegistry:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def procurement_dir(self, procurement_number: str) -> Path:
        number = safe_filename(procurement_number, "unknown")
        path = self.root / "procurements" / number
        path.mkdir(parents=True, exist_ok=True)
        for subdir in ("pages", "documents", "extracted", "analysis", "manifests"):
            (path / subdir).mkdir(parents=True, exist_ok=True)
        return path

    def register_existing(
        self,
        procurement_number: str,
        path: str | Path,
        *,
        artifact_type: str = "document",
        source_url: str = "",
        original_filename: str = "",
        content_type: str = "",
        extraction_status: str = "",
        document_type: str = "",
        document_confidence: str = "",
    ) -> ArtifactRecord:
        proc_dir = self.procurement_dir(procurement_number)
        file_path = ensure_inside(proc_dir, Path(path)) if Path(path).is_absolute() else ensure_inside(proc_dir, proc_dir / path)
        if not file_path.exists():
            raise FileNotFoundError(file_path)
        return ArtifactRecord(
            procurement_number=procurement_number,
            artifact_type=artifact_type,
            source_url=source_url,
            local_path=str(file_path),
            original_filename=safe_filename(original_filename or file_path.name),
            content_type=content_type,
            size_bytes=file_path.stat().st_size,
            sha256=sha256_file(file_path),
            downloaded_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            extraction_status=extraction_status,
            document_type=document_type,
            document_confidence=document_confidence,
        )

    def load_manifest_records(self, procurement_number: str, manifest_path: str | Path) -> list[ArtifactRecord]:
        path = Path(manifest_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("artifacts", data) if isinstance(data, dict) else data
        records: list[ArtifactRecord] = []
        for row in rows:
            record = ArtifactRecord(
                procurement_number=procurement_number,
                artifact_type=row.get("artifact_type", "document"),
                source_url=row.get("source_url", ""),
                local_path=row.get("local_path", ""),
                original_filename=safe_filename(row.get("original_filename", "")),
                content_type=row.get("content_type", ""),
                size_bytes=int(row.get("size_bytes") or 0),
                sha256=row.get("sha256", ""),
                downloaded_at=row.get("downloaded_at", ""),
                extraction_status=row.get("extraction_status", ""),
                document_type=row.get("document_type", ""),
                document_confidence=row.get("document_confidence", ""),
            )
            records.append(record)
        return records

