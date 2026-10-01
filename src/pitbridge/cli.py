import argparse
import json
import sys

from .bundle import read_json, verify_bundle, write_bundle
from .demo import demo_inputs


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build and independently replay availability-aware feature evidence")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("demo", "build", "verify"):
        p = sub.add_parser(command)
        p.add_argument("--out", default="outputs")
        if command == "build":
            p.add_argument("--inputs", required=True, help="JSON observations, decisions and specs")
    args = parser.parse_args(argv)
    try:
        result = verify_bundle(args.out) if args.command == "verify" else write_bundle(demo_inputs() if args.command == "demo" else read_json(args.inputs), args.out)
    except (ValueError, OSError, KeyError) as exc:
        print(f"pitbridge: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0
