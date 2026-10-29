import argparse
import json
import sys

from .bundle import read_json, verify_bundle, write_bundle
from .csv_inputs import load_csv_inputs
from .csv_starter import write_csv_starter
from .demo import demo_inputs
from .rolling_bundle import rolling_demo_inputs, verify_rolling_bundle, write_rolling_bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build and independently replay availability-aware feature evidence")
    sub = parser.add_subparsers(dest="command", required=True)
    starter = sub.add_parser("init-csv", help="Create editable synthetic input tables without a checkout")
    starter.add_argument("--out", required=True, help="New input directory; existing paths are refused")
    starter.add_argument("--rolling", action="store_true", help="Create rolling rather than scalar inputs")
    benchmark = sub.add_parser("benchmark", help="Measure scalar joins in isolated processes")
    benchmark.add_argument("--rows", nargs="+", type=int, default=[100_000, 1_000_000])
    benchmark.add_argument("--repeats", type=int, default=3)
    benchmark.add_argument("--seed", type=int, default=42)
    benchmark.add_argument("--out", default="outputs/scaling")
    for command in ("demo", "build", "verify", "rolling-demo", "aggregate", "verify-rolling"):
        p = sub.add_parser(command)
        p.add_argument("--out", default="outputs/rolling" if command in ("rolling-demo", "aggregate", "verify-rolling") else "outputs")
        if command in ("build", "aggregate"):
            source = p.add_mutually_exclusive_group(required=True)
            source.add_argument("--inputs", help="JSON observations, decisions and specs")
            source.add_argument("--csv-dir", help="Directory with observations.csv, decisions.csv and specs.csv (rolling_specs.csv for aggregate)")
    args = parser.parse_args(argv)
    try:
        if args.command == "init-csv":
            result = write_csv_starter(args.out, rolling=args.rolling)
        elif args.command == "benchmark":
            from .benchmark import run_scaling
            result = run_scaling(tuple(args.rows), args.repeats, args.seed, args.out)
        elif args.command == "verify-rolling":
            result = verify_rolling_bundle(args.out)
        elif args.command in ("rolling-demo", "aggregate"):
            data = rolling_demo_inputs() if args.command == "rolling-demo" else (
                load_csv_inputs(args.csv_dir, rolling=True) if args.csv_dir else read_json(args.inputs))
            result = write_rolling_bundle(data, args.out)
        else:
            if args.command == "verify":
                result = verify_bundle(args.out)
            else:
                data = demo_inputs() if args.command == "demo" else (
                    load_csv_inputs(args.csv_dir) if args.csv_dir else read_json(args.inputs))
                result = write_bundle(data, args.out)
    except (ValueError, OSError, KeyError) as exc:
        print(f"pitbridge: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0
