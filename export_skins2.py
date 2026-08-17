"""
League of Legends Skin & Loot Exporter
----------------------------------------
Reads the running League client's local lockfile to authenticate against
the LCU (League Client Update) API, then exports:
  - every skin you own (purchased, owned via loot redemption, etc.)
  - every skin shard / permanent sitting in your crafting (loot) inventory

Output: a single JSON file named "<summoner-name>_skins.json" written next
to this script (or next to the .exe if bundled), ready to share with friends
and upload to the coordination web tool.

This only ever talks to https://127.0.0.1:<port> - your own computer's
League client - it does not contact any third-party server.
"""

import json
import os
import sys
import base64
import ssl
import urllib.request
import urllib.error
from pathlib import Path


def find_lockfile():
    """Locate the League client's lockfile, which contains the local
    API port and auth token. Checks common install locations, then
    falls back to asking the user."""
    candidates = []

    # Common Windows install locations
    for env_var in ("PROGRAMDATA", "LOCALAPPDATA"):
        base = os.environ.get(env_var)
        if base:
            candidates.append(
                Path(base) / "Riot Games" / "League of Legends" / "lockfile"
            )

    candidates += [
        Path("C:/Riot Games/League of Legends/lockfile"),
        Path("D:/Riot Games/League of Legends/lockfile"),
        Path("E:/Riot Games/League of Legends/lockfile"),
        Path("F:/Riot Games/League of Legends/lockfile"),
        Path("C:/Program Files/Riot Games/League of Legends/lockfile"),
        Path("C:/Program Files (x86)/Riot Games/League of Legends/lockfile"),
    ]

    for path in candidates:
        if path.exists():
            return path

    return None


def read_lockfile(path: Path):
    """lockfile format: name:pid:port:password:protocol"""
    content = path.read_text(encoding="utf-8").strip()
    parts = content.split(":")
    if len(parts) != 5:
        raise ValueError(f"Unexpected lockfile format: {content}")
    _, _pid, port, password, protocol = parts
    return port, password, protocol


def build_opener(password: str):
    """Build an HTTPS opener that trusts the League client's
    self-signed local certificate and sends the Basic auth header."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    auth = base64.b64encode(f"riot:{password}".encode()).decode()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    opener.addheaders = [("Authorization", f"Basic {auth}")]
    return opener


def lcu_get(opener, port, endpoint):
    url = f"https://127.0.0.1:{port}{endpoint}"
    try:
        with opener.open(url, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except urllib.error.URLError as e:
        raise ConnectionError(
            "Could not reach the League client. Is it open and are you logged in?"
        ) from e


def get_summoner_name(opener, port):
    data = lcu_get(opener, port, "/lol-summoner/v1/current-summoner")
    if not data:
        return "UnknownSummoner"
    name = data.get("gameName") or data.get("displayName") or "UnknownSummoner"
    tag = data.get("tagLine")
    return f"{name}#{tag}" if tag else name


def get_champion_name_map(opener, port):
    """Map championId -> champion name, so output is human-readable."""
    champs = lcu_get(opener, port, "/lol-game-data/assets/v1/champion-summary.json")
    if not champs:
        return {}
    return {c["id"]: c.get("name", f"Champion {c['id']}") for c in champs if "id" in c}


def get_skin_line_map(opener, port):
    """Map skinLine id -> human name, e.g. 13 -> 'Dragonslayer'."""
    lines = lcu_get(opener, port, "/lol-game-data/assets/v1/skinlines.json")
    if not lines:
        return {}
    result = {}
    # Some client versions return a list, some a dict keyed by id
    if isinstance(lines, list):
        for entry in lines:
            lid = entry.get("id")
            if lid is not None:
                result[lid] = entry.get("name", f"Line {lid}")
    elif isinstance(lines, dict):
        for key, entry in lines.items():
            try:
                lid = int(entry.get("id", key))
            except (TypeError, ValueError):
                continue
            result[lid] = entry.get("name", f"Line {lid}")
    return result


def get_skin_catalog(opener, port, skin_line_names):
    """Full skin catalog: skinId -> {name, championId, skinLineNames}. Used to
    resolve both owned skins and crafting loot to readable names, figure out
    which champion a given skin shard belongs to, and group by skin line/set."""
    catalog = lcu_get(opener, port, "/lol-game-data/assets/v1/skins.json")
    if not catalog:
        return {}
    # catalog is a dict keyed by skin id (as string) in most client versions
    if isinstance(catalog, dict):
        result = {}
        for key, skin in catalog.items():
            try:
                skin_id = int(skin.get("id", key))
            except (TypeError, ValueError):
                continue
            line_ids = [
                l.get("id")
                for l in (skin.get("skinLines") or [])
                if l.get("id") is not None
            ]
            line_names = [skin_line_names.get(lid, f"Line {lid}") for lid in line_ids]
            result[skin_id] = {
                "name": skin.get("name", f"Skin {skin_id}"),
                "championId": skin_id
                // 1000,  # LoL convention: skinId = championId*1000 + n
                "skinLines": line_names,  # e.g. ["Star Guardian"], usually 0 or 1 entries
            }
        return result
    return {}


def get_owned_skins(opener, port, champ_names, skin_catalog):
    """Returns a list of dicts: {id, name, championId, championName, skinLines, chromas}"""
    user = lcu_get(opener, port, "/lol-summoner/v1/current-summoner")
    summoner_id = user.get("summonerId", None)
    # collection = lcu_get(opener, port, "/lol-collections/v1/inventories/skins")
    collection = lcu_get(
        opener, port, f"/lol-champions/v1/inventories/{summoner_id}/skins-minimal"
    )
    if collection is None:
        collection = []

    owned_skins = []
    for skin in collection:
        if skin.get("ownership", {}).get("owned"):
            champ_id = skin.get("championId")
            skin_id = skin.get("id")
            skin.update(
                lcu_get(
                    opener,
                    port,
                    f"/lol-champions/v1/inventories/{summoner_id}/champions/{champ_id}/skins/{skin_id}",
                )
            )
            catalog_entry = skin_catalog.get(skin_id, {})
            owned_skins.append(
                {
                    "id": skin_id,
                    "name": skin.get("name"),
                    "championId": champ_id,
                    "championName": champ_names.get(champ_id, f"Champion {champ_id}"),
                    "skinLines": catalog_entry.get(
                        "skinLines", []
                    ),  # e.g. ["Star Guardian"]
                    "chromas": [
                        {
                            "id": c.get("id"),
                            "name": c.get("name"),
                            "owned": c.get("ownership", {}).get("owned", False),
                        }
                        for c in skin.get("chromas", []) or []
                    ],
                }
            )

    return owned_skins


def get_crafting_loot(opener, port, champ_names, skin_catalog):
    """Returns skin shards / permanents currently sitting in loot
    (i.e. craftable / already-craftable-to-permanent items)."""
    loot = lcu_get(opener, port, "/lol-loot/v1/player-loot")
    if loot is None:
        return []

    craftable = []
    for item in loot:
        loot_id = item.get("lootId", "") or ""
        is_skin_loot = (
            loot_id.startswith("CHAMPION_SKIN")
            or loot_id.startswith("SKIN_")
            or item.get("type") in ("CHAMPION_SKIN", "STATSTONE_SKIN_UPGRADE")
        )
        if not is_skin_loot:
            continue

        # Try to pull the numeric skin id out of the loot id, e.g.
        # "CHAMPION_SKIN_RENTAL_103021" or "CHAMPION_SKIN_103021"
        skin_id = None
        digits = "".join(ch for ch in loot_id.split("_")[-1] if ch.isdigit())
        if digits:
            skin_id = int(digits)

        catalog_entry = skin_catalog.get(skin_id, {}) if skin_id else {}
        champ_id = catalog_entry.get("championId")
        readable_name = (
            item.get("localizedName")
            or catalog_entry.get("name")
            or item.get("displayName")
            or loot_id
        )

        craftable.append(
            {
                "lootId": loot_id,
                "skinId": skin_id,
                "skinName": readable_name,
                "championId": champ_id,
                "championName": (
                    champ_names.get(champ_id, "Unknown") if champ_id else "Unknown"
                ),
                "skinLines": catalog_entry.get(
                    "skinLines", []
                ),  # e.g. ["Star Guardian"]
                "count": item.get("count", 1),
                "itemStatus": item.get(
                    "itemStatus"
                ),  # e.g. "OWNED" / "LOCKED" / "UNLOCKED"
            }
        )

    return craftable


def main():
    print("=" * 60)
    print(" League of Legends Skin & Crafting Inventory Exporter")
    print("=" * 60)
    print()
    print("Looking for your League client...")

    lockfile = find_lockfile()
    if lockfile is None:
        print()
        print("!! Could not automatically find your League client.")
        manual = input(
            "Paste the full path to your 'lockfile' file "
            "(usually in your League of Legends install folder), or press Enter to quit: "
        ).strip()
        if not manual:
            input("Press Enter to exit...")
            sys.exit(1)
        lockfile = Path(manual)
        if not lockfile.exists():
            print(
                "That path doesn't exist. Make sure League of Legends is open, then try again."
            )
            input("Press Enter to exit...")
            sys.exit(1)

    try:
        port, password, protocol = read_lockfile(lockfile)
    except Exception as e:
        print(f"!! Couldn't read the lockfile: {e}")
        print(
            "Make sure League of Legends is fully open (not just the Riot Client) and try again."
        )
        input("Press Enter to exit...")
        sys.exit(1)

    opener = build_opener(password)

    print("Connecting to League client...")
    try:
        summoner_name = get_summoner_name(opener, port)
    except ConnectionError as e:
        print(f"!! {e}")
        input("Press Enter to exit...")
        sys.exit(1)

    print(f"Connected! Found summoner: {summoner_name}")
    print()
    print("Loading champion, skin, and skin-line reference data...")
    champ_names = get_champion_name_map(opener, port)
    skin_line_names = get_skin_line_map(opener, port)
    skin_catalog = get_skin_catalog(opener, port, skin_line_names)

    print("Reading your owned skins... (this can take a few seconds)")
    owned_skins = get_owned_skins(opener, port, champ_names, skin_catalog)
    print(f"  -> Found {len(owned_skins)} owned skins.")

    print("Reading your crafting / loot inventory...")
    craftable = get_crafting_loot(opener, port, champ_names, skin_catalog)
    print(f"  -> Found {len(craftable)} skin-related loot items.")

    export = {
        "exportVersion": 2,
        "summonerName": summoner_name,
        "ownedSkins": owned_skins,
        "craftingLoot": craftable,
    }

    # Save next to the script/exe, in a name that's safe for filenames
    safe_name = "".join(
        c for c in summoner_name if c.isalnum() or c in ("-", "_", "#")
    ).rstrip()
    out_file = Path(os.getcwd()) / f"{safe_name}_skins.json"

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 60)
    print(f"Done! Saved to: {out_file}")
    print("Send this file to whoever is coordinating skins,")
    print("or upload it to the skin-coordination web tool.")
    print("=" * 60)
    input("\nPress Enter to close this window...")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print()
        print(f"!! Something went wrong: {e}")
        print(
            "If this keeps happening, send this error message to whoever set this up for you."
        )
        input("Press Enter to exit...")
        sys.exit(1)
