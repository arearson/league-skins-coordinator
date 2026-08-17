"""
League of Legends Champion Pool Generator
-------------------------------------------
Builds a champion pool file (compatible with the Skin Coordinator's
"Import pool from file" button) from your real Riot account data:

  - Top champion mastery (overall, all-time)
  - Most-played champions (all-time, based on recent ranked history)
  - Most-played champions THIS SEASON (filtered by a season start date)

Unlike export_skins.py, this does NOT talk to your local League client.
It talks to Riot's public developer API instead, which means you need a
free API key. Get one in about 2 minutes:

  1. Go to https://developer.riotgames.com
  2. Log in with your Riot account
  3. Copy the "Development API Key" shown on your dashboard
     (it's a string starting with RGAPI-...)
  4. Paste it in when this script asks for it

A development API key expires every 24 hours and has fairly low rate
limits (20 requests/sec, 100 requests/2min) — that's fine for one
person's pool but means this script deliberately paces its requests.

USAGE
-----
    python generate_pool.py

You'll be prompted for your API key, your Riot ID (the Name#TAG shown
in the client), your region, and how many champions to include from
each category. The result is saved as "<name>_pool.json", ready to
import directly into the Skin Coordinator.
"""

import json
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

# Platform routing values (where your account/summoner data lives) mapped to
# their regional routing values (used for match history + account lookup).
# https://developer.riotgames.com/docs/lol#routing-values
PLATFORM_TO_REGION = {
    "na1": "americas",
    "br1": "americas",
    "la1": "americas",
    "la2": "americas",
    "oc1": "americas",
    "euw1": "europe",
    "eun1": "europe",
    "tr1": "europe",
    "ru": "europe",
    "kr": "asia",
    "jp1": "asia",
    "ph2": "sea",
    "sg2": "sea",
    "th2": "sea",
    "tw2": "sea",
    "vn2": "sea",
}

# 2026 Season 1 started January 8, 2026. Riot doesn't expose season
# boundaries through the API, so this is a manually-maintained default —
# update it (or override with --season-start) once a new season begins.
DEFAULT_SEASON_START = "2026-01-08"

REQUEST_DELAY_SECONDS = 1.3  # stays comfortably under dev-key rate limits


def api_get(url, api_key):
    # req = urllib.request.Request(url, headers={"X-Riot-Token": api_key})
    new_url = url + f"?api_key={api_key}"
    req = urllib.request.Request(new_url)
    print(new_url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            # print(result)
            return result
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("  Rate limited, waiting 5 seconds and retrying...")
            time.sleep(5)
            return api_get(url, api_key)
        if e.code == 403:
            raise RuntimeError(
                "403 Forbidden — your API key is likely expired (dev keys last 24 hours). "
                "Get a fresh one from https://developer.riotgames.com"
            ) from e
        if e.code == 404:
            print("not found")
            return None
        raise RuntimeError(f"Riot API returned HTTP {e.code} for {url}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Couldn't reach Riot's API — check your internet connection."
        ) from e


def get_puuid(game_name, tag_line, region, api_key):
    url = (
        f"https://{region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/"
        f"{urllib.parse.quote(game_name)}/{urllib.parse.quote(tag_line)}"
    )
    "https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/hydrophantom/na1?api_key=RGAPI-5c1f4211-3092-437c-9b59-ca0db41afdaf"
    data = api_get(url, api_key)
    if not data:
        raise RuntimeError(f"Couldn't find a Riot account for {game_name}#{tag_line}")
    return data["puuid"]


def get_champion_id_to_name_map():
    """Data Dragon static champion data — no API key needed."""
    version_url = "https://ddragon.leagueoflegends.com/api/versions.json"
    with urllib.request.urlopen(version_url, timeout=15) as resp:
        versions = json.loads(resp.read().decode("utf-8"))
    latest = versions[0]
    champ_url = (
        f"https://ddragon.leagueoflegends.com/cdn/{latest}/data/en_US/champion.json"
    )
    with urllib.request.urlopen(champ_url, timeout=15) as resp:
        champ_data = json.loads(resp.read().decode("utf-8"))
    return {int(v["key"]): v["name"] for v in champ_data["data"].values()}


def get_top_mastery(puuid, platform, api_key, limit):
    url = f"https://{platform}.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}"
    data = api_get(url, api_key)
    if not data:
        return []
    # Already sorted by championPoints descending per Riot's API contract.
    return [entry["championId"] for entry in data[:limit]]


def get_match_ids(puuid, region, api_key, count, queue=None):
    params = {"start": 0, "count": min(count, 100)}
    if queue:
        params["queue"] = queue
    query = urllib.parse.urlencode(params)
    url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?{query}"
    data = api_get(url, api_key)
    return data or []


def get_match_champion_and_time(match_id, puuid, region, api_key):
    """Returns (championId, gameStartTimestampMs) for this player in this match."""
    url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    data = api_get(url, api_key)
    if not data:
        return None, None
    info = data.get("info", {})
    game_start = info.get("gameStartTimestamp") or info.get("gameCreation")
    for p in info.get("participants", []):
        if p.get("puuid") == puuid:
            return p.get("championId"), game_start
    return None, game_start


def most_played(champion_counts, limit):
    return [champ for champ, _ in champion_counts.most_common(limit)]


def main():
    print("=" * 62)
    print(" League of Legends Champion Pool Generator")
    print("=" * 62)
    print()
    print("This uses Riot's public API (not your local League client),")
    print("so you'll need a free developer API key.")
    print()

    api_key = input("Paste your Riot API key (starts with RGAPI-): ").strip()
    if not api_key:
        print("No API key entered. Get one at https://developer.riotgames.com")
        input("Press Enter to exit...")
        sys.exit(1)

    riot_id = input("Your Riot ID, as Name#TAG (e.g. Faker#KR1): ").strip()
    if "#" not in riot_id:
        print("That doesn't look like a Riot ID — it needs a # and tag, e.g. Faker#KR1")
        input("Press Enter to exit...")
        sys.exit(1)
    game_name, tag_line = riot_id.split("#", 1)

    print()
    print("Platform options:", ", ".join(sorted(PLATFORM_TO_REGION.keys())))
    platform = input("Your platform/server (e.g. na1, euw1, kr): ").strip().lower()
    if platform not in PLATFORM_TO_REGION:
        print(f"Unrecognized platform '{platform}'.")
        input("Press Enter to exit...")
        sys.exit(1)
    region = PLATFORM_TO_REGION[platform]

    season_start_str = (
        input(
            f"Season start date, YYYY-MM-DD [default {DEFAULT_SEASON_START}]: "
        ).strip()
        or DEFAULT_SEASON_START
    )
    try:
        season_start = datetime.strptime(season_start_str, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        print("Couldn't parse that date, using the default.")
        season_start = datetime.strptime(DEFAULT_SEASON_START, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    season_start_ms = int(season_start.timestamp() * 1000)

    def ask_int(prompt, default):
        raw = input(f"{prompt} [default {default}]: ").strip()
        return int(raw) if raw.isdigit() else default

    print()
    top_mastery_n = ask_int("How many top-mastery champions to include", 10)
    most_played_n = ask_int("How many most-played (all-time) champions to include", 10)
    most_played_season_n = ask_int(
        "How many most-played (this season) champions to include", 10
    )
    match_sample_size = ask_int(
        "How many recent ranked matches to scan for 'most played' stats (more = slower, ~1.5s each)",
        60,
    )

    print()
    print("Looking up your account...")
    try:
        puuid = get_puuid(game_name, tag_line, region, api_key)
    except RuntimeError as e:
        print(f"!! {e}")
        input("Press Enter to exit...")
        sys.exit(1)
    print(f"Found account for {game_name}#{tag_line}")

    print("Loading champion name reference data...")
    champ_names = get_champion_id_to_name_map()

    print(f"Fetching top {top_mastery_n} champion masteries...")
    mastery_ids = get_top_mastery(puuid, platform, api_key, top_mastery_n)
    time.sleep(REQUEST_DELAY_SECONDS)

    print(
        f"Fetching your last {match_sample_size} ranked matches (this takes a while, ~1-2 min)..."
    )
    match_ids = get_match_ids(
        puuid, region, api_key, match_sample_size, queue=420
    )  # 420 = ranked solo/duo
    time.sleep(REQUEST_DELAY_SECONDS)

    all_time_counts = Counter()
    season_counts = Counter()

    for i, match_id in enumerate(match_ids):
        champ_id, game_start_ms = get_match_champion_and_time(
            match_id, puuid, region, api_key
        )
        if champ_id:
            all_time_counts[champ_id] += 1
            if game_start_ms and game_start_ms >= season_start_ms:
                season_counts[champ_id] += 1
        if (i + 1) % 10 == 0:
            print(f"  ...scanned {i + 1}/{len(match_ids)} matches")
        time.sleep(REQUEST_DELAY_SECONDS)

    most_played_ids = most_played(all_time_counts, most_played_n)
    most_played_season_ids = most_played(season_counts, most_played_season_n)

    def to_names(ids):
        return [champ_names.get(cid, f"Champion {cid}") for cid in ids]

    mastery_names = to_names(mastery_ids)
    most_played_names = to_names(most_played_ids)
    most_played_season_names = to_names(most_played_season_ids)

    # Combined pool: union of all three lists, de-duplicated, alphabetical —
    # this is what actually gets imported into the Skin Coordinator.
    combined = sorted(
        set(mastery_names) | set(most_played_names) | set(most_played_season_names)
    )

    export = {
        "poolExportVersion": 1,
        "player": riot_id,
        "champions": combined,
        "sources": {
            "topMastery": mastery_names,
            "mostPlayedAllTime": most_played_names,
            "mostPlayedThisSeason": most_played_season_names,
        },
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "seasonStartUsed": season_start_str,
        "matchesScanned": len(match_ids),
    }

    safe_name = "".join(
        c for c in riot_id if c.isalnum() or c in ("-", "_", "#")
    ).rstrip()
    out_file = Path.cwd() / f"{safe_name}_pool.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 62)
    print(f"Done! Saved to: {out_file}")
    print(f"  Top mastery:          {', '.join(mastery_names) or '(none found)'}")
    print(f"  Most played all-time: {', '.join(most_played_names) or '(none found)'}")
    print(
        f"  Most played (season): {', '.join(most_played_season_names) or '(none found)'}"
    )
    print()
    print("Import this file using the 'Import pool from file' button")
    print("next to your name in the Skin Coordinator's Theory Craft tab.")
    print("=" * 62)
    input("\nPress Enter to close this window...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
    except Exception as e:
        print()
        print(f"!! Something went wrong: {e}")
        input("Press Enter to exit...")
        sys.exit(1)
