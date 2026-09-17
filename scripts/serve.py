"""Serve the local Vigie preview, or a validated static release directory."""
from __future__ import annotations

import argparse
import functools
import mimetypes
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from stage_public import METHODS

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
METHOD_FILES = {f"/{name}": ROOT / name for name in METHODS}


class VigieHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, methods=None, **kwargs):
        self.public_root = Path(directory or PUBLIC).resolve()
        self.methods = METHOD_FILES if methods is None and directory is None else (methods or {})
        super().__init__(*args, directory=str(self.public_root), **kwargs)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404, "Not found")
        return None

    def send_head(self):
        """GET and HEAD share the same route and filesystem checks."""
        path = unquote(urlsplit(self.path).path)
        if "\x00" in path or "\\" in path or any(part.startswith(".") for part in path.split("/") if part):
            self.send_error(404, "Not found")
            return None
        if path in self.methods:
            target = Path(self.methods[path])
            if target.is_symlink() or not target.is_file() or target.resolve().parent != ROOT.resolve():
                self.send_error(404, "Method file missing")
                return None
            file = target.open("rb")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(target.stat().st_size))
            self.end_headers()
            return file
        target = Path(self.translate_path(self.path))
        if not target.resolve().is_relative_to(self.public_root):
            self.send_error(404, "Not found")
            return None
        cursor = self.public_root
        for part in target.relative_to(self.public_root).parts:
            cursor /= part
            if cursor.is_symlink():
                self.send_error(404, "Not found")
                return None
        if target.is_dir():
            for index in ("index.html", "index.htm"):
                if (target / index).is_symlink():
                    self.send_error(404, "Not found")
                    return None
        return super().send_head()

    def guess_type(self, path):
        if Path(path).suffix.lower() in {".md", ".yaml", ".yml"}:
            return "text/plain; charset=utf-8"
        ctype, _ = mimetypes.guess_type(path)
        return ctype or "application/octet-stream"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--directory", type=Path, help="Serve an existing staged static directory")
    args = parser.parse_args()
    directory = args.directory.resolve() if args.directory else PUBLIC
    if not (directory / "index.html").is_file():
        parser.exit(1, f"Missing {directory / 'index.html'}. Rebuild the site first.\n")
    handler = functools.partial(VigieHandler, directory=directory, methods={} if args.directory else METHOD_FILES)
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as httpd:
        print(f"Vigie: http://127.0.0.1:{httpd.server_port}/", flush=True)
        print(f"Serving {directory}. Ctrl+C to stop.", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
