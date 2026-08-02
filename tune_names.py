#!/usr/bin/env python3
"""
Story Garden — pronunciation studio

    python3 tune_names.py                    # audition every name
    python3 tune_names.py --only Khalid      # just one
    python3 tune_names.py --model eleven_v3  # use IPA instead of respelling

Generates a two-second clip of each name on its own and builds names.html so you
can click through them all. The whole table costs a few cents, so you can iterate
on spellings as often as you like without touching the story audio.

The loop:
  1. python3 tune_names.py
  2. open names.html, click through, note what's wrong
  3. fix the "Say It Like" (or IPA) column in stories.xlsx
  4. python3 build.py && python3 tune_names.py     <- only changed names regenerate
  5. when you're happy: python3 make_audio.py --force
"""

import argparse
import hashlib
import html
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")
STORIES = HERE / "stories.json"
OUT = HERE / "audio" / "_names"
PAGE = HERE / "names.html"
STATE = OUT / "state.json"

INSTRUCTIONS = ("Say this name clearly and warmly, at a gentle pace, "
                "as if reading it aloud in a children's story.")


def synth_openai(text, voice):
    from openai import OpenAI
    return OpenAI().audio.speech.create(
        model="gpt-4o-mini-tts", voice=voice, input=text,
        instructions=INSTRUCTIONS, response_format="mp3").content


def synth_eleven(text, voice_id, model):
    from elevenlabs.client import ElevenLabs
    return b"".join(ElevenLabs().text_to_speech.convert(
        voice_id=voice_id, model_id=model, text=text,
        output_format="mp3_44100_128",
        voice_settings={"stability": 0.5, "similarity_boost": 0.75}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="openai", choices=["openai", "elevenlabs"])
    ap.add_argument("--model", default=None,
                    help="elevenlabs only: eleven_multilingual_v2 (alias) "
                         "or eleven_v3 (inline IPA)")
    ap.add_argument("--voice", default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if not STORIES.exists():
        sys.exit("Run build.py first.")
    data = json.loads(STORIES.read_text(encoding="utf-8"))
    say = data.get("pronunciations", {})
    ipa = data.get("ipa", {})
    if not say:
        sys.exit("No pronunciation entries found.")

    model = args.model or ("eleven_multilingual_v2" if args.provider == "elevenlabs" else "")
    use_ipa = model == "eleven_v3"
    voice = args.voice or ("shimmer" if args.provider == "openai" else "Rachel")

    # what we actually send for each written name
    entries = []
    for written, spoken in sorted(say.items()):
        if args.only and args.only.lower() not in written.lower():
            continue
        if use_ipa and written in ipa:
            sent, how = f"/{ipa[written]}/", "IPA"
        else:
            sent, how = spoken, "respelling"
        entries.append(dict(
            written=written, spoken=spoken, ipa=ipa.get(written, ""),
            sent=sent, how=how,
            slug=re.sub(r"[^a-z0-9]+", "-", written.lower()).strip("-"),
            hash=hashlib.sha256(f"{sent}|{voice}|{model}".encode()).hexdigest()[:12],
        ))

    OUT.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}

    todo = [e for e in entries
            if args.force or state.get(e["slug"]) != e["hash"]
            or not (OUT / f"{e['slug']}.mp3").exists()]

    chars = sum(len(e["sent"]) for e in todo)
    rate = 15.0 if args.provider == "openai" else 60.0
    print(f"{len(entries)} names, {len(todo)} to generate "
          f"({chars:,} chars, about ${chars / 1_000_000 * rate:.3f})")

    if todo:
        if args.provider == "elevenlabs":
            from elevenlabs.client import ElevenLabs
            vs = ElevenLabs().voices.get_all().voices
            match = next((v for v in vs if v.name.lower() == voice.lower()), None)
            if not match:
                sys.exit("No such ElevenLabs voice: " + voice)
            vid = match.voice_id
        for n, e in enumerate(todo, 1):
            print(f"  {n}/{len(todo)}  {e['written']}  ->  {e['sent']}", flush=True)
            try:
                audio = (synth_openai(e["sent"], voice) if args.provider == "openai"
                         else synth_eleven(e["sent"], vid, model))
                (OUT / f"{e['slug']}.mp3").write_bytes(audio)
                state[e["slug"]] = e["hash"]
            except Exception as err:
                print(f"      failed: {err}")
        STATE.write_text(json.dumps(state, indent=1))

    # ---- listening page ----
    rows = []
    for e in entries:
        src = f"audio/_names/{e['slug']}.mp3"
        exists = (OUT / f"{e['slug']}.mp3").exists()
        rows.append(f"""<tr>
  <td class="w">{html.escape(e['written'])}</td>
  <td><code>{html.escape(e['spoken'])}</code></td>
  <td><code class="ipa">{html.escape(e['ipa']) or '—'}</code></td>
  <td class="how">{e['how'] if exists else ''}</td>
  <td>{'<audio controls preload="none" src="' + src + '"></audio>' if exists
       else '<span class="muted">not generated</span>'}</td>
</tr>""")

    PAGE.write_text(f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pronunciation studio</title><style>
body{{font:15px/1.6 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
 max-width:1000px;margin:0 auto;padding:24px 18px 60px;color:#22313a;background:#F7FAF9}}
h1{{font-size:1.5rem;margin:0 0 4px}} p.lede{{color:#5E757E;margin:0 0 8px}}
input{{width:100%;padding:11px 14px;margin:16px 0;border:1px solid #D6DEDB;border-radius:9px;font:inherit}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden}}
th{{text-align:left;font-size:.72rem;letter-spacing:.07em;text-transform:uppercase;
 color:#5E757E;padding:10px 12px;background:#EEF3F1}}
td{{padding:9px 12px;border-top:1px solid #EEF3F1;vertical-align:middle}}
td.w{{font-weight:600;white-space:nowrap}}
code{{background:#EEF3F1;padding:2px 7px;border-radius:5px;font-size:.85em;
 font-family:ui-monospace,Menlo,Consolas,monospace}}
code.ipa{{background:#E8E2F3}}
td.how{{font-size:.72rem;color:#8CA0A8;text-transform:uppercase;letter-spacing:.05em}}
audio{{height:34px;width:210px;vertical-align:middle}}
.muted{{color:#B0BFC5;font-size:.85rem}}
tr.hide{{display:none}}
</style></head><body>
<h1>Pronunciation studio</h1>
<p class="lede">{voice}{' · ' + model if model else ''} · {len(entries)} names.
Click through, then correct the <b>Say It Like</b> or <b>IPA</b> column in
stories.xlsx and rerun <code>build.py &amp;&amp; tune_names.py</code>.</p>
<input id="f" placeholder="Filter names…" autofocus>
<table><thead><tr><th>Written</th><th>Say It Like</th><th>IPA</th><th>Used</th><th>Listen</th></tr></thead>
<tbody id="b">{''.join(rows)}</tbody></table>
<script>
const f=document.getElementById('f');
f.addEventListener('input',()=>{{const q=f.value.toLowerCase();
 for(const tr of document.getElementById('b').rows)
   tr.classList.toggle('hide', q && !tr.textContent.toLowerCase().includes(q));}});
document.addEventListener('play',e=>{{
 for(const a of document.querySelectorAll('audio')) if(a!==e.target) a.pause();}},true);
</script></body></html>""", encoding="utf-8")

    print(f"\nWrote {PAGE.name} — open it and click through.")
    if not use_ipa and ipa:
        print(f"({len(ipa)} names have IPA available. To hear it, you need "
              f"ElevenLabs: --provider elevenlabs --model eleven_v3)")


if __name__ == "__main__":
    main()
