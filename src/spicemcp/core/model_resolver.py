"""3-tier model library resolution: bare filenames, relative paths, absolute paths."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModelReference:
    directive: str
    status: str  # found | not_found | passthrough | rejected | rewritten
    resolved_path: str | None = None
    host_path: str | None = None
    similar: list[str] = field(default_factory=list)


class ModelResolver:
    """Resolves .lib/.include path arguments against configured model_dirs mounts.

    Container layout: host model_dirs[0] -> /models/user_0, model_dirs[1] -> /models/user_1, etc.
    """

    _MODEL_EXTENSIONS = {".lib", ".sub", ".sp", ".spice", ".mod", ".net"}

    def __init__(self, model_dirs: list[Path | str]):
        self.model_dirs = [Path(d) for d in model_dirs]

    def resolve(self, directive: str, path_arg: str) -> ModelReference:
        """Classify and resolve a path argument from a .lib or .include directive.

        Returns a ModelReference indicating what should happen at simulation time.
        Caller is responsible for applying PATH_REJECTED violations; this method
        only classifies -- it does not raise.
        """
        path = Path(path_arg)

        if path.is_absolute():
            return self._resolve_absolute(directive, path)

        # Bare filename (parent is '.', meaning no directory component)
        if path.parent == Path("."):
            return self._resolve_bare(directive, path)

        # Relative path with directory components -- allowed as-is, resolves
        # in the work directory at simulation time. Not mount-checked here.
        return ModelReference(directive=directive, status="found", resolved_path=path_arg)

    def _resolve_absolute(self, directive: str, path: Path) -> ModelReference:
        for i, model_dir in enumerate(self.model_dirs):
            try:
                rel = path.relative_to(model_dir)
                container_path = f"/models/user_{i}/{rel.as_posix()}"
                return ModelReference(
                    directive=directive,
                    status="rewritten",
                    resolved_path=container_path,
                    host_path=str(path),
                )
            except ValueError:
                continue
        return ModelReference(
            directive=directive,
            status="rejected",
            similar=self.find_similar(path.name),
        )

    def _resolve_bare(self, directive: str, path: Path) -> ModelReference:
        for i, model_dir in enumerate(self.model_dirs):
            candidate = model_dir / path.name
            if candidate.exists():
                container_path = f"/models/user_{i}/{path.name}"
                return ModelReference(
                    directive=directive,
                    status="found",
                    resolved_path=container_path,
                    host_path=str(candidate),
                )
        # Not found in any configured mount -- pass through to simulator,
        # which may find it in its bundled library (e.g. LTspice stock models).
        return ModelReference(directive=directive, status="passthrough")

    def find_similar(self, filename: str) -> list[str]:
        """Return up to 3 close filename matches across all configured model_dirs."""
        candidates: list[str] = []
        for model_dir in self.model_dirs:
            if model_dir.is_dir():
                for f in model_dir.rglob("*"):
                    if f.is_file() and f.suffix.lower() in self._MODEL_EXTENSIONS:
                        candidates.append(f.name)
        return difflib.get_close_matches(filename, candidates, n=3, cutoff=0.4)
