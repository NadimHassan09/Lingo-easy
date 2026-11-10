#!/usr/bin/env python3
"""
Turn every Listening part's dialogue/monologue into an mp3 stored in the part's own folder, under the name the part already declares (audio.file).

  pip install edge-tts            # free, no API key (Microsoft Edge online read-aloud service; unofficial)
  # ffmpeg + ffprobe must be on PATH (or set FFMPEG_DIR)

  python scripts/generate_listening_audio.py                       # all 70 listening parts (placement + A1..C2), skips finished ones
  python scripts/generate_listening_audio.py --only LI001 LI101    # selected parts
  python scripts/generate_listening_audio.py --scope B2            # one scope: placement | A1..C2
  python scripts/generate_listening_audio.py --force               # regenerate even if up to date
  python scripts/generate_listening_audio.py --dry-run             # show the voice plan, call nothing

Per part it writes next to part.json:
  <audio.file>            the mp3 (one voice per speaker, short pause between turns, pace from the part's profile)
  audio-manifest.json     engine, voices, pace, per-turn start/end times, duration, size, sha256 of the mp3 and of the transcript it was made from
part.json itself is NOT modified (audio.file was already the reference), so content hashes and IDs stay valid. A part is re-generated when its transcript or the
voice plan changes. Network errors are retried; a part that still fails is reported and the others continue (exit status 1 at the end).
"""
import argparse
import asyncio
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assembler.layout import iter_scopes  # noqa: E402

MANIFEST = "audio-manifest.json"


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def find_tool(name):
    d = os.environ.get("FFMPEG_DIR")
    exe = shutil.which(name, path=d) if d else None
    exe = exe or shutil.which(name)
    if not exe:
        sys.exit(f"{name} not found: install ffmpeg (it includes ffprobe) or set FFMPEG_DIR")
    return exe


def voice_plan(part, cfg):
    """speaker id -> {voice, pitch}; and the delivery rate for the part's profile preset."""
    t = cfg["tts"]
    e = t["edge"]
    used, plan = {}, {}
    for sp in part["audio"]["speakers"]:
        pool = e["voices"][sp["gender"]][sp["accent"]]
        k = used.get((sp["gender"], sp["accent"]), 0)
        used[(sp["gender"], sp["accent"])] = k + 1
        plan[sp["id"]] = {"voice": pool[k % len(pool)], "pitch": e["pitch_variants_hz"][(k // len(pool)) % len(e["pitch_variants_hz"])]}
    preset = t["profile_to_preset"][part["profile"]]
    return plan, preset, e["rate_by_preset"][preset]


def part_files(only, scope_filter):
    bank = ROOT / "question_bank"
    for name, mode, level, d in iter_scopes(bank):
        if scope_filter and scope_filter not in (name, level, "placement" if mode == "placement" else None):
            continue
        for p in sorted((d / "listening").glob("*/part.json")):
            if only and p.parent.name not in only:
                continue
            yield name, p


def probe_duration(ffprobe, path):
    out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


async def synth(text, voice, rate, pitch, out, sem, retries=6):
    import edge_tts
    last = None
    for attempt in range(retries):
        try:
            async with sem:
                await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(out))
            if Path(out).stat().st_size > 800:
                return
            last = RuntimeError("empty audio returned")
        except Exception as e:  # noqa: BLE001 - network / service errors: retry with backoff
            last = e
        await asyncio.sleep(2.5 * (attempt + 1))  # the free service sometimes answers with no audio under load: back off and retry
    raise RuntimeError(f"speech synthesis failed for voice {voice}: {last}")


def clean(text):
    return " ".join(text.replace("—", ", ").replace("–", "-").split())


async def build_part(path, cfg, sem, tools, force, dry):
    part = load(path)
    folder = path.parent
    audio = part["audio"]
    plan, preset, rate = voice_plan(part, cfg)
    pause = cfg["tts"]["edge"]["pause_ms_between_turns"]
    transcript_sha = sha(audio["transcript"])
    target, manifest_path = folder / audio["file"], folder / MANIFEST
    state = {"transcript_sha256": transcript_sha, "voices": plan, "rate": rate, "pause_ms": pause}
    if target.exists() and manifest_path.exists() and not force:
        old = load(manifest_path)
        if all(old.get(k) == v for k, v in state.items()):
            return part["id"], "up_to_date", None
    if dry:
        return part["id"], "would_generate", {"preset": preset, "rate": rate, "voices": {s["id"] + " " + s["name"]: plan[s["id"]] for s in audio["speakers"]}, "turns": len(audio["transcript"])}
    ffmpeg, ffprobe = tools
    with tempfile.TemporaryDirectory(prefix=f"lingo_{part['id']}_") as tmp:
        tmp = Path(tmp)
        clips = [tmp / f"t{i:03d}.mp3" for i in range(len(audio["transcript"]))]
        await asyncio.gather(*[synth(clean(t["text"]), plan[t["speaker"]]["voice"], rate, plan[t["speaker"]]["pitch"], clips[i], sem) for i, t in enumerate(audio["transcript"])])
        silence = tmp / "pause.mp3"
        subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{pause / 1000:.3f}", "-c:a", "libmp3lame", "-b:a", "48k", str(silence)], check=True)
        listing = tmp / "list.txt"
        lines, turns, clock = [], [], 0.0
        pause_s = probe_duration(ffprobe, silence)
        for i, (t, c) in enumerate(zip(audio["transcript"], clips)):
            d = probe_duration(ffprobe, c)
            turns.append({"index": i, "speaker": t["speaker"], "start": round(clock, 2), "end": round(clock + d, 2)})
            clock += d + (pause_s if i < len(clips) - 1 else 0)
            lines.append(f"file '{c.as_posix()}'")
            if i < len(clips) - 1:
                lines.append(f"file '{silence.as_posix()}'")
        listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp_out = tmp / "final.mp3"
        subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c:a", "libmp3lame", "-b:a", "64k", "-ar", "24000", "-ac", "1", str(tmp_out)], check=True)
        duration = probe_duration(ffprobe, tmp_out)
        data = tmp_out.read_bytes()
        folder.mkdir(parents=True, exist_ok=True)
        tmp_target = folder / (audio["file"] + ".tmp")
        tmp_target.write_bytes(data)
        os.replace(tmp_target, target)
    try:
        import edge_tts
        engine = "edge-tts " + getattr(edge_tts, "__version__", "")
    except Exception:  # noqa: BLE001
        engine = "edge-tts"
    manifest = {"part_id": part["id"], "part_uuid": part.get("uuid"), "audio_file": audio["file"], "engine": engine.strip(),
                "service": "Microsoft Edge online read-aloud via the edge-tts package (unofficial, free, no API key)",
                "preset": preset, **state, "speakers": [{"id": s["id"], "name": s["name"], "gender": s["gender"], "accent": s["accent"], **plan[s["id"]]} for s in audio["speakers"]],
                "turns": turns, "duration_seconds": round(duration, 2), "size_bytes": len(data), "audio_sha256": sha(data),
                "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                "note": "Machine-generated speech for development and review. Check it by ear before treating it as final assessment audio."}
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return part["id"], "generated", {"seconds": manifest["duration_seconds"], "bytes": len(data)}


async def main_async(args):
    cfg = load(ROOT / "config" / "blueprint.json")
    tools = (None, None) if args.dry_run else (find_tool("ffmpeg"), find_tool("ffprobe"))
    if not args.dry_run:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            sys.exit("edge-tts is not installed: pip install edge-tts")
    sem = asyncio.Semaphore(args.concurrency)
    files = list(part_files(set(args.only or []), args.scope))
    if not files:
        sys.exit("no listening parts matched")
    ok = bad = 0
    summary = {"generated": 0, "up_to_date": 0, "would_generate": 0, "failed": 0}
    for scope, path in files:
        try:
            pid, status, info = await build_part(path, cfg, sem, tools, args.force, args.dry_run)
            summary[status] += 1
            print(f"{status:<15} {scope:<14} {pid}  {info if info else ''}", flush=True)
        except Exception as e:  # noqa: BLE001
            summary["failed"] += 1
            print(f"FAILED          {scope:<14} {path.parent.name}  {type(e).__name__}: {e}", flush=True)
    print(json.dumps(summary))
    return 1 if summary["failed"] else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="part ids, e.g. LI001 LI101")
    ap.add_argument("--scope", help="placement | A1..C2")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--concurrency", type=int, default=6, help="parallel speech requests")
    sys.exit(asyncio.run(main_async(ap.parse_args())))


if __name__ == "__main__":
    main()
