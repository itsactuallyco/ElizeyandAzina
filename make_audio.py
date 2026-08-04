#!/usr/bin/env python3
"""
Story Garden — generate narration audio

    python3 make_audio.py                  # generate anything missing or changed
    python3 make_audio.py --only "Rumi"    # just one person, for auditioning voices
    python3 make_audio.py --provider openai
    python3 make_audio.py --model eleven_multilingual_v2   # skip IPA, plain respelling
    python3 make_audio.py --estimate       # cost and size, generates nothing

One MP3 per paragraph (both the regular Children's Story and, when a person
has one, their Story Mode retelling), so the site can highlight along as it
reads and only the paragraphs you actually changed get regenerated. Audio
lands in audio/<person>/ (regular) and audio/<person>/sm/ (Story Mode); the
site picks both up automatically and anything without a file falls back to
the browser voice.

Defaults to ElevenLabs' eleven_v3, which understands inline IPA phonemes —
any word in the Pronunciation tab that also has an IPA entry is spoken from
that instead of the plain respelling. Use tune_names.py to audition names
before spending on the full story audio.

Setup:
    pip install openai            # for --provider openai
    pip install elevenlabs        # for ElevenLabs (the default)

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

from dotenv import load_dotenv # type: ignore

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
        # eleven_v3 supports inline IPA, but as tested it drifts on repeated
        # occurrences of the same word within a clip regardless of voice —
        # multilingual_v2 doesn't support IPA but is reliable, and (unlike
        # v3) supports previous_text/next_text for cross-paragraph continuity.
        model="eleven_multilingual_v2",
        # two voices: the regular Children's Story and the Story Mode
        # retelling are read by different narrators.
        voices={"normal": "Nina", "storymode": "Fernanda"},
        rate_per_million=60.0,     # rough estimate — ElevenLabs bills against a
                                   # subscription's character quota, not a flat rate
    ),
}


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "unnamed"


def load_stories():
    if not STORIES.exists():
        sys.exit("No stories.json here. Run build.py first, or cd into the site folder.")
    return json.loads(STORIES.read_text(encoding="utf-8"))


def speakable(text, table, ipa=None, use_ipa=False):
    """Apply the pronunciation table — same swaps the browser voice makes.
    When use_ipa is on, a word with an IPA entry is spoken from that instead
    of its plain respelling (falls back to the respelling if it has none)."""
    if not table:
        return text
    ipa = ipa or {}
    keys = sorted(table, key=len, reverse=True)
    pattern = re.compile(
        r"(?<![A-Za-z])(" + "|".join(re.escape(k) for k in keys) + r")(?![A-Za-z])"
    )

    def repl(m):
        word = m.group(1)
        if use_ipa and ipa.get(word):
            return wrap_ipa(ipa[word])
        return table[word]

    return pattern.sub(repl, text)


def wrap_ipa(value):
    """The IPA column may or may not already include the /slashes/ — handle both."""
    value = value.strip()
    if value.startswith("/") and value.endswith("/"):
        return value
    return f"/{value}/"


def collect(data, only=None, ipa=None, use_ipa=False):
    """Every paragraph that needs audio — both the regular story and, for
    anyone who has one, their Story Mode retelling — with a hash of the text
    that produced it."""
    table = data.get("pronunciations", {})
    jobs = []
    for person in data["people"]:
        if only and only.lower() not in person["name"].lower():
            continue
        folder = slug(person["name"])
        variants = [("normal", folder, list(person["paras"]) + [person["lesson"]])]
        story_mode = person.get("storyMode")
        if story_mode:
            variants.append(("storymode", f"{folder}/sm",
                              list(story_mode["paras"]) + [story_mode["lesson"]]))
        for kind, sub, paras in variants:
            # every paragraph gets spoken up front so neighbours can be used
            # as context — ElevenLabs uses this to keep pacing/tone
            # consistent across the paragraph boundary instead of each clip
            # sounding like a disconnected, freshly-started sentence.
            spoken_paras = [speakable(p, table, ipa, use_ipa) for p in paras]
            for i, spoken in enumerate(spoken_paras):
                path = AUDIO / sub / f"{i:02d}.mp3"
                jobs.append(dict(
                    person=person["name"],
                    kind=kind,
                    folder=folder,
                    index=i,
                    key=path.relative_to(AUDIO).with_suffix("").as_posix(),
                    path=path,
                    text=spoken,
                    prev_text=spoken_paras[i - 1] if i > 0 else None,
                    next_text=spoken_paras[i + 1] if i + 1 < len(spoken_paras) else None,
                    hash=hashlib.sha256(spoken.encode("utf-8")).hexdigest()[:16],
                ))
    return jobs


def synth_openai(text, cfg, prev_text=None, next_text=None):
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


def synth_elevenlabs(text, cfg, prev_text=None, next_text=None):
    from elevenlabs.client import ElevenLabs
    client = ElevenLabs()
    kwargs = dict(
        voice_id=cfg["voice_id"],
        model_id=cfg["model"],
        text=text,
        output_format="mp3_44100_128",
        voice_settings={"stability": 0.55, "similarity_boost": 0.75,
                        "style": 0.15, "use_speaker_boost": True},
        # "best effort" determinism per ElevenLabs' docs — reduces (but does
        # not guarantee away) per-call variance in how a given line is read
        seed=4242,
    )
    # gives ElevenLabs the neighbouring paragraphs as context, so pacing and
    # tone carry across the cut instead of each clip sounding freshly started —
    # eleven_v3 rejects the request outright if these are present at all
    if cfg["model"] != "eleven_v3":
        if prev_text:
            kwargs["previous_text"] = prev_text
        if next_text:
            kwargs["next_text"] = next_text
    audio = client.text_to_speech.convert(**kwargs)
    return b"".join(audio)


# ElevenLabs' own stable IDs for its premade voices — looking these up by name
# needs the "voices_read" permission on your API key, which restricted keys
# often don't have. Known voices resolve for free; anything else still needs
# that permission (or pass --voice-id directly).
KNOWN_VOICE_IDS = {
    "rachel": "21m00Tcm4TlvDq8ikWAM",
}


_voice_cache = None


def resolve_elevenlabs_voice(name):
    global _voice_cache
    known = KNOWN_VOICE_IDS.get(name.lower())
    if known:
        return known
    if _voice_cache is None:
        from elevenlabs.client import ElevenLabs
        try:
            _voice_cache = ElevenLabs().voices.get_all().voices
        except Exception as err:
            sys.exit(f"Couldn't look up the ElevenLabs voice '{name}' by name: {err}\n"
                      f"Either add the 'voices_read' permission to your API key, or pass "
                      f"--voice-id-normal/--voice-id-storymode directly if you already know them.")
    # Voice Library names often carry a " - Descriptor" suffix (e.g. "Fernanda
    # - Calm Storytelling") that isn't part of what you'd naturally type — try
    # an exact match first, then fall back to "starts with".
    for v in _voice_cache:
        if v.name.lower() == name.lower():
            return v.voice_id
    prefix_matches = [v for v in _voice_cache if v.name.lower().startswith(name.lower())]
    if len(prefix_matches) == 1:
        return prefix_matches[0].voice_id
    if len(prefix_matches) > 1:
        sys.exit(f"'{name}' matches more than one ElevenLabs voice: "
                  f"{', '.join(v.name for v in prefix_matches)}. Use the fuller name to disambiguate.")
    names = ", ".join(v.name for v in _voice_cache[:12])
    sys.exit(f"No ElevenLabs voice called '{name}'. Available: {names}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="elevenlabs", choices=list(PROVIDERS))
    ap.add_argument("--model", help="override the default model "
                                    "(elevenlabs: eleven_v3 for IPA, or eleven_multilingual_v2)")
    ap.add_argument("--voice", help="override the default voice (openai, "
                                     "or elevenlabs if you want the same voice for both)")
    ap.add_argument("--voice-normal", help="elevenlabs only: voice for the regular story")
    ap.add_argument("--voice-storymode", help="elevenlabs only: voice for Story Mode")
    ap.add_argument("--voice-id", help="elevenlabs only: skip the by-name lookup "
                                        "(needs 'voices_read') for both voices")
    ap.add_argument("--voice-id-normal", help="elevenlabs only: skip the lookup for the regular voice")
    ap.add_argument("--voice-id-storymode", help="elevenlabs only: skip the lookup for the Story Mode voice")
    ap.add_argument("--only", help="just people whose name contains this")
    ap.add_argument("--force", action="store_true", help="regenerate even if unchanged")
    ap.add_argument("--estimate", action="store_true", help="report cost, generate nothing")
    args = ap.parse_args()

    cfg = dict(PROVIDERS[args.provider])
    if args.model:
        cfg["model"] = args.model
    if args.provider == "openai":
        if args.voice:
            cfg["voice"] = args.voice
    else:
        if args.voice:
            cfg["voices"] = {"normal": args.voice, "storymode": args.voice}
        if args.voice_normal or args.voice_storymode:
            cfg["voices"] = dict(cfg["voices"])
            if args.voice_normal:
                cfg["voices"]["normal"] = args.voice_normal
            if args.voice_storymode:
                cfg["voices"]["storymode"] = args.voice_storymode
    use_ipa = args.provider == "elevenlabs" and cfg["model"] == "eleven_v3"

    data = load_stories()
    ipa = data.get("ipa", {})
    jobs = collect(data, args.only, ipa, use_ipa)
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
            or hashes.get(j["key"]) != j["hash"]]

    chars = sum(len(j["text"]) for j in todo)
    cost = chars / 1_000_000 * cfg["rate_per_million"]
    print(f"{len(jobs)} paragraphs total, {len(todo)} need generating "
          f"({chars:,} characters)")
    if use_ipa:
        print(f"IPA: {len(ipa)} word(s) available, spoken as phonemes instead of respelling")
    print(f"Estimated cost with {args.provider} ({cfg['model']}): ${cost:.2f}")

    if args.estimate:
        return
    if not todo:
        print("Everything is already up to date.")
        return
    if cost > 5 and input("Continue? [y/N] ").strip().lower() != "y":
        return

    voice_ids = {}
    if args.provider == "elevenlabs":
        overrides = {"normal": args.voice_id_normal or args.voice_id,
                     "storymode": args.voice_id_storymode or args.voice_id}
        for kind, name in cfg["voices"].items():
            voice_ids[kind] = overrides[kind] or resolve_elevenlabs_voice(name)
    synth = {"openai": synth_openai, "elevenlabs": synth_elevenlabs}[args.provider]

    failures = []
    for n, job in enumerate(todo, 1):
        job["path"].parent.mkdir(parents=True, exist_ok=True)
        tag = "SM " if job["kind"] == "storymode" else ""
        label = f"{job['person']} [{tag}{job['index'] + 1}]"
        print(f"  {n}/{len(todo)}  {label}", flush=True)
        job_cfg = dict(cfg, voice_id=voice_ids.get(job["kind"])) if args.provider == "elevenlabs" else cfg
        for attempt in range(4):
            try:
                job["path"].write_bytes(
                    synth(job["text"], job_cfg, job["prev_text"], job["next_text"]))
                hashes[job["key"]] = job["hash"]
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
    people, story_mode = {}, {}
    for job in jobs:
        if job["path"].exists():
            target = story_mode if job["kind"] == "storymode" else people
            target.setdefault(job["person"], []).append(
                job["path"].relative_to(AUDIO).as_posix())
    for d in (people, story_mode):
        for name in d:
            d[name].sort()

    voice_info = cfg["voices"] if args.provider == "elevenlabs" else cfg["voice"]
    MANIFEST.write_text(json.dumps(
        dict(provider=args.provider, model=cfg["model"], voice=voice_info,
             people=people, storyMode=story_mode, hashes=hashes),
        indent=1), encoding="utf-8")

    total_mb = sum(f.stat().st_size for f in AUDIO.rglob("*.mp3")) / 1_000_000
    complete = sum(1 for p in data["people"] if len(people.get(p["name"], []))
                   == len(p["paras"]) + 1)
    sm_people = [p for p in data["people"] if p.get("storyMode")]
    sm_complete = sum(1 for p in sm_people if len(story_mode.get(p["name"], []))
                      == len(p["storyMode"]["paras"]) + 1)
    print(f"\nDone. {complete}/{len(data['people'])} people have full narration.")
    if sm_people:
        print(f"      {sm_complete}/{len(sm_people)} have full Story Mode narration.")
    print(f"audio/ is {total_mb:.1f} MB across {len(list(AUDIO.rglob('*.mp3')))} files.")
    if failures:
        print(f"\n{len(failures)} paragraph(s) failed — rerun to pick them up:")
        for label, err in failures:
            print(f"  - {label}: {err}")


if __name__ == "__main__":
    main()
