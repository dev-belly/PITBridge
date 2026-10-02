import argparse
import json
import sys

from .bundle import read_json, verify_bundle, write_bundle
from .demo import demo_inputs
from .rolling_bundle import rolling_demo_inputs, verify_rolling_bundle, write_rolling_bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build and independently replay availability-aware feature evidence")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("demo", "build", "verify", "rolling-demo", "aggregate", "verify-rolling"):
        p = sub.add_parser(command)
        p.add_argument("--out", default="outputs/rolling" if command in ("rolling-demo", "aggregate", "verify-rolling") else "outputs")
        if command in ("build", "aggregate"):
            p.add_argument("--inputs", required=True, help="JSON observations, decisions and specs")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify-rolling":
            result = verify_rolling_bundle(args.out)
        elif args.command in ("rolling-demo", "aggregate"):
            data = rolling_demo_inputs() if args.command == "rolling-demo" else read_json(args.inputs)
            result = write_rolling_bundle(data, args.out)
        else:
            result = verify_bundle(args.out) if args.command == "verify" else write_bundle(demo_inputs() if args.command == "demo" else read_json(args.inputs), args.out)
    except (ValueError, OSError, KeyError) as exc:
        print(f"pitbridge: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0
