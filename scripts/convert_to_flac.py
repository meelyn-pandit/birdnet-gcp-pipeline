#!/usr/bin/env python3
"""Losslessly convert WAV files to FLAC, mirroring the folder structure.

Streams in blocks, so long recordings do not need to fit in memory.
Existing outputs are skipped, so the script can be rerun after interruption.

Note: FLAC conversion drops WAV-specific metadata chunks (for example
AudioMoth comment or GUANO chunks). Build metadata.csv from the original
WAVs first if you need anything from those chunks.

Example:
    python scripts/convert_to_flac.py /Volumes/Field/recordings /Volumes/Field/flac
"""
import argparse
from pathlib import Path

import soundfile as sf

BLOCK = 1 << 20  # frames per block


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    args = ap.parse_args()

    done = skipped = failed = 0
    for p in sorted(args.src.rglob("*")):
        if not p.is_file() or p.suffix.lower() != ".wav" or p.name.startswith("."):
            continue
        out = (args.dst / p.relative_to(args.src)).with_suffix(".flac")
        if out.exists():
            skipped += 1
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".flac.part")
        try:
            with sf.SoundFile(str(p)) as fin:
                # FLAC supports integer PCM up to 24-bit
                subtype = fin.subtype if fin.subtype in ("PCM_16", "PCM_24", "PCM_S8") else "PCM_24"
                with sf.SoundFile(str(tmp), "w", samplerate=fin.samplerate, channels=fin.channels,
                                  format="FLAC", subtype=subtype) as fout:
                    for block in fin.blocks(blocksize=BLOCK, always_2d=True):
                        fout.write(block)
            tmp.rename(out)
            done += 1
        except Exception as e:
            tmp.unlink(missing_ok=True)
            print(f"FAILED {p}: {e}")
            failed += 1
    print(f"Converted {done}, skipped {skipped} existing, failed {failed}")


if __name__ == "__main__":
    main()
