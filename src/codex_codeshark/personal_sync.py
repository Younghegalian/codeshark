from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .migration import MigrationResult, export_personal_data, import_personal_data
from .secure_io import atomic_write_text, ensure_private_directory, ensure_private_file, read_private_text


SYNC_CONFIG_NAME = "personal-sync.json"
SYNC_ARCHIVE_NAME = "codeshark-personal-data.codeshark.zip"


class PersonalSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class PersonalSyncStatus:
    directory: Path | None
    automatic: bool


class PersonalDataSync:
    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir
        self.path = runtime_dir / SYNC_CONFIG_NAME
        ensure_private_directory(runtime_dir)
        ensure_private_file(self.path)

    def status(self) -> PersonalSyncStatus:
        if not self.path.is_file():
            return PersonalSyncStatus(None, False)
        try:
            content = read_private_text(self.path, max_bytes=20_000).strip()
            if not content:
                return PersonalSyncStatus(None, False)
            data = json.loads(content)
            raw_directory = data.get("directory")
            automatic = data.get("automatic") is True
        except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PersonalSyncError(f"cannot read personal sync configuration: {exc}") from exc
        if raw_directory is None and not automatic:
            return PersonalSyncStatus(None, False)
        if not isinstance(raw_directory, str):
            raise PersonalSyncError("personal sync configuration is invalid")
        directory = Path(raw_directory).expanduser()
        if not directory.is_absolute() or not directory.is_dir():
            raise PersonalSyncError("configured personal sync directory is unavailable")
        return PersonalSyncStatus(directory.resolve(), automatic)

    def configure(self, directory: Path) -> PersonalSyncStatus:
        candidate = directory.expanduser()
        if not candidate.is_absolute() or not candidate.is_dir():
            raise PersonalSyncError("sync directory must be an existing absolute directory")
        status = PersonalSyncStatus(candidate.resolve(), False)
        self._write(status)
        return status

    def disable(self) -> None:
        self._write(PersonalSyncStatus(None, False))

    def push(self, *, runtime_dir: Path | None = None) -> MigrationResult:
        status = self.status()
        if status.directory is None:
            raise PersonalSyncError("personal sync is not configured; run sync-data enable DIRECTORY")
        result = export_personal_data(
            status.directory / SYNC_ARCHIVE_NAME,
            runtime_dir=runtime_dir or self.runtime_dir,
            replace=True,
        )
        self._write(PersonalSyncStatus(status.directory, True))
        return result

    def pull(self, *, runtime_dir: Path | None = None, replace: bool = False) -> MigrationResult:
        status = self.status()
        if status.directory is None:
            raise PersonalSyncError("personal sync is not configured; run sync-data enable DIRECTORY")
        archive = status.directory / SYNC_ARCHIVE_NAME
        if not archive.is_file():
            raise PersonalSyncError(f"personal sync archive is missing: {archive}")
        result = import_personal_data(
            archive,
            runtime_dir=runtime_dir or self.runtime_dir,
            replace=replace,
        )
        self._write(PersonalSyncStatus(status.directory, True))
        return result

    def backup_if_enabled(self, *, runtime_dir: Path | None = None) -> MigrationResult | None:
        status = self.status()
        if status.directory is None or not status.automatic:
            return None
        return export_personal_data(
            status.directory / SYNC_ARCHIVE_NAME,
            runtime_dir=runtime_dir or self.runtime_dir,
            replace=True,
        )

    def _write(self, status: PersonalSyncStatus) -> None:
        payload = (
            {}
            if status.directory is None
            else {"directory": str(status.directory), "automatic": status.automatic}
        )
        atomic_write_text(self.path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
