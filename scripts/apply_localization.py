#!/usr/bin/env python3
"""Apply a name-based Android resource catalogue without changing resource IDs."""
import argparse
import copy
import json
import re
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET

ANDROID = "{http://schemas.android.com/apk/res/android}"
ET.register_namespace("android", ANDROID[1:-1])
FORMAT = re.compile(r"%(?:(?:\d+)\$)?[-#+ 0,(<]*\d*(?:\.\d+)?(?:[tT][a-zA-Z]|[a-zA-Z%])")


def android_text(node):
    """Undo Android quoting/escaping after XML entity decoding."""
    raw = "".join(node.itertext())
    result = []
    i = 0
    while i < len(raw):
        char = raw[i]
        if char == '"':
            i += 1
            continue
        if char == "\\" and i + 1 < len(raw):
            i += 1
            char = raw[i]
            if char == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", raw[i + 1:i + 5]):
                result.append(chr(int(raw[i + 1:i + 5], 16)))
                i += 5
                continue
            char = {"n": "\n", "t": "\t", "r": "\r"}.get(char, char)
        result.append(char)
        i += 1
    return "".join(result)


def escaped_text(text):
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")


def assign_text(node, text):
    # A single styling span is retained. Richer spans require segmented targets.
    if len(node):
        if len(node) != 1 or len(node[0]) or (node.text or "").strip() or (node[0].tail or "").strip():
            raise ValueError("Segmented translation required: " + node.attrib.get("name", ""))
        node.text = '"'
        node[0].text = escaped_text(text)
        node[0].tail = '"'
    else:
        node.text = '"' + escaped_text(text) + '"'


def resources(path):
    tree = ET.parse(path)
    return tree, {n.attrib["name"]: n for n in tree.getroot() if "name" in n.attrib}


def write_tree(tree, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="    ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def same_formats(source, target, name):
    if Counter(FORMAT.findall(source)) != Counter(FORMAT.findall(target)):
        raise ValueError("Format placeholders changed: " + name)


def apply(project, data, replace_default=True):
    res = project / "res"
    base_path = res / "values/strings.xml"
    base_tree, base = resources(base_path)
    reference_path = res / ("values-" + data.get("reference_locale", "en")) / "strings.xml"
    reference_tree, reference = resources(reference_path) if reference_path.exists() else (None, {})
    canonical = {**base, **reference}
    translations = data["strings"]
    unknown = set(translations) - set(base)
    if unknown:
        raise ValueError("Unknown resource names: " + ", ".join(sorted(unknown)))
    changed = {}
    formatter_cases = []
    for name, target in translations.items():
        if not isinstance(target, str):
            raise ValueError("Non-string target: " + name)
        source = canonical[name]
        source_text = android_text(source)
        same_formats(source_text, target, name)
        if source.attrib.get("translatable") == "false" and target != source_text:
            raise ValueError("Non-translatable resource changed: " + name)
        if target != source_text:
            changed[name] = target
        if source.attrib.get("formatted") != "false" and FORMAT.search(target):
            formatter_cases.append({"name": name, "text": target})
    # Full Hebrew resource file also retains all technical/legal entries verbatim.
    localized = copy.deepcopy(base_tree)
    localized_names = {n.attrib["name"]: n for n in localized.getroot()}
    for name, target in changed.items():
        assign_text(localized_names[name], target)
        if replace_default:
            assign_text(base[name], target)
            if name in reference:
                assign_text(reference[name], target)
    qualifier = data.get("resource_qualifier", data["locale"])
    locale_dir = res / ("values-" + qualifier)
    write_tree(localized, locale_dir / "strings.xml")
    if replace_default:
        write_tree(base_tree, base_path)
        if reference_tree is not None:
            write_tree(reference_tree, reference_path)

    plural_targets = data.get("plurals", {})
    plural_tree, plural_sources = resources(res / "values/plurals.xml")
    plural_overlay = ET.ElementTree(ET.Element("resources"))
    for name, quantities in plural_targets.items():
        source = plural_sources[name]
        original_items = {n.attrib["quantity"]: android_text(n) for n in source}
        node = ET.Element("plurals", dict(source.attrib))
        for quantity, target in quantities.items():
            original = original_items.get(quantity, original_items["other"])
            same_formats(original, target, name + ":" + quantity)
            item = ET.SubElement(node, "item", quantity=quantity)
            assign_text(item, target)
            formatter_cases.append({"name": name + ":" + quantity, "text": target})
        plural_overlay.getroot().append(copy.deepcopy(node))
        if replace_default:
            source[:] = list(node)
    if plural_targets:
        write_tree(plural_overlay, locale_dir / "plurals.xml")
        if replace_default:
            write_tree(plural_tree, res / "values/plurals.xml")
            # The English split does not necessarily include library plurals.
            ref_plural_path = reference_path.parent / "plurals.xml"
            if ref_plural_path.exists():
                ref_plural_tree, ref_plurals = resources(ref_plural_path)
                for node in plural_overlay.getroot():
                    if node.attrib["name"] in ref_plurals:
                        ref_plurals[node.attrib["name"]][:] = list(copy.deepcopy(node))
                write_tree(ref_plural_tree, ref_plural_path)

    array_tree, arrays = resources(res / "values/arrays.xml")
    array_overlay = ET.ElementTree(ET.Element("resources"))
    for name, items in data.get("array_items", {}).items():
        source = arrays[name]
        node = copy.deepcopy(source)
        for index, target in items.items():
            index = int(index)
            same_formats(android_text(source[index]), target, name + ":" + str(index))
            assign_text(node[index], target)
            if replace_default:
                assign_text(source[index], target)
        array_overlay.getroot().append(node)
    if len(array_overlay.getroot()):
        write_tree(array_overlay, locale_dir / "arrays.xml")
        if replace_default:
            write_tree(array_tree, res / "values/arrays.xml")

    manifest_path = project / "AndroidManifest.xml"
    manifest = ET.parse(manifest_path)
    if data["locale"] in {"he", "iw", "ar", "fa", "ur"}:
        manifest.getroot().find("application").set(ANDROID + "supportsRtl", "true")
        write_tree(manifest, manifest_path)
    config_name = manifest.getroot().find("application").get(ANDROID + "localeConfig")
    if config_name and config_name.startswith("@xml/"):
        config_path = res / "xml" / (config_name.split("/", 1)[1] + ".xml")
        config = ET.parse(config_path)
        if data["locale"] not in {n.get(ANDROID + "name") for n in config.getroot()}:
            ET.SubElement(config.getroot(), "locale", {ANDROID + "name": data["locale"]})
            write_tree(config, config_path)

    # Read back the generated XML now, before spending time rebuilding.
    _, final = resources(locale_dir / "strings.xml")
    for name, target in changed.items():
        if android_text(final[name]) != target:
            raise ValueError("XML escaping round trip failed: " + name)
    report = {
        "native_only": data.get("native_only", True),
        "locale": data["locale"],
        "reference_locale": data.get("reference_locale", "en"),
        "source_sha256": data.get("source_sha256"),
        "native_resource_names": len(base),
        "reviewed_names": len(translations),
        "translated_names": len(changed),
        "preserved_names": len(base) - len(changed),
        "plurals": len(plural_targets),
        "arrays": len(data.get("array_items", {})),
        "format_mismatches": 0,
        "flutter_translated": False,
        "runtime_tested": False,
    }
    return report, formatter_cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--translations", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--formatter-cases", type=Path)
    parser.add_argument("--locale-only", action="store_true")
    args = parser.parse_args()
    report, cases = apply(args.project, json.loads(args.translations.read_text()), not args.locale_only)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    if args.formatter_cases:
        args.formatter_cases.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
