# SPDX-License-Identifier: LGPL-2.1-or-later
"""Small independent, read-only OCI distribution/Flatpak-index fixture server."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import unquote, urlsplit

from json_validation import array, load_json, object_map, string, string_map


@dataclass
class Image:
    digest: str
    blobs: dict[str, bytes]
    record: dict[str, object]

    @classmethod
    def load(cls, layout: Path) -> Image:
        index = object_map(load_json(layout / "index.json"), "OCI index")
        manifests = array(index["manifests"], "OCI manifests")
        if len(manifests) != 1:
            raise ValueError("registry fixture requires one image per layout")
        descriptor = object_map(manifests[0], "OCI manifest descriptor")
        digest = string(descriptor["digest"], "OCI manifest digest")
        blobs = {}
        for path in (layout / "blobs/sha256").iterdir():
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != path.name:
                raise ValueError(f"OCI fixture checksum mismatch: {path}")
            blobs[f"sha256:{path.name}"] = data
        manifest = object_map(json.loads(blobs[digest]), "OCI manifest")
        config_descriptor = object_map(manifest["config"], "OCI config descriptor")
        config_digest = string(config_descriptor["digest"], "OCI config digest")
        config = object_map(json.loads(blobs[config_digest]), "OCI config")
        configuration = object_map(config.get("config", {}), "OCI configuration")
        return cls(digest, blobs, {
            "Tags": ["latest"], "Digest": digest,
            "MediaType": "application/vnd.oci.image.manifest.v1+json",
            "OS": string(config["os"], "OCI OS"),
            "Architecture": string(config["architecture"], "OCI architecture"),
            "Annotations": string_map(manifest.get("annotations", {}), "OCI annotations"),
            "Labels": string_map(configuration.get("Labels", {}), "OCI labels"),
        })


class Registry:
    def __init__(self, images: dict[str, Image]) -> None:
        self.images = images.copy()
        self.requests: list[str] = []
        self.signatures: dict[str, bytes] = {}
        # Retain previously published blobs to permit in-flight readers to finish.
        self.blobs = {name: dict(image.blobs) for name, image in images.items()}
        self.serial = 0

    def publish(self, name: str, image: Image) -> None:
        self.blobs.setdefault(name, {}).update(image.blobs)
        self.images[name] = image
        self.serial += 1

    def response(self, path: str) -> tuple[int, bytes, str]:
        path = unquote(urlsplit(path).path)
        self.requests.append(path)
        if path in self.signatures:
            return 200, self.signatures[path], "application/octet-stream"
        if path in {"/index/static", "/index/dynamic"}:
            body = {"Registry": "/", "Results": [
                {"Name": name, "Images": [image.record], "Lists": []}
                for name, image in sorted(self.images.items())
            ]}
            return 200, json.dumps(body).encode(), "application/json"
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "v2":
            _, name, kind, digest = parts
            if kind == "manifests" and name in self.images:
                image = self.images[name]
                if digest in {"latest", image.digest}:
                    return 200, image.blobs[image.digest], str(image.record["MediaType"])
            if kind == "blobs" and digest in self.blobs.get(name, {}):
                return 200, self.blobs[name][digest], "application/octet-stream"
        if path in {"/v2", "/v2/"}:
            return 200, b"{}", "application/json"
        return 404, b"not found", "text/plain"

    @contextmanager
    def serving(self) -> Generator[str, None, None]:
        registry = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                status, body, media_type = registry.response(self.path)
                self.send_response(status)
                self.send_header("Content-Type", media_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache")
                self.send_header("ETag", f'"blackbox-{registry.serial}"')
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            do_HEAD = do_GET

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"oci+http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
