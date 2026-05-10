"""MCP tool handler for list_models -- search configured model_dirs."""

from __future__ import annotations

import difflib
from pathlib import Path

_MODEL_EXTENSIONS = {".lib", ".sub", ".sp", ".spice", ".mod", ".net", ".cir"}


def _scan_dir(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    out: list[Path] = []
    for f in directory.rglob("*"):
        if f.is_file() and f.suffix.lower() in _MODEL_EXTENSIONS:
            out.append(f)
    return out


def list_models(search: str = "") -> dict:
    """List model files in configured model_dirs, optionally filtered by 'search'.

    Substring match (case-insensitive) on filename. If no exact-substring matches
    are found AND a search term was given, returns up to 3 close matches.
    """
    from spicemcp import _globals

    config = _globals.config
    model_dirs = config.model_dirs if config else []
    searched_dirs = [str(d) for d in model_dirs]

    if not model_dirs:
        return {
            "matches": [],
            "total_matches": 0,
            "searched_dirs": [],
            "note": (
                "No model_dirs configured. Add directories to model_dirs in your"
                " spicemcp config to make local model libraries searchable."
            ),
        }

    needle = (search or "").strip().lower()
    matches: list[dict] = []
    all_names: list[str] = []

    for i, model_dir in enumerate(model_dirs):
        files = _scan_dir(model_dir)
        for f in files:
            all_names.append(f.name)
            if needle and needle not in f.name.lower():
                continue
            try:
                size_kb = f.stat().st_size / 1024.0
            except OSError:
                size_kb = 0.0
            container_path = f"/models/user_{i}/{f.relative_to(model_dir).as_posix()}"
            matches.append(
                {
                    "name": f.name,
                    "container_path": container_path,
                    "host_path": str(f),
                    "size_kb": round(size_kb, 2),
                    "source": f"user_{i}",
                }
            )

    note = (
        "Bundled LTspice models are not listed here -- bare filenames like"
        " 'LTC3312Sa.sub' are resolved by the simulator at runtime."
    )

    if needle and not matches:
        similar = difflib.get_close_matches(needle, [n.lower() for n in all_names], n=3, cutoff=0.4)
        if similar:
            note = f"No matches found for '{search}'. Similar filenames: {', '.join(similar)}."
        else:
            note = (
                f"No matches found for '{search}'."
                " Check the filename or add its directory to model_dirs in your config."
            )

    return {
        "matches": matches,
        "total_matches": len(matches),
        "searched_dirs": searched_dirs,
        "note": note,
    }
