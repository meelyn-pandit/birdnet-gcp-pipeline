"""Total up the archive by format and estimate upload time.

Example:
    bgp-estimate-upload /Volumes/Field/recordings --mbps 50
"""
import argparse
from collections import Counter
from pathlib import Path

from ..metadata import AUDIO_EXTS


def human(n):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1000:
            return f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} PB"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", type=Path)
    ap.add_argument("--mbps", type=float, default=50, help="Upload speed in megabits per second")
    args = ap.parse_args(argv)
    if not args.root.is_dir():
        ap.error(f"not a directory: {args.root}")

    sizes, counts = Counter(), Counter()
    for p in args.root.rglob("*"):
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS and not p.name.startswith("."):
            ext = p.suffix.lower()
            sizes[ext] += p.stat().st_size
            counts[ext] += 1

    total = sum(sizes.values())
    for ext in sorted(sizes):
        print(f"{ext:6} {counts[ext]:>8} files  {human(sizes[ext]):>10}")
    print(f"{'total':6} {sum(counts.values()):>8} files  {human(total):>10}")

    hours = total * 8 / (args.mbps * 1e6) / 3600
    print(f"\nEstimated upload at {args.mbps:g} Mbps: {hours:.1f} hours")
    if sizes[".wav"]:
        flac_hours = (total - sizes[".wav"] / 2) * 8 / (args.mbps * 1e6) / 3600
        print(f"If WAVs are converted to FLAC (~50% smaller, varies): ~{flac_hours:.1f} hours")


if __name__ == "__main__":
    main()
