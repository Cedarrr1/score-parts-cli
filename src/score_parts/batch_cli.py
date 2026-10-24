"""Headless batch entry point."""

import argparse
from pathlib import Path

from .batch import run_batch


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="score-parts-batch", description="Create a reviewed-part delivery workspace")
    parser.add_argument("inputs", nargs="+", type=Path, help="MusicXML files or folders")
    parser.add_argument("-o", "--output", type=Path, default=Path("deliveries"))
    parser.add_argument("--scale", type=int, default=70)
    parser.add_argument("--filename-pattern", default="{title} - {part}")
    args = parser.parse_args(argv)
    try:
        result = run_batch(args.inputs, args.output, scale=args.scale,
                           filename_pattern=args.filename_pattern,
                           on_event=lambda i, total, message: print(f"[{i}/{total}] {message}"))
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Error: {error}\n")
    print(f"Report: {result / 'report.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
