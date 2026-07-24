from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .secure_io import atomic_write_text


DEFAULT_PROJECT = "General"
GLOBAL_SCOPE = "global"

_WORKSPACE_NON_PROJECT_DIRECTORIES = frozenset({"deliverables", "inbox"})
PROJECT_SSOT_FILENAME = "PROJECT_SSOT.md"
_SSOT_MEMORY_START = "<!-- CODESHARK_PROJECT_MEMORY_START -->"
_SSOT_MEMORY_END = "<!-- CODESHARK_PROJECT_MEMORY_END -->"
_MAX_SSOT_BYTES = 512_000


@dataclass(frozen=True)
class WorkspaceProject:
    """A safely discovered project directory available to the administrator."""

    name: str
    path: Path


def _project_directory(workdir: Path, project: str) -> Path:
    normalized = normalize_project_name(project)
    if normalized.casefold() == DEFAULT_PROJECT.casefold():
        raise ValueError("General does not have a project directory")
    root = workdir.expanduser().resolve()
    directory = (root / normalized).resolve()
    if directory.parent != root or not directory.is_dir():
        raise ValueError(f"project directory is unavailable: {normalized}")
    return directory


def project_ssot_path(workdir: Path, project: str) -> Path:
    """Return the safe project-local SSOT path for one workspace project."""
    return _project_directory(workdir, project) / PROJECT_SSOT_FILENAME


def ensure_project_ssot(workdir: Path, project: str) -> Path:
    """Create the durable project brief before Codeshark begins project work."""
    path = project_ssot_path(workdir, project)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"project SSOT is not a regular file: {path}")
        return path
    template = "\n".join(
        (
            f"# {project} — Project SSOT",
            "",
            "This is the durable project-local source of truth for Codeshark and collaborators.",
            "Keep the owner-maintained brief current; Codeshark records explicit major details separately below.",
            "",
            "## Owner-maintained brief",
            "",
            "- Objective:",
            "- Scope:",
            "- Constraints:",
            "- Decisions:",
            "- Current status:",
            "- Deliverables:",
            "",
            _SSOT_MEMORY_START,
            "## Codeshark-captured project details",
            "",
            "_No project details have been captured yet._",
            _SSOT_MEMORY_END,
            "",
        )
    )
    atomic_write_text(path, template, mode=0o644, private_parent=False)
    return path


def read_project_ssot(workdir: Path, project: str, *, max_chars: int = 4_000) -> str:
    """Read a bounded project SSOT excerpt without following a symlink."""
    path = project_ssot_path(workdir, project)
    if not path.exists():
        return ""
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"project SSOT is not a regular file: {path}")
    if path.stat().st_size > _MAX_SSOT_BYTES:
        raise ValueError(f"project SSOT exceeds {_MAX_SSOT_BYTES} bytes: {path}")
    return path.read_text(encoding="utf-8")[:max_chars]


def sync_project_ssot(
    workdir: Path,
    project: str,
    details: tuple[tuple[str, str], ...],
) -> Path:
    """Synchronize Codeshark-owned project details without altering the owner brief."""
    path = ensure_project_ssot(workdir, project)
    current = read_project_ssot(workdir, project, max_chars=_MAX_SSOT_BYTES)
    lines = [_SSOT_MEMORY_START, "## Codeshark-captured project details", ""]
    if details:
        for title, content in details:
            normalized_title = " ".join(title.split()) or "Project detail"
            normalized_content = " ".join(content.split())
            if normalized_content:
                lines.append(f"- **{normalized_title}** — {normalized_content}")
    else:
        lines.append("_No project details have been captured yet._")
    lines.extend((_SSOT_MEMORY_END, ""))
    managed = "\n".join(lines)
    start = current.find(_SSOT_MEMORY_START)
    end = current.find(_SSOT_MEMORY_END, start + len(_SSOT_MEMORY_START))
    if start >= 0 and end >= 0:
        updated = current[:start].rstrip() + "\n\n" + managed + current[end + len(_SSOT_MEMORY_END) :]
    else:
        updated = current.rstrip() + "\n\n" + managed
    atomic_write_text(path, updated, mode=0o644, private_parent=False)
    return path


def discover_workspace_projects(
    workdir: Path,
    delegated_roots: tuple[Path, ...],
    *,
    agent_repository_root: Path | None = None,
    limit: int = 48,
) -> tuple[WorkspaceProject, ...]:
    """Discover only physical direct-child projects in the configured workspace.

    A workspace directory is the project source of truth. Hidden internal
    directories plus the transport-only ``inbox`` and ``deliverables`` folders
    are excluded; every other direct child is a project. Delegated roots remain
    writable administrator roots, but never become implicit project candidates.
    """

    root = workdir.expanduser().resolve()
    del delegated_roots, agent_repository_root
    discovered: dict[Path, WorkspaceProject] = {}

    def add(path: Path, name: str) -> None:
        if len(discovered) >= limit:
            return
        try:
            resolved = path.resolve()
        except OSError:
            return
        if resolved == root or not resolved.is_dir():
            return
        try:
            normalized = normalize_project_name(name)
        except ValueError:
            return
        discovered.setdefault(resolved, WorkspaceProject(normalized, resolved))

    try:
        workspace_children = sorted(root.iterdir(), key=lambda path: path.name.casefold())
    except OSError:
        workspace_children = []
    for child in workspace_children:
        if (
            child.name.startswith(".")
            or child.name in _WORKSPACE_NON_PROJECT_DIRECTORIES
            or not child.is_dir()
        ):
            continue
        add(child, child.name)

    return tuple(sorted(discovered.values(), key=lambda item: item.name.casefold()))


def project_named_in_request(
    request: str,
    candidates: tuple[WorkspaceProject, ...],
) -> str | None:
    """Return an unambiguous project explicitly named by path or label."""

    request_path = request.replace("\\", "/")
    normalized_request = _normalize_project_text(request_path)
    matches: list[str] = []
    for candidate in candidates:
        absolute_path = candidate.path.as_posix()
        label = _normalize_project_text(candidate.name)
        basename = _normalize_project_text(candidate.path.name)
        if absolute_path in request_path or (
            label and _contains_project_label(normalized_request, label)
        ) or (
            basename and _contains_project_label(normalized_request, basename)
        ):
            matches.append(candidate.name)
    unique = tuple(dict.fromkeys(matches))
    return unique[0] if len(unique) == 1 else None


def _normalize_project_text(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).casefold().strip()


def _contains_project_label(text: str, label: str) -> bool:
    return bool(re.search(rf"(?:^|\s){re.escape(label)}(?:$|\s)", text))


def normalize_project_name(value: str) -> str:
    name = " ".join(value.split())
    if not name:
        raise ValueError("project name must not be empty")
    if len(name) > 80 or any(ord(character) < 32 for character in name):
        raise ValueError("project name must be a single line of at most 80 characters")
    if name.casefold() == GLOBAL_SCOPE:
        raise ValueError(f"{GLOBAL_SCOPE!r} is reserved for global records")
    return name


def normalize_scope(value: str) -> str:
    if " ".join(value.split()).casefold() == GLOBAL_SCOPE:
        return GLOBAL_SCOPE
    return normalize_project_name(value)


def create_workspace_project(workdir: Path, name: str) -> WorkspaceProject:
    """Create one safe direct-child workspace project selected by Project Router."""
    normalized = normalize_project_name(name)
    if (
        normalized.casefold() == DEFAULT_PROJECT.casefold()
        or normalized.startswith(".")
        or normalized in _WORKSPACE_NON_PROJECT_DIRECTORIES
        or "/" in normalized
        or "\\" in normalized
    ):
        raise ValueError("project name must be a non-system direct workspace folder name")
    root = workdir.expanduser().resolve()
    candidate = root / normalized
    if candidate.parent != root:
        raise ValueError("project must be created directly inside the configured workspace")
    if candidate.exists():
        if not candidate.is_dir():
            raise ValueError("project path already exists and is not a directory")
    else:
        candidate.mkdir(mode=0o700)
    return WorkspaceProject(normalized, candidate.resolve())
