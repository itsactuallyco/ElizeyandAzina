#!/usr/bin/env python3
"""
Story Garden — generate narration audio

    python3 make_audio.py                 # generate anything missing or changed
    python3 make_audio.py --only "Rumi"   # just one person, for auditioning voices
    python3 make_audio.py --provider elevenlabs
    python3 make_audio.py --estimate      # cost and size, generates nothing

One MP3 per paragraph, so the site can highlight along as it reads and only the
paragraphs you actually changed get regenerated. Audio lands in audio/ and the
site picks it up automatically; anything without a file falls back to the
browser voice.

Setup:
    pip install openai            # for OpenAI  (default)
    pip install elevenlabs        # for ElevenLabs

    export OPENAI_API_KEY=sk-...
    export ELEVENLABS_API_KEY=...
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")
STORIES = HERE / "stories.json"
AUDIO = HERE / "audio"
MANIFEST = AUDIO / "manifest.json"

# How the narrator should sound. Used verbatim by OpenAI; ElevenLabs takes
# its equivalent from the voice settings below.
INSTRUCTIONS = (
    "You are reading a bedtime story to a child between four and nine years old. "
    "Speak in a warm, gentle, unhurried voice, like a kind aunt reading aloud at "
    "the end of the day. Let the pace breathe — pause a beat at commas and a "
    "little longer at full stops. Sound interested in the story, never dramatic "
    "or performative. Standard American accent throughout."
)

PROVIDERS = {
    "openai": dict(
        model="gpt-4o-mini-tts",
        voice="sage",       # try: shimmer, nova, coral, sage
        rate_per_million=15.0,
    ),
    "elevenlabs": dict(
        model="eleven_multilingual_v2",
        voice="Rachel",        # any voice name from your ElevenLabs library
        rate_per_million=60.0,
    ),
}


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "unnamed"


def load_stories():
    if not STORIES.exists():
        sys.exit("No stories.json here. Run build.py first, or cd into the site folder.")
    return json.loads(STORIES.read_text(encoding="utf-8"))


def speakable(text, table):
    """Apply the pronunciation table — same swaps the browser voice makes."""
    if not table:
        return text
    keys = sorted(table, key=len, reverse=True)
    pattern = re.compile(
        r"(?<![A-Za-z])(" + "|".join(re.escape(k) for k in keys) + r")(?![A-Za-z])"
    )
    return pattern.sub(lambda m: table[m.group(1)], text)


def collect(data, only=None):
    """Every paragraph that needs audio, with a hash of the text that produced it."""
    table = data.get("pronunciations", {})
    jobs = []
    for person in data["people"]:
        if only and only.lower() not in person["name"].lower():
            continue
        paras = list(person["paras"]) + [person["lesson"]]
        folder = slug(person["name"])
        for i, para in enumerate(paras):
            spoken = speakable(para, table)
            jobs.append(dict(
                person=person["name"],
                folder=folder,
                index=i,
                path=AUDIO / folder / f"{i:02d}.mp3",
                text=spoken,
                hash=hashlib.sha256(spoken.encode("utf-8")).hexdigest()[:16],
            ))
    return jobs


def synth_openai(text, cfg):
    from openai import OpenAI
    client = OpenAI()
    res = client.audio.speech.create(
        model=cfg["model"],
        voice=cfg["voice"],
        input=text,
        instructions=INSTRUCTIONS,
        response_format="mp3",
    )
    return res.content


def synth_elevenlabs(text, cfg):
    from elevenlabs.client import ElevenLabs
    client = ElevenLabs()
    audio = client.text_to_speech.convert(
        voice_id=cfg["voice_id"],
        model_id=cfg["model"],
        text=text,
        output_format="mp3_44100_128",
        voice_settings={"stability": 0.55, "similarity_boost": 0.75,
                        "style": 0.15, "use_speaker_boost": True},
    )
    return b"".join(audio)


def resolve_elevenlabs_voice(cfg):
    from elevenlabs.client import ElevenLabs
    client = ElevenLabs()
    for v in client.voices.get_all().voices:
        if v.name.lower() == cfg["voice"].lower():
            return v.voice_id
    names = ", ".join(v.name for v in client.voices.get_all().voices[:12])
    sys.exit(f"No ElevenLabs voice called '{cfg['voice']}'. Available: {names}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="openai", choices=list(PROVIDERS))
    ap.add_argument("--voice", help="override the default voice")
    ap.add_argument("--only", help="just people whose name contains this")
    ap.add_argument("--force", action="store_true", help="regenerate even if unchanged")
    ap.add_argument("--estimate", action="store_true", help="report cost, generate nothing")
    args = ap.parse_args()

    cfg = dict(PROVIDERS[args.provider])
    if args.voice:
        cfg["voice"] = args.voice

    data = load_stories()
    jobs = collect(data, args.only)
    if not jobs:
        sys.exit("Nothing matched.")

    AUDIO.mkdir(exist_ok=True)
    manifest = {}
    if MANIFEST.exists():
        try:
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    hashes = manifest.get("hashes", {})

    todo = [j for j in jobs
            if args.force or not j["path"].exists()
            or hashes.get(f"{j['folder']}/{j['index']:02d}") != j["hash"]]

    chars = sum(len(j["text"]) for j in todo)
    cost = chars / 1_000_000 * cfg["rate_per_million"]
    print(f"{len(jobs)} paragraphs total, {len(todo)} need generating "
          f"({chars:,} characters)")
    print(f"Estimated cost with {args.provider}: ${cost:.2f}")

    if args.estimate:
        return
    if not todo:
        print("Everything is already up to date.")
        return
    if cost > 5 and input("Continue? [y/N] ").strip().lower() != "y":
        return

    if args.provider == "elevenlabs":
        cfg["voice_id"] = resolve_elevenlabs_voice(cfg)
    synth = {"openai": synth_openai, "elevenlabs": synth_elevenlabs}[args.provider]

    failures = []
    for n, job in enumerate(todo, 1):
        job["path"].parent.mkdir(parents=True, exist_ok=True)
        label = f"{job['person']} [{job['index'] + 1}]"
        print(f"  {n}/{len(todo)}  {label}", flush=True)
        for attempt in range(4):
            try:
                job["path"].write_bytes(synth(job["text"], cfg))
                hashes[f"{job['folder']}/{job['index']:02d}"] = job["hash"]
                break
            except Exception as err:
                if attempt == 3:
                    failures.append((label, str(err)))
                    print(f"      gave up: {err}")
                else:
                    wait = 2 ** attempt
                    print(f"      retrying in {wait}s ({err})")
                    time.sleep(wait)

    # rebuild the manifest from what is actually on disk
    people = {}
    for job in jobs:
        if job["path"].exists():
            people.setdefault(job["person"], []).append(
                f"{job['folder']}/{job['index']:02d}.mp3")
    for name in people:
        people[name].sort()

    MANIFEST.write_text(json.dumps(
        dict(provider=args.provider, voice=cfg["voice"], people=people, hashes=hashes),
        indent=1), encoding="utf-8")

    total_mb = sum(f.stat().st_size for f in AUDIO.rglob("*.mp3")) / 1_000_000
    complete = sum(1 for p in data["people"] if len(people.get(p["name"], []))
                   == len(p["paras"]) + 1)
    print(f"\nDone. {complete}/{len(data['people'])} people have full narration.")
    print(f"audio/ is {total_mb:.1f} MB across {len(list(AUDIO.rglob('*.mp3')))} files.")
    if failures:
        print(f"\n{len(failures)} paragraph(s) failed — rerun to pick them up:")
        for label, err in failures:
            print(f"  - {label}: {err}")


if __name__ == "__main__":
    main()
