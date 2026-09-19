"""Build a complete, validated static snapshot in deploy/public/ (no upload).

A failed build keeps the previous snapshot; a successful build cannot retain
obsolete assets. Files are copied from their authoritative sources.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deploy" / "public"
METHODS = ("VISION.md", "ranking.md", "sources.yaml", "RENT.md", "FRICTION.md", "FACETS.md", "DESIGN.md", "edge.md", "anomalies.md")
REQUIRED_ASSETS = ("index.html", "morning.html", "favicon.svg")
ASSET_EXTENSIONS = {
    ".html", ".css", ".js", ".mjs", ".svg", ".png", ".jpg", ".jpeg",
    ".webp", ".avif", ".gif", ".ico", ".woff", ".woff2", ".txt",
    ".webmanifest", ".xml", ".json",
}
# Locally served publisher preview images (scripts/fetch_brief_media.py).
MEDIA_NAME = re.compile(r"[a-f0-9]{20}\.(?:jpg|jpeg|png|webp|avif|gif)")
MEDIA_MAX_BYTES = 900_000


class PageLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.duplicates: set[str] = set()
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        values = dict(attrs)
        ident = values.get("id")
        if ident:
            if ident in self.ids:
                self.duplicates.add(ident)
            self.ids.add(ident)
        for attr in ("href", "src", "poster"):
            if values.get(attr):
                if tag == "link" and values.get("rel") in {"preconnect", "dns-prefetch"}:
                    continue
                self.links.append((attr, values[attr]))


def validate_site(directory: Path) -> list[str]:
    """Check local navigation and anchors without making network requests."""
    base = directory.resolve()
    pages: dict[Path, PageLinks] = {}
    errors: list[str] = []
    for path in sorted(base.rglob("*.html")):
        page = PageLinks()
        page.feed(path.read_text(encoding="utf-8"))
        pages[path] = page
        for ident in sorted(page.duplicates):
            errors.append(f"{path.relative_to(base)}: duplicate id {ident}")
    for path, page in pages.items():
        for attr, raw in page.links:
            link = urlsplit(raw)
            if link.scheme or link.netloc:
                if link.scheme.lower() not in {"https", "http", "mailto", "tel", "data", ""}:
                    errors.append(f"{path.relative_to(base)}: unsafe {attr} scheme")
                continue
            decoded = unquote(link.path)
            if "\\" in decoded or "\x00" in decoded:
                errors.append(f"{path.relative_to(base)}: invalid local URL {raw}")
                continue
            target = (base / decoded.lstrip("/")) if decoded.startswith("/") else (path.parent / decoded)
            if not decoded:
                target = path
            target = target.resolve()
            if not target.is_relative_to(base):
                errors.append(f"{path.relative_to(base)}: URL escapes publish root {raw}")
                continue
            if target.is_dir():
                target /= "index.html"
            if not target.is_file():
                errors.append(f"{path.relative_to(base)}: missing local target {raw}")
            elif link.fragment and target in pages and unquote(link.fragment) not in pages[target].ids:
                errors.append(f"{path.relative_to(base)}: missing anchor {raw}")
    return sorted(set(errors))


def _safe_remove(path: Path, parent: Path) -> None:
    # Check final resolved paths before any recursive removal on Windows.
    if path.is_symlink() or path.resolve().parent != parent.resolve():
        raise ValueError(f"Unsafe temporary path: {path}")
    if path.exists():
        shutil.rmtree(path)


def stage(root: Path = ROOT, output: Path = OUT) -> dict:
    root = root.resolve()
    public = root / "public"
    if public.is_symlink():
        raise ValueError("The public source directory cannot be a symlink")
    output = output.absolute()
    resolved_output = output.resolve()
    inside_sources = resolved_output.is_relative_to(root) and not resolved_output.is_relative_to(root / "deploy")
    if output.is_symlink() or resolved_output == root or root.is_relative_to(resolved_output) or inside_sources:
        raise ValueError("The publish destination must be separate from source files")
    for name in REQUIRED_ASSETS:
        if not (public / name).is_file():
            raise ValueError(f"Missing public/{name}; rebuild the site first")
    for name in METHODS:
        source = root / name
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"Missing or unsafe method file: {name}")
    assets: list[Path] = []
    for source in sorted(public.rglob("*")):
        relative = source.relative_to(public)
        if source.is_symlink() or not source.resolve().is_relative_to(public.resolve()):
            raise ValueError(f"Public symlinks are not publishable: {relative}")
        if relative.as_posix() == "build-manifest.json":
            raise ValueError("build-manifest.json is generated during staging, not a source asset")
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            raise ValueError(f"Private file in public tree: {relative}")
        if source.is_file():
            if source.suffix.lower() not in ASSET_EXTENSIONS:
                raise ValueError(f"Unsupported public asset: {relative}")
            assets.append(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".vigie-stage-", dir=output.parent))
    backup: Path | None = None
    try:
        for source in assets:
            target = temporary / source.relative_to(public)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for name in METHODS:
            shutil.copy2(root / name, temporary / name)
        media_dir = root / "data" / "media" / "brief"
        if media_dir.is_symlink():
            raise ValueError("The media source directory cannot be a symlink")
        if media_dir.is_dir():
            for source in sorted(media_dir.iterdir()):
                if source.name.startswith("."):
                    continue  # a crashed fetch may leave a .part behind; pruning owns it
                if source.is_symlink() or not source.is_file():
                    raise ValueError(f"Unsafe media asset: {source.name}")
                if not MEDIA_NAME.fullmatch(source.name):
                    raise ValueError(f"Unsupported media asset: {source.name}")
                if source.stat().st_size > MEDIA_MAX_BYTES:
                    raise ValueError(f"Oversized media asset: {source.name}")
                target = temporary / "media" / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        errors = validate_site(temporary)
        if errors:
            raise ValueError("Invalid static site:\n" + "\n".join(errors))
        files = {
            p.relative_to(temporary).as_posix(): {
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in sorted(temporary.rglob("*")) if p.is_file()
        }
        manifest = {"schema_version": 1, "files": files}
        (temporary / "build-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if output.exists():
            if output.resolve().parent != output.parent.resolve() or not output.is_dir():
                raise ValueError("Unsafe publish destination")
            backup = Path(tempfile.mkdtemp(prefix=".vigie-previous-", dir=output.parent))
            backup.rmdir()
            # Rename only checked direct children of the chosen destination parent.
            output.rename(backup)
        try:
            temporary.rename(output)
        except BaseException:
            if backup is not None:
                backup.rename(output)
                backup = None
            raise
        if backup is not None:
            _safe_remove(backup, output.parent)
        return manifest
    finally:
        _safe_remove(temporary, output.parent)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    try:
        manifest = stage(output=args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Staging failed: {exc}\n")
    print(f"Validated {len(manifest['files'])} files -> {args.output}")
    print("No files have been uploaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
