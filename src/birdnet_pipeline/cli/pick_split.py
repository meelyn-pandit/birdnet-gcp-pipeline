"""Pick train/test recordings across sites and ARUs, copy them, write a split.

Every ARU contributes the same number of recordings, spread over months
and two hour blocks (dawn: before 08:00, morning: 08:00 and later).

  * test:  chosen at random, ignoring BirdNET, so accuracy measured on them
           reflects what the model will meet on the full archive.
  * train: mostly recordings where existing BirdNET results show many
           species (more songs to label per minute of listening), plus a
           few random ones so the model also sees quiet recordings.
           Never from a date already used for test at the same ARU
           (recordings 10 minutes apart are near-duplicates).

Only full-length recordings with a valid YYYYMMDD_HHMMSS name are used.
Copies are renamed <site>_<aru>_<YYYYMMDD_HHMMSS>.WAV because timestamps
repeat across ARUs and sites. The split CSV has a `priority` column:
label in priority order and you keep balanced coverage if you stop early.

Example:
    bgp-pick-split \\
        --site sswma=/media/.../sswma/sswma_audio_files \\
        --site cbma=/media/.../cbma/cbma_audio_files \\
        --site kiowa=/media/.../kiowa/kiowa_audio_files \\
        --site lwma=/media/.../lwma/lwma_audio_files --exclude lwma/aru01 \\
        --dest data/raw/round2 --split-out data/splits/round2_split.csv
"""
import argparse
import csv
import random
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .. import paths

NAME_RE = re.compile(r"^(20\d{2})(\d{2})(\d{2})_(\d{2})(\d{4})\.wav$", re.IGNORECASE)
FIELDS = ["recording", "split", "priority", "site", "aru", "date", "hour", "stratum",
          "pick", "birdnet_species", "source"]


@dataclass
class Rec:
    site: str
    aru: str
    path: Path
    date: str          # YYYYMMDD
    hour: int
    stratum: str       # YYYYMM-dawn / YYYYMM-morning
    richness: int = -1  # distinct BirdNET species at >= min_conf (-1 = not read)

    @property
    def recording(self) -> str:
        return f"{self.site}_{self.aru}_{self.path.stem}"


def candidates(site: str, aru_dir: Path) -> list[Rec]:
    """Valid, full-length recordings in one ARU folder."""
    files = []
    for p in sorted(aru_dir.iterdir()):      # sorted: same seed -> same picks
        m = NAME_RE.match(p.name)
        if m and 1 <= int(m.group(2)) <= 12:
            files.append((p, m, p.stat().st_size))
    if not files:
        return []
    full = Counter(s for _, _, s in files).most_common(1)[0][0]   # the usual file size
    out = []
    for p, m, size in files:
        if size != full:
            continue
        y, mo, d, h = m.group(1), m.group(2), m.group(3), int(m.group(4))
        block = "dawn" if h < 8 else "morning"
        out.append(Rec(site, aru_dir.name, p, f"{y}{mo}{d}", h, f"{y}{mo}-{block}"))
    return out


def birdnet_richness(rec: Rec, min_conf: float) -> int:
    csv_path = rec.path.with_name(f"{rec.path.stem}.BirdNET.results.csv")
    if not csv_path.exists():
        return 0
    species = set()
    with open(csv_path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                if float(r.get("confidence") or 0) >= min_conf:
                    species.add(r.get("common_name"))
            except ValueError:
                continue
    return len(species)


def round_robin(by_stratum: dict, n: int, rng: random.Random, choose) -> list[Rec]:
    """Take n recordings cycling over strata in random order; choose(pool) picks one."""
    strata = [s for s in by_stratum if by_stratum[s]]
    rng.shuffle(strata)
    picked, used_dates = [], set()
    while len(picked) < n and strata:
        for s in list(strata):
            if len(picked) == n:
                break
            pool = by_stratum[s]
            fresh = [r for r in pool if r.date not in used_dates] or pool
            r = choose(fresh)
            picked.append(r)
            used_dates.add(r.date)
            pool.remove(r)
            if not pool:
                strata.remove(s)
    return picked


def pick_aru(recs: list[Rec], n_train: int, n_test: int, n_random_train: int,
             min_conf: float, rng: random.Random) -> list[tuple[Rec, str, str]]:
    by_stratum = defaultdict(list)
    for r in recs:
        by_stratum[r.stratum].append(r)

    test = round_robin(by_stratum, n_test, rng, rng.choice)
    test_dates = {r.date for r in test}

    train_pool = defaultdict(list)
    for s, pool in by_stratum.items():
        train_pool[s] = [r for r in pool if r.date not in test_dates]

    rand = round_robin(train_pool, min(n_random_train, n_train), rng, rng.choice)

    for pool in train_pool.values():          # only now read BirdNET, for what is left
        for r in pool:
            r.richness = birdnet_richness(r, min_conf)

    def richest(pool):
        top = sorted(pool, key=lambda r: r.richness, reverse=True)
        k = max(1, len(top) // 10)            # random among the top 10%: not just the noisiest
        return rng.choice(top[:k])

    rich = round_robin(train_pool, n_train - len(rand), rng, richest)

    train = [(r, "train", "enriched") for r in rich] + [(r, "train", "random") for r in rand]
    tests = [(r, "test", "random") for r in test]
    # Interleave test and train so labeling in priority order stays balanced.
    out = []
    for i in range(max(len(train), len(tests))):
        if i < len(tests):
            out.append(tests[i])
        if i < len(train):
            out.append(train[i])
    return out


def parse_site(value: str) -> tuple[str, Path]:
    name, sep, path = value.partition("=")
    if not sep or not name or not path:
        raise argparse.ArgumentTypeError("use --site NAME=/path/to/<site>_audio_files")
    return name, Path(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", type=parse_site, action="append", required=True,
                    metavar="NAME=FOLDER", help="Site name and the folder holding its aru* folders")
    ap.add_argument("--exclude", nargs="*", default=[], metavar="SITE/ARU",
                    help="ARUs to skip, e.g. lwma/aru01")
    ap.add_argument("--aru-glob", default="aru0*")
    ap.add_argument("--train", type=int, default=6, help="Train recordings per ARU (default 6)")
    ap.add_argument("--test", type=int, default=4, help="Test recordings per ARU (default 4)")
    ap.add_argument("--random-train", type=int, default=2,
                    help="Of the train recordings, how many are random rather than species-rich")
    ap.add_argument("--min-conf", type=float, default=0.5,
                    help="BirdNET confidence for counting a species when ranking train candidates")
    ap.add_argument("--dest", type=Path, default=paths.RAW / "round2")
    ap.add_argument("--split-out", type=Path, default=paths.SPLITS / "round2_split.csv")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true", help="Write the split CSV but copy nothing")
    args = ap.parse_args(argv)

    if args.split_out.exists():
        sys.exit(f"{args.split_out} exists; choose another --split-out or remove it first")

    rng = random.Random(args.seed)
    rows = []
    for site, folder in args.site:
        aru_dirs = sorted(d for d in folder.glob(args.aru_glob) if d.is_dir())
        if not aru_dirs:
            sys.exit(f"No {args.aru_glob} folders in {folder}")
        for d in aru_dirs:
            if f"{site}/{d.name}" in args.exclude:
                continue
            recs = candidates(site, d)
            picks = pick_aru(recs, args.train, args.test, args.random_train, args.min_conf, rng)
            short = len(picks) < args.train + args.test
            print(f"{site}/{d.name}: {len(recs)} usable, picked {len(picks)}"
                  + ("  (fewer than asked)" if short else ""))
            for i, (r, split, how) in enumerate(picks, start=1):
                rows.append({"recording": r.recording, "split": split, "priority": i,
                             "site": site, "aru": r.aru, "date": r.date, "hour": r.hour,
                             "stratum": r.stratum, "pick": how,
                             "birdnet_species": r.richness if r.richness >= 0 else "",
                             "source": str(r.path)})

    rows.sort(key=lambda r: (r["priority"], r["site"], r["aru"]))
    args.split_out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.split_out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    n = Counter(r["split"] for r in rows)
    print(f"{n['train']} train, {n['test']} test -> {args.split_out}")
    if args.dry_run:
        return

    args.dest.mkdir(parents=True, exist_ok=True)
    for i, r in enumerate(rows, start=1):
        dst = args.dest / f"{r['recording']}{Path(r['source']).suffix}"
        if not dst.exists():
            shutil.copy2(r["source"], dst)
        if i % 25 == 0 or i == len(rows):
            print(f"  copied {i}/{len(rows)}", flush=True)
    print(f"Recordings in {args.dest}")


if __name__ == "__main__":
    main()
