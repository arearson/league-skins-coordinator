# LoL Skin Exporter — Setup Guide

This tool reads your own League of Legends skin and crafting inventory
straight from your League client (the same client running on your PC)
and saves it to a JSON file you can send to friends.

It only ever talks to `127.0.0.1` (your own computer). It never sends
your data anywhere on its own.

---

## Step 1 — Build the .exe (you do this once)

I can't compile a Windows `.exe` directly in this environment, but turning
the script into one takes about 2 minutes on any Windows PC with Python:

1. Install Python from https://python.org (check "Add to PATH" during install)
2. Open Command Prompt in the folder with `export_skins.py`
3. Run:
   ```
   pip install pyinstaller
   pyinstaller --onefile --console --name "LoL_Skin_Exporter" export_skins.py
   ```
4. Your `.exe` will appear in the new `dist` folder:
   `dist\LoL_Skin_Exporter.exe`

That single `.exe` file is now self-contained — send *that* to your
friends. They don't need Python installed at all.

---

## Step 2 — What your friends do

1. Make sure League of Legends is open and they're logged in
2. Double-click `LoL_Skin_Exporter.exe`
3. A black window pops up, does its thing, and saves a file like
   `Faker#KR1_skins.json` in the same folder as the .exe
4. They send you that `.json` file (Discord, email, whatever)

That's it — no installs, no terminal commands, no typing required on
their end.

---

## Step 3 — Coordinate skins

Once you've collected everyone's `*_skins.json` files, open the
**LoL Skin Coordinator** (`skin_coordinator.html` — just double-click it,
it opens in any browser) and upload them all. It shows, per champion or
per skin line, who owns what, who has shards ready to craft, and who's
missing a skin entirely.

The **Theory Craft** tab lets you build a champion pool per player (the
champions they actually want to play) and shows matching-skin team
combinations, gaps, and flexibility across the group.

---

## Optional — auto-generate a champion pool with `generate_pool.py`

Typing out a champion pool by hand works fine, but if you'd rather seed
it from real play data, `generate_pool.py` builds one automatically from:

- Your top champion mastery (all-time)
- Your most-played champions (all-time, from recent ranked matches)
- Your most-played champions **this season**

This is a separate script from the skin exporter — it talks to Riot's
public developer API instead of your local client, so **it needs an API
key**:

1. Go to https://developer.riotgames.com and log in with your Riot account
2. Copy the "Development API Key" on your dashboard (starts with `RGAPI-`)
3. Run:
   ```
   python generate_pool.py
   ```
4. Paste the key when asked, along with your Riot ID and platform (na1, euw1, etc.)

It saves a `<name>_pool.json` file — import it directly using the
"Import pool from file" button next to your name in the Theory Craft tab.

A few things worth knowing:
- **Development API keys expire every 24 hours.** If the script fails
  with a 403 error, grab a fresh key from the same dashboard page.
- Scanning match history is intentionally slow (about 1.5 seconds per
  match) to stay under Riot's rate limits — scanning 60 matches takes
  roughly 1.5–2 minutes.
- The "this season" cutoff defaults to the current season's start date,
  but you can override it if you want a different window.

---

## Troubleshooting (for the .exe runner)

- **"Could not automatically find your League client"** — League isn't
  open, or it's installed somewhere unusual. They can paste the path
  to the `lockfile` file from their League of Legends install folder
  when prompted.
- **"Could not reach the League client"** — League is open but not
  fully logged in yet. Wait until they're at the home screen, then
  try again.
- Windows SmartScreen may warn about an "unrecognized app" since the
  .exe isn't signed — this is normal for small self-built tools. Click
  "More info" → "Run anyway."
