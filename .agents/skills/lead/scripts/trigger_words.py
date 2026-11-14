"""Print oh-my-codex's own keyword matches for dispatch text, without starting a workflow.

Usage: trigger_words.py DISPATCH.txt [--package /prefix/node_modules/oh-my-codex]
Use '-' for stdin. The installed detector, not a copied keyword list, is authoritative.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

DETECT = """
import { pathToFileURL } from 'node:url';
import { readFileSync } from 'node:fs';
const { detectKeywords } = await import(pathToFileURL(process.argv[1]).href);
const matches = detectKeywords(readFileSync(0, 'utf8'));
console.log(JSON.stringify({ selected: matches[0] ?? null, matches }));
"""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dispatch")
    parser.add_argument("--package", type=Path)
    args = parser.parse_args(argv)
    try:
        package = args.package
        if package is None:
            root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, check=True)
            package = Path(root.stdout.strip()) / "oh-my-codex"
        detector = package / "dist/hooks/keyword-detector.js"
        if not detector.is_file():
            raise FileNotFoundError(f"oh-my-codex is absent at {package}; cannot check triggers")
        dispatch = sys.stdin.read() if args.dispatch == "-" else Path(args.dispatch).read_text()
        run = subprocess.run(
            ["node", "--input-type=module", "-e", DETECT, str(detector.resolve())],
            input=dispatch,
            capture_output=True,
            text=True,
            check=True,
        )
        print(json.dumps(json.loads(run.stdout), indent=2))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
