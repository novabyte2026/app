#!/usr/bin/env python3
"""Merge an authorized XAPK, apply native localization, align and sign an APK."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from apply_localization import ANDROID, android_text, apply, resources, write_tree
from check_formats import check
from verify_apk import verify

PINNED = {
    "APKEditor.jar": (
        "https://github.com/REAndroid/APKEditor/releases/download/V1.4.9/APKEditor-1.4.9.jar",
        "a9cd40df818845456be6d696de6110c89edf4b0a0580cb83438ed6b25a366e67",
    ),
    "apktool.jar": (
        "https://github.com/iBotPeaches/Apktool/releases/download/v3.0.3/apktool_3.0.3.jar",
        "dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423",
    ),
    "build-tools.zip": (
        "https://dl.google.com/android/repository/build-tools_r36_linux.zip",
        "5d9ac77fb6ff43d9da518a337b4fcf8f9097113df531d99ccefe80ef7ce8250b",
    ),
}


def sha256(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def run(command):
    subprocess.run([str(c) for c in command], check=True)


def tools(directory):
    directory.mkdir(parents=True, exist_ok=True)
    for name, (url, checksum) in PINNED.items():
        path = directory / name
        if not path.exists():
            temporary = path.with_suffix(path.suffix + ".download")
            with urllib.request.urlopen(url, timeout=120) as source, temporary.open("wb") as target:
                shutil.copyfileobj(source, target)
            if sha256(temporary) != checksum:
                raise ValueError("Tool checksum mismatch: " + name)
            temporary.replace(path)
        elif sha256(path) != checksum:
            raise ValueError("Tool checksum mismatch: " + name)
    android = directory / "android-build-tools"
    executable = android / "android-16/apksigner"
    if not executable.exists():
        android.mkdir(exist_ok=True)
        with zipfile.ZipFile(directory / "build-tools.zip") as archive:
            for entry in archive.infolist():
                destination = (android / entry.filename).resolve()
                if not destination.is_relative_to(android.resolve()):
                    raise ValueError("Unsafe tool archive entry")
                archive.extract(entry, android)
    for name in ("aapt2", "apksigner", "zipalign"):
        (android / "android-16" / name).chmod(0o755)
    return android / "android-16"


def sanitize_manifest(path):
    tree = ET.parse(path)
    root = tree.getroot()
    for attribute in ("requiredSplitTypes", "splitTypes", "isSplitRequired"):
        root.attrib.pop(ANDROID + attribute, None)
    application = root.find("application")
    application.attrib.pop(ANDROID + "isSplitRequired", None)
    obsolete = {
        "com.android.vending.splits.required", "com.android.vending.splits",
        "com.android.vending.derived.apk.id", "com.android.stamp.source", "com.android.stamp.type",
    }
    for node in list(application):
        if node.tag == "meta-data" and node.get(ANDROID + "name") in obsolete:
            application.remove(node)
    write_tree(tree, path)


def public_ids(project):
    return {(n.get("type"), n.get("name")): n.get("id") for n in ET.parse(project / "res/values/public.xml").getroot()}


def reserve_private_gaps(project):
    """Keep aapt2-generated private resources at their original numeric IDs.

    Patched aapt2 packs dollar-prefixed private names into free slots, even
    when public.xml specifies their original IDs. Reserving holes between
    these resources prevents packing from shifting references used by code.
    """
    public_path = project / "res/values/public.xml"
    tree = ET.parse(public_path)
    root = tree.getroot()
    groups = {}
    occupied = {int(node.get("id"), 16) for node in root}
    for node in root:
        if node.get("name", "").startswith("$"):
            groups.setdefault(node.get("type"), []).append(int(node.get("id"), 16))
    overlay = ET.ElementTree(ET.Element("resources"))
    additions = {}
    for kind, ids in groups.items():
        for value in range(min(ids), max(ids) + 1):
            if value in occupied:
                continue
            name = "rebuild_reserved_" + kind + "_" + format(value, "08x")
            identifier = "0x" + format(value, "08x")
            ET.SubElement(root, "public", type=kind, name=name, id=identifier)
            ET.SubElement(overlay.getroot(), "item", type=kind, name=name).text = "@null"
            additions[(kind, name)] = identifier
    if additions:
        write_tree(tree, public_path)
        write_tree(overlay, project / "res/values/rebuild_reserved.xml")
    return additions


def compare_resources(project, decoded, identifiers, data):
    if public_ids(decoded) != identifiers:
        raise ValueError("Resource IDs changed during compilation")
    count = 0
    for qualifier in ("values", "values-" + data.get("resource_qualifier", data["locale"]), "values-" + data.get("reference_locale", "en")):
        for filename in ("strings.xml", "plurals.xml", "arrays.xml"):
            expected_path = project / "res" / qualifier / filename
            if not expected_path.exists():
                continue
            _, expected = resources(expected_path)
            _, actual = resources(decoded / "res" / qualifier / filename)
            if set(expected) != set(actual):
                raise ValueError("Resource catalogue changed: " + qualifier + "/" + filename)
            for name, node in expected.items():
                if filename == "strings.xml":
                    good = android_text(node) == android_text(actual[name])
                elif filename == "plurals.xml":
                    good = {n.get("quantity"): android_text(n) for n in node} == {n.get("quantity"): android_text(n) for n in actual[name]}
                else:
                    good = [android_text(n) for n in node] == [android_text(n) for n in actual[name]]
                if not good:
                    raise ValueError("Compiled resource differs: " + name)
                count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tools", type=Path, default=Path(".tools"))
    parser.add_argument("--keystore", type=Path)
    parser.add_argument("--password-file", type=Path)
    parser.add_argument("--alias", default="localization")
    args = parser.parse_args()
    if bool(args.keystore) != bool(args.password_file):
        parser.error("--keystore and --password-file must be supplied together")
    data = json.loads(args.catalogue.read_text())
    checksum = sha256(args.source)
    if not data.get("source_sha256") or checksum != data["source_sha256"]:
        raise ValueError("Source package does not match the reviewed catalogue")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    android = tools(args.tools.resolve())
    jar = args.tools.resolve()
    with tempfile.TemporaryDirectory(prefix="native-localization-") as temporary:
        work = Path(temporary)
        original = work / "original"
        original.mkdir()
        with zipfile.ZipFile(args.source) as archive:
            for name in archive.namelist():
                if not name.endswith(".apk"):
                    continue
                destination = original / Path(name).name
                if destination.exists():
                    raise ValueError("Duplicate APK basename")
                destination.write_bytes(archive.read(name))
        apks = sorted(original.glob("*.apk"))
        if not apks:
            raise ValueError("Source archive has no APKs")
        merged = work / "merged.apk"
        run(["java", "-jar", jar / "APKEditor.jar", "m", "-i", original, "-o", merged])
        project = work / "project"
        run(["java", "-jar", jar / "apktool.jar", "d", "--no-src", merged, "-o", project])
        manifest_recovered = False
        try:
            ET.parse(project / "AndroidManifest.xml")
        except ET.ParseError:
            # Some merged AXML files trigger a decoder bug. Recover the base
            # manifest, then remove only the obsolete split/store metadata.
            candidates = []
            for apk in apks:
                badging = subprocess.check_output([str(android / "aapt2"), "dump", "badging", str(apk)], text=True)
                package = next(line for line in badging.splitlines() if line.startswith("package:"))
                if "split=" not in package:
                    candidates.append(apk)
            if len(candidates) != 1:
                raise ValueError("Cannot identify the base manifest")
            base = work / "base"
            run(["java", "-jar", jar / "apktool.jar", "d", "--no-src", candidates[0], "-o", base])
            shutil.copyfile(base / "AndroidManifest.xml", project / "AndroidManifest.xml")
            manifest_recovered = True
        sanitize_manifest(project / "AndroidManifest.xml")
        identifiers = public_ids(project)
        original_id_count = len(identifiers)
        reserved = reserve_private_gaps(project)
        identifiers.update(reserved)
        report, cases = apply(project, data)
        report["java_formatter_cases"] = check(cases)
        report["manifest_recovered_from_base"] = manifest_recovered
        report["original_resource_ids_preserved"] = original_id_count
        report["reserved_private_id_gaps"] = len(reserved)
        unsigned = work / "unsigned.apk"
        # Use Apktool's bundled patched aapt2; stock aapt2 rejects generated
        # drawable names present in some otherwise valid source packages.
        run(["java", "-jar", jar / "apktool.jar", "b", project, "-f", "-o", unsigned])
        aligned = work / "aligned.apk"
        run([android / "zipalign", "-P", "16", "-f", "4", unsigned, aligned])
        keystore = args.keystore.resolve() if args.keystore else work / "ephemeral.p12"
        password = args.password_file.resolve() if args.password_file else work / "password.txt"
        if not args.keystore:
            password.write_text(secrets.token_urlsafe(48) + "\n")
            password.chmod(0o600)
            run(["keytool", "-genkeypair", "-keystore", keystore, "-storetype", "PKCS12", "-alias", args.alias,
                 "-keyalg", "RSA", "-keysize", "4096", "-validity", "10000", "-storepass:file", password,
                 "-dname", "CN=Unofficial Native Localization"])
        result = output / "localized-native.apk"
        run([android / "apksigner", "sign", "--ks", keystore, "--ks-key-alias", args.alias,
             "--ks-pass", "file:" + str(password),
             "--v1-signing-enabled", "false", "--v2-signing-enabled", "true", "--v3-signing-enabled", "true",
             "--v4-signing-enabled", "false", "--out", result, aligned])
        signature = subprocess.check_output([str(android / "apksigner"), "verify", "--verbose", "--print-certs", str(result)], text=True)
        (output / "signature-verification.txt").write_text(signature)
        run([android / "zipalign", "-c", "-P", "16", "4", result])
        report["binary_preservation"] = verify(apks, result)
        decoded = work / "compiled"
        run(["java", "-jar", jar / "apktool.jar", "d", "--no-src", result, "-o", decoded])
        report["compiled_resources_checked"] = compare_resources(project, decoded, identifiers, data)
        report["signing_key"] = "provided" if args.keystore else "ephemeral; subsequent builds use a different certificate"
        report["signature_verified"] = True
        report["zip_alignment_verified"] = True
        qualifier = "values-" + data.get("resource_qualifier", data["locale"])
        shutil.copytree(project / "res" / qualifier, output / qualifier, dirs_exist_ok=True)
        (output / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
        (output / "SHA256SUMS.txt").write_text(sha256(result) + "  " + result.name + "\n")
        print(json.dumps(report))


if __name__ == "__main__":
    main()
