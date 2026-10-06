#!/usr/bin/env python3
"""Exercise translated Java Formatter strings with correctly typed arguments."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile

TOKEN = re.compile(r"%(?:(\d+)\$)?([-#+ 0,(<]*)(\d*)(?:\.(\d+))?([tT]?[a-zA-Z%])")


def check(cases):
    statements = []
    for row in cases:
        arguments = {}
        ordinary = 0
        last = 0
        for match in TOKEN.finditer(row["text"]):
            conversion = match[5]
            if conversion in {"%", "n"}:
                continue
            if match[1]:
                index = int(match[1])
            elif "<" in match[2]:
                index = last
            else:
                ordinary += 1
                index = ordinary
            last = index
            if conversion[0] in "tT":
                value = "Long.valueOf(1700000000000L)"
            elif conversion in "doxX":
                value = "Integer.valueOf(3)"
            elif conversion in "eEfgGaA":
                value = "Double.valueOf(3.25)"
            elif conversion in "cC":
                value = "Character.valueOf('x')"
            elif conversion in "bB":
                value = "Boolean.TRUE"
            else:
                value = '"sample"'
            if index in arguments and arguments[index] != value:
                raise ValueError("Conflicting argument types in " + row["name"])
            arguments[index] = value
        values = ", ".join(arguments.get(i, '"sample"') for i in range(1, max(arguments, default=0) + 1))
        statements.append(
            "try { String.format(java.util.Locale.ROOT, "
            + json.dumps(row["text"], ensure_ascii=False)
            + ", new Object[]{" + values + "}); } catch (Exception e) { failures++; System.err.println("
            + json.dumps(row["name"]) + ' + ": " + e); }'
        )
    code = (
        "public class CheckFormats { public static void main(String[] args) { int failures=0;\n"
        + "\n".join(statements)
        + '\nSystem.out.println("Checked ' + str(len(cases)) + ' format strings; failures="+failures);'
        + " if(failures>0) System.exit(1); }}"
    )
    with tempfile.TemporaryDirectory(prefix="android-format-check-") as directory:
        source = Path(directory) / "CheckFormats.java"
        source.write_text(code)
        subprocess.run(["java", str(source)], check=True)
    return len(cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    args = parser.parse_args()
    check(json.loads(args.cases.read_text()))


if __name__ == "__main__":
    main()
