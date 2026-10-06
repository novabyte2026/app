#!/usr/bin/env python3
"""Prepare locally approved source inputs as checksummed compressed chunks.

This command writes local files only. Publishing those files is a separate
operation and requires authorization to disclose the application payload.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chunk-size", type=int, default=512 * 1024)
    args = parser.parse_args()
    if args.chunk_size < 1:
        parser.error("chunk size must be positive")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    parts = output / "source-parts"
    if parts.exists() and any(parts.iterdir()):
        raise ValueError("Output already contains source chunks")
    parts.mkdir(exist_ok=True)
    source_hash = hashlib.sha256()
    source_size = 0
    with tempfile.TemporaryFile() as temporary:
        with args.source.open("rb") as source, gzip.GzipFile(filename="", fileobj=temporary, mode="wb", compresslevel=9, mtime=0) as compressed:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                source_hash.update(block)
                source_size += len(block)
                compressed.write(block)
        temporary.seek(0)
        compressed_hash = hashlib.sha256()
        compressed_size = 0
        entries = []
        while True:
            block = temporary.read(args.chunk_size)
            if not block:
                break
            filename = "source-" + str(len(entries)).zfill(4) + ".bin"
            (parts / filename).write_bytes(block)
            compressed_hash.update(block)
            compressed_size += len(block)
            entries.append({"path": "source-parts/" + filename, "size": len(block), "sha256": hashlib.sha256(block).hexdigest()})
    manifest = {
        "schema": 1, "format": "gzip-chunks", "source_size": source_size,
        "source_sha256": source_hash.hexdigest(), "compressed_size": compressed_size,
        "compressed_sha256": compressed_hash.hexdigest(), "parts": entries,
    }
    (output / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Prepared " + str(len(entries)) + " local source chunks; nothing was published.")


if __name__ == "__main__":
    main()
