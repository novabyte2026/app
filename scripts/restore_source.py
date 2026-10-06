#!/usr/bin/env python3
"""Reassemble explicitly published source chunks and verify both byte streams."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import tempfile


def restore(manifest_path, output):
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != 1 or manifest.get("format") != "gzip-chunks":
        raise ValueError("Unsupported source manifest")
    if output.exists():
        raise ValueError("Output already exists")
    parent = manifest_path.parent.resolve()
    if manifest["source_size"] <= 0 or manifest["compressed_size"] <= 0:
        raise ValueError("Invalid source sizes")
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = output.with_name(output.name + ".restoring")
    if pending.exists():
        raise ValueError("Unfinished output already exists")
    try:
        with tempfile.TemporaryFile() as compressed:
            compressed_hash = hashlib.sha256()
            compressed_size = 0
            seen = set()
            for part in manifest["parts"]:
                path = (parent / part["path"]).resolve()
                if not path.is_relative_to(parent) or path in seen:
                    raise ValueError("Unsafe or duplicate chunk path")
                seen.add(path)
                value = path.read_bytes()
                if len(value) != part["size"] or hashlib.sha256(value).hexdigest() != part["sha256"]:
                    raise ValueError("Source chunk checksum mismatch")
                compressed.write(value)
                compressed_hash.update(value)
                compressed_size += len(value)
            if compressed_size != manifest["compressed_size"] or compressed_hash.hexdigest() != manifest["compressed_sha256"]:
                raise ValueError("Compressed source checksum mismatch")
            compressed.seek(0)
            source_hash = hashlib.sha256()
            source_size = 0
            with gzip.GzipFile(fileobj=compressed, mode="rb") as source, pending.open("xb") as target:
                while True:
                    value = source.read(1024 * 1024)
                    if not value:
                        break
                    source_size += len(value)
                    if source_size > manifest["source_size"]:
                        raise ValueError("Decompressed source exceeds expected size")
                    source_hash.update(value)
                    target.write(value)
            if source_size != manifest["source_size"] or source_hash.hexdigest() != manifest["source_sha256"]:
                raise ValueError("Source package checksum mismatch")
        pending.replace(output)
    except BaseException:
        pending.unlink(missing_ok=True)
        raise
    print("Source restored and SHA-256 verified.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    restore(args.manifest, args.output)


if __name__ == "__main__":
    main()
