# Story Garden

A children's story site of great lives from Islamic history. Built to be edited
by you, not by a developer.

## What's in this folder

| File | What it is | Do you touch it? |
|---|---|---|
| `index.html` | The site itself — layout, artwork, narration | No |
| `stories.json` | Every category, story and pronunciation | Yes, if editing directly |
| `stories.xlsx` | The same content as a spreadsheet | Yes, if editing in Excel |
| `build.py` | Turns the spreadsheet into `stories.json` | Run it, don't edit it |
| `make_audio.py` | Records the narration MP3s | Run it, tweak the tone at the top |
| `audio/` | The recorded narration (appears after you run it) | No |

There are two ways to make changes and they produce the same result. **Pick one
and stay with it** — if you edit `stories.json` by hand and later run `build.py`,
the build overwrites your hand edits.

---

## Part 1 — Put it online (once)

### Step 1. Get the files into GitHub

1. Create a free account at [github.com](https://github.com) if you don't have one.
2. Click **+** (top right) → **New repository**. Name it `story-garden`.
   Leave it Public — nothing here is private, and Public keeps every free tier open to you.
3. On the empty repo page, click **uploading an existing file**.
4. Drag in all four files from this folder. Click **Commit changes**.

### Step 2. Connect Cloudflare Pages

1. Create a free account at [dash.cloudflare.com](https://dash.cloudflare.com).
2. Go to **Workers & Pages** → **Create application** → **Pages** → **Connect to Git**.
3. Authorise GitHub. When it asks which repositories, grant access to `story-garden`
   only — not your whole account.
4. Select `story-garden`, production branch `main`.
5. Build settings — this is the part people get wrong. There is no build step here,
   so:
   - **Framework preset:** None
   - **Build command:** *leave completely blank*
   - **Build output directory:** `/`
6. **Save and Deploy.**

About a minute later you'll have a live URL like
`story-garden-a1b.pages.dev`. That's the link you give your kids.

> **Choose Git integration, not Direct Upload.** Cloudflare doesn't let a
> Git-connected project switch to Direct Upload later. Git is what gives you the
> edit-in-the-browser workflow below, so start there.

### Step 3. Custom domain (optional)

Buy a domain anywhere (Cloudflare Registrar sells at cost, roughly $10/year).
In your Pages project → **Custom domains** → **Set up a domain**. Cloudflare
handles the DNS and the HTTPS certificate for free.

---

## Part 2 — Making changes

### Option A — edit the JSON in your browser (nothing to install)

1. Open your repo on github.com and click `stories.json`.
2. Click the pencil icon.
3. Make your change. Click **Commit changes**.
4. Cloudflare redeploys automatically. Refresh the site in ~30 seconds.

This works from your phone. Every change is versioned, so if something breaks you
can open the file's **History** and restore any earlier version.

**Adding a person** — copy an existing block inside `"people"` and adjust it:

```json
{
  "name": "Ibn Firnas",
  "area": "Flight & Invention",
  "cat": "makers",
  "obj": "gears",
  "wear": "turban",
  "robe": "#CBDDEF",
  "wc": "#F7DFA0",
  "tint": "#CBDDEF",
  "paras": [
    "First paragraph of the story.",
    "Second paragraph."
  ],
  "lesson": "This becomes the gold 'Something to remember' panel."
}
```

Watch for the two things that break JSON: every block needs a comma after it
*except* the last one in the list, and every piece of text needs its quotes.
If the site shows an error after an edit, that's almost always the cause.

### Option B — edit the spreadsheet

1. Open `stories.xlsx`. The **Stories** tab has one row per person; the story text
   lives in one cell with a blank line between paragraphs.
2. Save it.
3. In Terminal: `cd` into this folder and run `python3 build.py`
   (one-time setup: `pip install openpyxl`).
4. Upload the changed `stories.xlsx` **and** `stories.json` to GitHub.

`build.py` checks your work and tells you about anything it couldn't understand —
an unknown symbol name, a category that doesn't exist, a story too short to have a
lesson paragraph. It never crashes on bad input; it substitutes a default and
reports it.

---

## The fields explained

`cat` must match an `id` on the Categories list. `obj` is the object drawn beside
the figure. `wear` is the headwear. The three colours are the robe, the headwear,
and the card background.

**Headwear:** `turban` `hijab` `helmet` `crown` `sultan` `sikke` `cap`

**Symbols:** `trade` `shield` `sword` `lantern` `torchwater` `numbers` `school`
`hospital` `tools` `light` `medbook` `gears` `peacesword` `gold` `compass`
`scales` `quran` `city` `cipher` `heartbook` `twobooks` `flask` `globe` `heart`
`astrolabe` `quill` `observatory` `scroll` `ney` `dome` `oud` `map` `lawscroll`
`gathering` `bow`

**Palette:** mint `#CFE4DA` · sky `#CBDDEF` · blossom `#F6D7DD` · lilac `#DED4EE`
· saffron `#F7DFA0` · sand `#F3DCC4` · sage `#D9E8C9` · paper `#FDFAF5`

Any colour works, but these are the ones the site was designed around.

If a new person needs a symbol that isn't on the list, that's new artwork rather
than a config change — pick the closest one for now and it will look fine.

### Fixing a pronunciation

The narrator uses a lookup table so names are spoken correctly while staying
spelled correctly on screen. In `stories.json` under `"pronunciations"`, or on the
**Pronunciation** tab of the spreadsheet, add a pair:

```json
"Nishapur": "Nee-sha-poor"
```

Only the narration changes. The text your children read is untouched.

---

## Part 3 — Recorded narration

The site ships with a browser voice that works everywhere and costs nothing, but
it sounds mechanical. `make_audio.py` replaces it with real recorded narration.
Any story with audio uses it; anything without falls back to the browser voice,
so you can record a few at a time and nothing ever breaks.

### Setup (once)

```
pip install openai
export OPENAI_API_KEY=sk-...          # from platform.openai.com
```

On Windows PowerShell, use `$env:OPENAI_API_KEY="sk-..."` instead of `export`.

### Audition a voice before committing

```
python3 make_audio.py --only "Rumi"
```

That's six paragraphs and about five cents. Listen to `audio/rumi/00.mp3`. If the
voice isn't right, delete the folder and try another:

```
python3 make_audio.py --only "Rumi" --voice nova --force
```

OpenAI's warmer female voices are `shimmer` (the default here), `nova`, `coral`
and `sage`. The tone comes mostly from the `INSTRUCTIONS` block at the top of
`make_audio.py` — plain English, edit it freely. If you want her slower or
warmer, say so there and regenerate.

### Generate everything

```
python3 make_audio.py --estimate      # check the cost first
python3 make_audio.py
```

Then upload the whole `audio/` folder to GitHub alongside your other changes.

### Day to day

Run `make_audio.py` after every `build.py`. It hashes each paragraph, so it only
pays to regenerate the ones whose text actually changed — edit one sentence and
you'll re-record one paragraph, not two hours of audio. Failed paragraphs are
retried automatically and reported at the end; just rerun to pick them up.

The **Read to me** button turns green on stories that have recorded audio, so you
can see at a glance what's done.

### If you want better

`--provider elevenlabs` (with `pip install elevenlabs` and an `ELEVENLABS_API_KEY`)
gives noticeably better rhythm and pauses for roughly four times the cost. Set
`voice` in the `PROVIDERS` block to any voice name from your ElevenLabs library.
Worth trying only if the OpenAI narration still sounds flat to you.

---

## Previewing on your own computer

Double-clicking `index.html` will show an error, and that's expected — browsers
block a local file from reading another local file, which is how the site loads
`stories.json`. To preview properly, open Terminal in this folder and run:

```
python3 -m http.server 8000
```

Then visit `http://localhost:8000`. Press Ctrl+C when you're done.

## If something goes wrong

**The site says it couldn't load the stories.** `stories.json` has a syntax error.
Paste it into [jsonlint.com](https://jsonlint.com) to find the spot, or restore the
previous version from the file's History on GitHub.

**A change isn't showing up.** Check the **Deployments** tab of your Cloudflare
Pages project — the newest one should say Success. The site already defeats
browser caching on `stories.json`, so a stale copy shouldn't be the cause.

**A category shows "0 stories".** Every person's `cat` value must exactly match a
category `id`. `build.py` warns you about this; hand edits won't.
