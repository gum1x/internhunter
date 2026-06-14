from __future__ import annotations

from pathlib import Path

_EXTS = (".md", ".txt", ".pdf")


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        return ""  # pypdf not installed -> PDF unsupported, fail soft
    try:
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return ""


def _candidates(path: Path) -> list[Path]:
    if path.suffix and path.is_file():
        return [path]
    # treat `path` as a stem or directory: try <path>.<ext>, <path>/resume.<ext>, ./resume.<ext>
    out: list[Path] = []
    for ext in _EXTS:
        out.append(Path(str(path) + ext))
        out.append(path / f"resume{ext}")
        out.append(Path(f"resume{ext}"))
    return out


def load_resume_text(path: Path) -> str | None:
    """Read a résumé from .md/.txt/.pdf. Returns None if none found / empty."""
    for cand in _candidates(path):
        try:
            if not cand.is_file():
                continue
            text = _read_pdf(cand) if cand.suffix == ".pdf" else cand.read_text(
                encoding="utf-8", errors="ignore"
            )
            if text.strip():
                return text.strip()
        except Exception:
            continue
    return None
