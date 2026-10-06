#!/usr/bin/env python3
"""Verify byte preservation of executable code, native libraries and assets."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify(original_apks, target_apk):
    expected = {}
    for apk in original_apks:
        with zipfile.ZipFile(apk) as z:
            for name in z.namelist():
                if name.endswith(".dex") or name.startswith(("lib/", "assets/")):
                    if name.endswith("/"):
                        continue
                    checksum = digest(z.read(name))
                    if name in expected and expected[name] != checksum:
                        raise ValueError("Conflicting source entry: " + name)
                    expected[name] = checksum
    with zipfile.ZipFile(target_apk) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP entries")
        for name, checksum in expected.items():
            if name not in names or digest(z.read(name)) != checksum:
                raise ValueError("Original executable/asset modified or missing: " + name)
        uncompressed_libs = all(z.getinfo(n).compress_type == zipfile.ZIP_STORED for n in names if n.startswith("lib/") and n.endswith(".so"))
        if not uncompressed_libs:
            raise ValueError("Native libraries must remain uncompressed")
    return {
        "sha256": digest(Path(target_apk).read_bytes()),
        "preserved_entries": len(expected),
        "dex_files": sum(n.endswith(".dex") for n in expected),
        "native_libraries": sum(n.startswith("lib/") for n in expected),
        "assets": sum(n.startswith("assets/") for n in expected),
        "uncompressed_native_libraries": uncompressed_libs,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-dir", type=Path, required=True)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = verify(sorted(args.original_dir.glob("*.apk")), args.apk)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
