"""File storage — streaming writes, chunked reads, SHA-256 hashing, deduplication."""
import hashlib
import mimetypes
import shutil
from pathlib import Path
from typing import Generator

from fastapi import UploadFile

from app.config import settings
from app.models.job_file import FilePurpose


ALLOWED_MIME_TYPES: dict[FilePurpose, set[str]] = {
    FilePurpose.OCR: {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
        "image/tiff",
        "image/bmp",
        "application/pdf",
    },
    FilePurpose.TRANSCRIPTION: {
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/wave",
        "audio/x-wav",
        "audio/ogg",
        "audio/flac",
        "audio/aac",
        "audio/mp4",
        "audio/webm",
        "video/mp4",
        "video/webm",
        "video/quicktime",
        "video/x-msvideo",
    },
}


class FileValidationError(ValueError):
    """Raised when file type or size is invalid."""


class FileStorage:
    def __init__(
        self,
        upload_dir: str | None = None,
        chunk_size: int | None = None,
        max_size: int | None = None,
    ):
        self.upload_dir = Path(upload_dir or settings.upload_dir)
        self.chunk_size = chunk_size or settings.upload_chunk_size
        self.max_size = max_size or settings.max_upload_size_bytes
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def resolve_absolute_path(self, stored_path: str) -> Path:
        """Convert DB stored_path (relative) to absolute path on disk."""
        return self.upload_dir / stored_path

    def validate_mime_type(
        self, content_type: str | None, filename: str, purpose: FilePurpose
    ) -> str:
        """Validate MIME type against the purpose allowlist."""
        mime = content_type or ""
        if mime in ("application/octet-stream", ""):
            guessed, _ = mimetypes.guess_type(filename)
            mime = guessed or mime

        allowed = ALLOWED_MIME_TYPES[purpose]
        if mime not in allowed:
            raise FileValidationError(
                f"File type '{mime}' not allowed for {purpose.value}. "
                f"Allowed: {sorted(allowed)}"
            )
        return mime

    async def save_upload(
        self,
        upload_file: UploadFile,
        purpose: FilePurpose,
    ) -> tuple[str, str, int, str]:
        """
        Stream an upload to disk, hash while writing, and deduplicate by content hash.

        Returns:
            (stored_path, content_hash, file_size, file_type)
        """
        filename = upload_file.filename or "unnamed"
        file_type = self.validate_mime_type(
            upload_file.content_type, filename, purpose
        )

        ext = Path(filename).suffix.lower() or self._ext_from_mime(file_type)
        temp_path = self.upload_dir / f".tmp_{hashlib.sha256(filename.encode()).hexdigest()[:16]}"

        hasher = hashlib.sha256()
        total_size = 0

        try:
            with temp_path.open("wb") as out_file:
                while True:
                    chunk = await upload_file.read(self.chunk_size)
                    if not chunk:
                        break

                    total_size += len(chunk)
                    if total_size > self.max_size:
                        raise FileValidationError(
                            f"File exceeds max size of {self.max_size} bytes"
                        )

                    hasher.update(chunk)
                    out_file.write(chunk)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise
        finally:
            await upload_file.close()

        content_hash = hasher.hexdigest()
        final_path = self._path_for_hash(content_hash, ext)

        if final_path.exists():
            temp_path.unlink()
            stored_path = str(final_path.relative_to(self.upload_dir))
            return stored_path, content_hash, total_size, file_type

        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_path), str(final_path))

        stored_path = str(final_path.relative_to(self.upload_dir))
        return stored_path, content_hash, total_size, file_type

    def _path_for_hash(self, content_hash: str, ext: str) -> Path:
        """Shard storage by the first two hex chars of the content hash."""
        prefix = content_hash[:2]
        return self.upload_dir / prefix / f"{content_hash}{ext}"

    @staticmethod
    def _ext_from_mime(mime: str) -> str:
        ext = mimetypes.guess_extension(mime)
        return ext or ".bin"

    @staticmethod
    def iter_file_chunks(
        path: Path, chunk_size: int | None = None
    ) -> Generator[bytes, None, None]:
        """Yield file contents in fixed-size chunks for memory-efficient reads."""
        size = chunk_size or settings.upload_chunk_size
        with path.open("rb") as f:
            while True:
                chunk = f.read(size)
                if not chunk:
                    break
                yield chunk

    @staticmethod
    def compute_file_hash(path: Path) -> str:
        """Compute SHA-256 of an existing file using chunked reads."""
        hasher = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(settings.upload_chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()


file_storage = FileStorage()
