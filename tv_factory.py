#!/usr/bin/env python3

from __future__ import annotations

import os
import sqlite3
import textwrap
import re
import hashlib
import sys
import html
import json
import urllib.request
import urllib.error
import requests # type: ignore
import time
import random
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

# =========================
# CONFIG (nur hier ändern)
# =========================
SERVER_IP          = "192.168.1.67"                
TIMEZONE           = "Europe/Vienna"

# ---- Ports / Names ----
IPTV_PORT          = 8081
VOD_PORT           = 8080

#Base URL ergibt sich aus SERVER IP
BASE_URL           = SERVER_IP

IPTV_NAME          = "iptv"          # nginx site name: /etc/nginx/sites-available/iptv
VOD_NAME           = "xstreamity"    # nginx site name: /etc/nginx/sites-available/xstreamity
BOUQUET_NAME       = "Home TV"       # NUR EIN Bouquet

# ---- Paths ----
PICONS_ROOT        = "/srv/media_hdd/picons"
PICONS_BASE_URL    = f"http://{SERVER_IP}:{IPTV_PORT}/picons"
IPTV_ROOT          = "/srv/media_hdd/hls"
VOD_ROOT           = "/var/www/xtream"

# --- xstreamity Zugang ---
VOD_USER           = "DeinUser"                    # Benutzernamen Erstellen
VOD_PASS           = "Password"                    # Password Erstellen

# --- Webroot & DB ---
VOD_WEBROOT        = Path("/var/www/xtream")
VOD_DB_DIR         = Path("/var/lib/xtream")
VOD_DB             = VOD_DB_DIR / "xtream.db"
BASE_URL           = f"http://{SERVER_IP}:{VOD_PORT}"
VOD_BASE_URL       = BASE_URL

# Debian/Ubuntu typisch (bei dir war es php8.2-fpm.sock)
PHP_FPM_SOCK       = "/run/php/php8.2-fpm.sock"

# Output-Ordner
BASE_HLS           = Path("/srv/media_hdd/hls")
BASE_STATE         = Path("/srv/media_hdd/state")
BASE_PLAY          = Path("/srv/media_hdd/playlists")

# Media-Roots (2 Platten)
MOVIES_ROOTS       = [Path("/srv/media_hdd/filme"),  Path("/srv/media_14tb/filme")]
MOVIE_ROOTS        = [Path("/srv/media_hdd/filme"),  Path("/srv/media_14tb/filme")]
SERIES_ROOTS       = [Path("/srv/media_hdd/serien"), Path("/srv/media_14tb/serien")]
X_MOVIE_ROOTS      = [Path("/srv/media_hdd/xstreamity/filme"),  Path("/srv/media_14tb/xstreamity/filme")]
X_SERIES_ROOTS     = [Path("/srv/media_hdd/xstreamity/serien"), Path("/srv/media_14tb/xstreamity/serien")]

# TMDB Für Scrapping von Serien & Movies
TMDB_API_KEY       = "dein-api-key"
TMDB_LANG          = "de-DE"
TMDB_IMAGE_BASE    = "https://image.tmdb.org/t/p/"

# Dateiendungen
EXT = {".mkv", ".mp4", ".avi", ".mov", ".m4v"}
VIDEO_EXT = {".mkv", ".mp4", ".ts", ".m4v", ".avi"}
VIDEO_EXTS = {".mkv", ".mp4", ".ts", ".m4v", ".avi"}

# Staffel-Erkennung (S01E02 oder 1x02)
YEAR_RE = re.compile(r"(19\d{2}|20\d{2})")
SXXEYY_RE = re.compile(r"(?:s(\d{1,2})e(\d{1,2}))", re.IGNORECASE)
SAFE_CHARS_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
CATEGORY = "Serien"

# Fallback falls ffprobe spinnt
FALLBACK_MIN = 22
DAYS_AHEAD   = 8

# Ordnernamen (Kanalnamen), die nach Jahr sortiert werden sollen
SORT_BY_YEAR_DIRS = {
    "Jurassic TV",
   # "Star Wars",
   # "Jaws",
}

# Shuffle-Channels: hier kannst du mehrere Mix-Kanäle definieren.
# Jeder Eintrag erzeugt EINEN Kanal, der Dateien aus bestimmten Ordnern mischt.
# - scope:  "movies" | "series" | "both"
# - recursive: bei Serien (Staffel-Unterordner) auf True setzen

SHUFFLES = [
    {
        "id": "moviesuhd",
        "name": "Movies UHD",
        "dir_names": {"Movies UHD", "movies uhd", "movies-uhd", "moviesuhd"},
        "scope": "movies",
        "recursive": False,
    },

    {
        "id": "imdbtop",
        "name": "IMDB Top",
        "dir_names": {"IMDB Top", "imdbtop", "IMDB-Top", "imdbtop"},
        "scope": "movies",
        "recursive": False,
    },

    {
        "id": "diesimpsons",
        "name": "Die Simpsons",
        "dir_names": {"Die Simpsons", "die simpsons", "Die-Simpsons", "diesimpsons"},
        "scope": "series",
        "recursive": True,
    },

    {
        "id": "americandad",
        "name": "American Dad",
        "dir_names": {"American Dad", "AmericanDad", "americandad", "American-Dad"},
        "scope": "series",
        "recursive": True,
    },

    {
        "id": "southpark",
        "name": "South Park",
        "dir_names": {"South Park", "south park", "South-Park", "southpark"},
        "scope": "series",
        "recursive": True,
    },

    {
        "id": "primetimehd",
        "name": "PrimeTime HD",
        "dir_names": {"PrimeTime HD", "primetime hd", "primetime-hd", "primetimehd"},
        "scope": "movies",
        "recursive": False,
    },

    # Beispiel für Serien-Shuffle:
    # {
    #     "id": "simpsons",
    #     "name": "Simpsons Shuffle",
    #     "dir_names": {"simpsons", "die simpsons"},
    #     "scope": "series",
    #     "recursive": True,
    # },
]

# Serien-Kanäle: am Anfang aus dem Dateinamen entfernen (Prefix)
# KEY = Ordnername / Kanalname (genau so wie der Ordner heißt)
# VALUE = Liste von Prefixen, die in den Dateinamen vorkommen können
SERIES_PREFIX_STRIP: dict[str, list[str]] = {
    "Die Simpsons": ["Die Simpsons", "The Simpsons:", "The Simpsons"],
    "The Wire": ["The Wire", "The Wire", "The Wire"],
    "Two and a half Men": ["Two and a Half Men", "Two and a Half Men", "Two and a half Men"],
    "The Pacific": ["The Pacific", "The Pacific", "The Pacific"],
    "King of Queens": ["King of Queens", "King of Queens", "King of Queens"],
    "Mocro Maffia": ["Mocro Maffia", "Mocro Maffia", "Mocro Maffia"],
    "South Park": ["South Park", "South Park:", "South Park"],
    "Hoer mal wer da haemmert": ["Hör mal wer da hämmert", "Hoer mal wer da haemmert", "Hör mal wer da hämmert"],
    "American Dad": ["American Dad", "American Dad", "American Dad"],
    "Band of Brothers": ["Band of Brothers", "Band of Brothers", "Band of Brothers"],
    "The Big Bang Theory": ["The Big Bang Theory", "The Big Bang Theory", "The Big Bang Theory"],
    "The Walking Dead": ["The Walking Dead", "The Walking Dead", "The Walking Dead"],
    "Young Sheldon": ["Young Sheldon", "Young Sheldon", "Young Sheldon"],
    "Narcos": ["Narcos", "Narcos", "Narcos"],
    "El Chapo": ["El Chapo", "El Chapo", "El Chapo"],
    "Gomorrha": ["Gomorrha", "Gomorrha", "Gomorrha"],
    "Breaking Bad": ["Breaking Bad", "Breaking Bad", "Breaking Bad"],
    "Der Prinz von Bel Air": ["Der Prinz von Bel Air", "Der Prinz von Bel Air", "Der Prinz von Bel-Air"],
    "Malcolm mittendrin": ["Malcolm mittendrin", "Malcolm mittendrin", "Malcolm mittendrin"],
    # Beispiele:
    # "Star Wars": ["Star Wars"],
    # "Jaws": ["Jaws", "Der weiße Hai"],
}

# Radio

RADIOS = [
    {
        "id": "mouv",
        "name": "Mouv Radio",
        "dir": Path("/srv/media_hdd/radio/mouv"),
        "logo": f"{PICONS_BASE_URL}/mouv.png",
        "background": Path("/srv/media_hdd/radio/mouv/mouv.jpg"),
        "url_txt": Path("/srv/media_hdd/radio/mouv/url.txt"),
        "epg_blocks": [
            (0, 1,   "Night Session",        "Sanfte Beats und ruhiger Hip-Hop für die späten Stunden"),
            (1, 2,   "After Midnight",       "Deep Cuts, Lo-Fi Rap und entspannte Night Vibes"),
            (2, 3,   "Dreamwave",            "Atmosphärische Sounds zwischen Trap und Chill-Hop"),
            (3, 4,   "Silent Streets",       "Langsame Beats für leere Straßen und klare Gedanken"),
            (4, 5,   "Early Mood",           "Sanfter Rap-Flow zum Start in den Morgen"),
            (5, 6,   "Sunrise Beats",        "Positive Tracks und warme Sounds zum Wachwerden"),
            (6, 7,   "Morning Flow",         "Fresh Rap Releases und motivierende Rhymes"),
            (7, 8,   "City Wake Up",         "Urban Sounds für den perfekten Tagesbeginn"),
            (8, 9,   "Daily Grind",          "Pushende Beats für Arbeit, Schule und unterwegs"),
            (9, 10,  "Street Rotation",      "Aktuelle Hip-Hop Hits im Dauerlauf"),
            (10,11,  "Urban Pulse",          "Moderne Rap-Tracks mit internationalem Vibe"),
            (11,12,  "Midday Bounce",        "Groovige Beats für die Mittagspause"),
            (12,13,  "Lunch Break Beats",    "Locker-flockiger Hip-Hop zum Abschalten"),
            (13,14,  "Afternoon Ride",       "Smooth Rap für entspannte Nachmittage"),
            (14,15,  "Flow Factory",         "Bars, Beats und neue Artists im Mix"),
            (15,16,  "Rush Hour Rhymes",     "Energetische Tracks für den Feierabendverkehr"),
            (16,17,  "Urban Energy",         "Trap, Drill und moderne Rap Sounds"),
            (17,18,  "City Drive",           "Perfekter Soundtrack für unterwegs"),
            (18,19,  "Evening Heat",         "Heiße Beats und starke Lines zum Abend"),
            (19,20,  "Prime Flow",           "Die größten Hip-Hop Tracks am Abend"),
            (20,21,  "Rap Spotlight",        "Highlights aus Oldschool und Newschool"),
            (21,22,  "Night Bounce",         "Basslastige Beats und Club-Vibes"),
            (22,23,  "Late Night Cypher",    "Skills, Bars und Underground Rap"),
            (23,24,  "Moonlight Beats",      "Ruhiger Ausklang mit atmosphärischem Hip-Hop")
        ],
    },
    {
        "id": "generationfm",
        "name": "Generation FM",
        "dir": Path("/srv/media_hdd/radio/generationfm"),
        "logo": f"{PICONS_BASE_URL}/generationfm.png",
        "background": Path("/srv/media_hdd/radio/generationfm/generationfm.jpg"),
        "url_txt": Path("/srv/media_hdd/radio/generationfm/url.txt"),
        "epg_blocks": [
            (0, 1,   "Dark Hour",            "Düstere Beats und kompromissloser Straßenrap"),
            (1, 2,   "Underground Mode",     "Raw Hip-Hop fernab vom Mainstream"),
            (2, 3,   "Night Riders",         "Trap Sounds für lange Nächte"),
            (3, 4,   "Concrete Dreams",      "Straßenpoesie und ehrliche Lyrics"),
            (4, 5,   "First Light Bars",     "Ruhiger Rap bevor die Stadt erwacht"),
            (5, 6,   "Wake & Hustle",        "Motivierende Tracks für Frühstarter"),
            (6, 7,   "Street Morning",       "Kraftvolle Beats zum Wachwerden"),
            (7, 8,   "Block Party AM",       "Oldschool trifft moderne Rap Vibes"),
            (8, 9,   "Hustle Time",          "Tracks für Fokus und Motivation"),
            (9, 10,  "Kings Rotation",       "Die stärksten Rap-Tracks im Dauerplay"),
            (10,11,  "Mic Check",            "Skills, Punchlines und echte MCs"),
            (11,12,  "Beat District",        "Fette Produktionen und harte Drums"),
            (12,13,  "Noon Cypher",          "Rap pur – Bars stehen im Mittelpunkt"),
            (13,14,  "Street Stories",       "Storytelling Rap mit Charakter"),
            (14,15,  "Trap Avenue",          "808s, Hi-Hats und moderner Trap"),
            (15,16,  "Power Hour",           "High-Energy Rap für den Nachmittag"),
            (16,17,  "Block Energy",         "Aggressive Beats und Straßenflow"),
            (17,18,  "Drive By Beats",       "Basslastiger Sound fürs Autofahren"),
            (18,19,  "Concrete Heat",        "Druckvolle Tracks zum Feierabend"),
            (19,20,  "Kings Prime",          "Die größten Banger des Tages"),
            (20,21,  "Battle Mode",          "Punchlines, Diss-Vibes und Rap-Energie"),
            (21,22,  "Trap Kingdom",         "Moderne Club- und Trap-Hits"),
            (22,23,  "Last Round",           "Intensive Rap Tracks zum Tagesende"),
            (23,24,  "Street Flow",          "Ruhiger Abschluss mit deepen Sounds")
        ],
    },
]

# =========================
# END CONFIG
# =========================

@dataclass
class Channel:
    id: str
    name: str
    kind: str  # "video" | "shuffle" | "radio"
    logo: Optional[Path] = None
    background: Optional[Path] = None
    # video
    files: Optional[List[Path]] = None
    # radio
    radio_url: Optional[str] = None

def extract_year(p: Path) -> int:
    m = YEAR_RE.search(p.name)
    return int(m.group(1)) if m else 9999

def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def die(msg: str, code: int = 1) -> None:
    print(f"[FAIL] {msg}")
    raise SystemExit(code)


def is_root() -> bool:
    return os.geteuid() == 0


def which(bin_name: str) -> bool:
    return shutil.which(bin_name) is not None

def ok(msg: str) -> None:
    print(f"[OK] {msg}")


def skip(msg: str) -> None:
    print(f"[SKIP] {msg}")


def info(msg: str) -> None:
    print(f"[INFO] {msg}")


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def get_last_run_seconds(file_path: Path, channel_id: str) -> int | None:
    log = Path(f"/var/log/ffmpeg_{channel_id}.log")
    if not log.exists():
        return None

    needle = f"file={str(file_path)}"
    last = None
    for line in log.read_text(errors="ignore").splitlines():
        if "END" in line and needle in line:
            m = re.search(r"ran=(\d+)", line)
            if m:
                last = int(m.group(1))
    return last

def clean_title(s: str) -> str:
    s = re.sub(r"\.(mkv|mp4|avi|m4v)$", "", s, flags=re.I)
    s = re.sub(r"\((19|20)\d{2}\)", "", s)
    s = re.sub(r"\b(720p|1080p|2160p|x264|x265|bluray|web|webrip|hdrip|dv|hdr|ac3|dts)\b", "", s, flags=re.I)
    s = re.sub(r"[._]", " ", s)
    return " ".join(s.split()).strip()

def extract_tmdb_id(name: str):
    m = re.search(r"\{tmdb-(\d+)\}", name, re.IGNORECASE)
    return m.group(1) if m else None

def strip_tmdb_tag(name: str):
    return re.sub(r"\{tmdb-\d+\}", "", name, flags=re.IGNORECASE).strip()

def fetch_tmdb_trailer(tmdb_id: int, kind: str = "movie") -> str:
    """
    Holt den Trailer-Key von TMDB und gibt YouTube URL zurück.
    kind: "movie" oder "tv"
    Priorisiert: 1. Offizieller Trailer (de), 2. Beliebiger Trailer (de), 3. Beliebiger Trailer (en)
    """
    try:
        endpoint = f"https://api.themoviedb.org/3/{kind}/{tmdb_id}/videos"
        params = {"api_key": TMDB_API_KEY, "language": TMDB_LANG}  # z.B. de-DE

        data = requests.get(endpoint, params=params, timeout=10).json()
        results = data.get("results", [])

        if not results:
            # Fallback auf Englisch wenn keine deutschen Videos
            params["language"] = "en-US"
            data = requests.get(endpoint, params=params, timeout=10).json()
            results = data.get("results", [])

        # Priorisierung: offizieller Trailer > Trailer > Teaser > Featurette
        priority = {"Trailer": 1, "Teaser": 2, "Featurette": 3, "Clip": 4}

        # Sortiere nach Priorität und offiziell-Status
        sorted_videos = sorted(
            results,
            key=lambda x: (
                0 if x.get("official") else 1,  # Offizielle zuerst
                priority.get(x.get("type", ""), 99),  # Dann nach Typ
                x.get("published_at", "")  # Neueste zuerst
            )
        )

        if sorted_videos:
            key = sorted_videos[0].get("key", "")
            site = sorted_videos[0].get("site", "YouTube")

            if site == "YouTube" and key:
                return key
            elif site == "Vimeo" and key:
                return f"https://vimeo.com/{key}"

        return ""
    except Exception:
        return ""

def fetch_tmdb_credits(tmdb_id: int, kind: str = "movie") -> str:
    """
    Holt Cast mit Bildern als JSON-String.
    Returns: JSON-Array mit name, profile_path, character, id
    """
    try:
        endpoint = f"https://api.themoviedb.org/3/{kind}/{tmdb_id}/credits"
        params = {"api_key": TMDB_API_KEY, "language": TMDB_LANG}
        data = requests.get(endpoint, params=params, timeout=10).json()

        cast_list = data.get("cast", [])
        result = []

        for actor in cast_list[:10]:
            profile_path = actor.get("profile_path")
            image_url = ""
            if profile_path:
                image_url = f"https://image.tmdb.org/t/p/w500{profile_path}"

            result.append({
                "id": actor.get("id"),
                "name": actor.get("name", ""),
                "character": actor.get("character") or "",
                "profile_path": image_url
            })

        return json.dumps(result, ensure_ascii=False)
    except Exception:
        return json.dumps([])

def fetch_tmdb(title: str, year: str | None = None):
    try:
        url = "https://api.themoviedb.org/3/search/movie"
        params = {"api_key": TMDB_API_KEY, "query": title, "language": TMDB_LANG}
        if year:
            params["year"] = year
        data = requests.get(url, params=params, timeout=10).json()
        if not data.get("results"):
            return None
        m = data["results"][0]
        tmdb_id = m.get("id")
        kinopoisk_url = f"https://www.themoviedb.org/movie/{tmdb_id}"
        original_title = m.get("original_title", "") or ""

        detail = requests.get(
            f"https://api.themoviedb.org/3/movie/{tmdb_id}",
            params={"api_key": TMDB_API_KEY, "language": TMDB_LANG},
            timeout=10
        ).json()

        credits = requests.get(
            f"https://api.themoviedb.org/3/movie/{tmdb_id}/credits",
            params={"api_key": TMDB_API_KEY, "language": TMDB_LANG},
            timeout=10
        ).json()

        director = ""
        for person in credits.get("crew", []):
            if person.get("job") == "Director":
                director = person.get("name", "") or ""
                break

        genres = ", ".join(
            g.get("name", "") for g in detail.get("genres", []) if g.get("name")
        )

        countries = ", ".join(
            c.get("name", "") for c in detail.get("production_countries", []) if c.get("name")
        )

        # Cast holen (wenn du es noch nicht hast)
        cast = fetch_tmdb_credits(tmdb_id, "movie")
        # Trailer holen
        trailer = fetch_tmdb_trailer(tmdb_id, "movie")

        return {
            "tmdb_id": tmdb_id,
            "poster": (TMDB_IMAGE_BASE + "w500" + m["poster_path"]) if m.get("poster_path") else "",
            "backdrop": (TMDB_IMAGE_BASE + "w780" + m["backdrop_path"]) if m.get("backdrop_path") else "",
            "plot": m.get("overview", "") or "",
            "rating": str(m.get("vote_average", "") or ""),
            "release_date": m.get("release_date", "") or "",
            "cast": cast,
            "trailer": trailer,
            "director": director,
            "genre": genres,
            "country": countries,
            "o_name": original_title,
            "kinopoisk_url": kinopoisk_url,
        }
    except Exception:
        return None

def fetch_tmdb_tv(name: str):
    try:
        url = "https://api.themoviedb.org/3/search/tv"
        params = {"api_key": TMDB_API_KEY, "query": name, "language": TMDB_LANG}
        data = requests.get(url, params=params, timeout=10).json()
        if not data.get("results"):
            return None
        m = data["results"][0]
        tmdb_id = m.get("id")
        kinopoisk_url = f"https://www.themoviedb.org/tv/{tmdb_id}"
        original_name = m.get("original_name", "") or ""

        detail = requests.get(
            f"https://api.themoviedb.org/3/tv/{tmdb_id}",
            params={"api_key": TMDB_API_KEY, "language": TMDB_LANG},
            timeout=10
        ).json()

        credits = requests.get(
            f"https://api.themoviedb.org/3/tv/{tmdb_id}/credits",
            params={"api_key": TMDB_API_KEY, "language": TMDB_LANG},
            timeout=10
        ).json()

        director = ""
        creators = detail.get("created_by", []) or []
        if creators:
            director = creators[0].get("name", "") or ""
        else:
            for person in credits.get("crew", []):
                if person.get("job") in ("Executive Producer", "Director"):
                    director = person.get("name", "") or ""
                    break

        genres = ", ".join(
            g.get("name", "") for g in detail.get("genres", []) if g.get("name")
        )

        countries = ", ".join(detail.get("origin_country", []) or [])

        # Cast holen (wenn du es noch nicht hast)
        cast = fetch_tmdb_credits(tmdb_id, "tv")
        # Trailer holen
        trailer = fetch_tmdb_trailer(tmdb_id, "tv")

        return {
            "tmdb_id": tmdb_id,
            "poster": ("https://image.tmdb.org/t/p/w500" + m["poster_path"]) if m.get("poster_path") else "",
            "backdrop": ("https://image.tmdb.org/t/p/w780" + m["backdrop_path"]) if m.get("backdrop_path") else "",
            "plot": m.get("overview", "") or "",
            "rating": str(m.get("vote_average", "") or ""),
            "release_date": m.get("first_air_date", "") or "",
            "cast": cast,
            "trailer": trailer,
            "director": director,
            "genre": genres,
            "country": countries,
            "o_name": original_name,
            "kinopoisk_url": kinopoisk_url,
        }
    except Exception:
        return None

def fetch_tmdb_episode(tmdb_id: int, season: int, episode: int):
    try:
        # 1) Episode-Basisdaten
        url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season}/episode/{episode}"
        params = {"api_key": TMDB_API_KEY, "language": TMDB_LANG}
        data = requests.get(url, params=params, timeout=10).json()

        # 2) Credits extra holen
        credits_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season}/episode/{episode}/credits"
        credits = requests.get(credits_url, params=params, timeout=10).json()

        crew_names = []
        for item in credits.get("crew", []):
            name = str(item.get("name", "")).strip()
            if name and name not in crew_names:
                crew_names.append(name)

        crew_string = ", ".join(crew_names[:5])

        return {
            "title": data.get("name", "") or "",
            "plot": data.get("overview", "") or "",
            "air_date": data.get("air_date", "") or "",
            "crew": crew_string,
        }
    except Exception:
        return None

def strip_series_prefix(title: str, prefixes: list[str]) -> str:
    t = title.strip()
    if not prefixes:
        return t

    for p in prefixes:
        p = p.strip()
        if not p:
            continue

        # Match: "Prefix - ..." oder "Prefix_..." oder "Prefix...."
        # (case-insensitive, toleriert verschiedene Trenner)
        pat = re.compile(rf"^\s*{re.escape(p)}\s*[-–—._ ]+\s*", re.IGNORECASE)
        new = pat.sub("", t)
        if new != t:
            return new.strip()

    return t

def write_text_if_changed(path: Path, content: str, label: str) -> None:
    ensure_dir(path.parent)
    if path.exists():
        old = path.read_text(errors="ignore")
        if sha256_text(old) == sha256_text(content):
            skip(f"{label} unchanged: {path}")
            return
        path.write_text(content)
        ok(f"{label} updated: {path}")
        return
    path.write_text(content)
    ok(f"{label} written: {path}")


def apt_install(pkgs):
    if not have("apt-get"):
        print("!! apt-get nicht vorhanden – überspringe Install")
        return
    run(["apt-get","update"], check=False)
    run(["apt-get","install","-y"] + pkgs, check=False)


def ensure_php_fpm():
    # nginx + php-fpm + sqlite
    print("[SETUP] Pakete prüfen/installieren …")
    apt_install(["nginx", "php-fpm", "php-sqlite3"])


def ensure_symlink(dst: Path, src: Path, label: str) -> None:
    if dst.is_symlink() and dst.resolve() == src.resolve():
        print(f"[SYMLINK] {label} ok -> {dst} -> {src}")
        return
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    dst.symlink_to(src)
    print(f"[SYMLINK] {label} erstellt -> {dst} -> {src}")

def which(bin_name: str) -> bool:
    return shutil.which(bin_name) is not None


def die(msg: str) -> None:
    print(f"[FACTORY] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], check: bool = True, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=text, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def ensure_dirs():
    run(["mkdir","-p", str(VOD_WEBROOT)], check=False)
    run(["mkdir","-p", str(VOD_DB.parent)], check=False)


def ensure_dir(p: Path, mode: int = 0o775) -> None:
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, mode)
    except Exception:
        pass


def slugify(s: str) -> str:
    s = s.strip().lower()
    s = SAFE_CHARS_RE.sub("", s.replace(" ", ""))
    return s or "channel"


def natural_key(path: Path) -> Tuple:
    """Sort key: tries SxxEyy, otherwise fallback to name."""
    name = path.name.lower()
    m = SXXEYY_RE.search(name)
    if m:
        s = int(m.group(1))
        e = int(m.group(2))
        return (0, s, e, name)
    return (1, 0, 0, name)


def ffprobe_duration_seconds(f: Path) -> int:
    try:
        cp = run([
            "/usr/bin/ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nk=1:nw=1",
            str(f)
        ], check=True)
        val = (cp.stdout or "").strip()
        if not val:
            raise ValueError("empty duration")
        dur = int(float(val))
        # sanity
        if dur < 300:
            return FALLBACK_MIN * 60
        return dur
    except Exception:
        return FALLBACK_MIN * 60


def write_text(path: Path, content: str, mode: int = 0o644) -> None:
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")
    try:
        os.chmod(path, mode)
    except Exception:
        pass


def read_url(url_txt: Path) -> str:
    if not url_txt.exists():
        die(f"Radio url.txt fehlt: {url_txt}")
    url = url_txt.read_text(encoding="utf-8").strip()
    if not url:
        die(f"Radio url.txt ist leer: {url_txt}")
    return url


def find_media_dirs(roots: List[Path]) -> List[Path]:
    out: List[Path] = []
    for r in roots:
        if not r.exists():
            continue
        for p in r.iterdir():
            if p.is_dir():
                out.append(p)
    return out


def collect_videos_in_dir(d: Path) -> List[Path]:
    files: List[Path] = []
    for p in d.rglob("*"):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            files.append(p)
    files.sort(key=natural_key)
    return files


def detect_logo_in_dir(d: Path) -> Optional[Path]:
    for cand in ["poster.jpg", "folder.jpg", "logo.jpg", "cover.jpg"]:
        p = d / cand
        if p.exists():
            return p
    return None


def write_video_list_file(cid: str, files: List[Path]) -> Path:
    ensure_dir(BASE_STATE)
    lf = BASE_STATE / f"{cid}_files.txt"
    # absolute paths – runner liest direkt
    content = "\n".join(str(p) for p in files) + "\n"
    write_text(lf, content)
    return lf


def write_shuffle_list_file(cid: str, files: List[Path]) -> Path:
    # shuffle JEDEN factory-start
    files2 = files[:]
    random.shuffle(files2)
    return write_video_list_file(cid, files2)


def write_radio_runner(ch: Channel) -> Path:
    ensure_dir(Path("/usr/local/bin"))
    runner = Path(f"/usr/local/bin/iptv-{ch.id}.sh")

    outdir = BASE_HLS
    img = ch.background
    url = (ch.radio_url or "").strip()

    if isinstance(img, Path) and not img.exists():
        img = None
    if not url:
        die(f"Radio URL fehlt für {ch.id}")

    script = f"""#!/bin/bash
set -euo pipefail

OUTDIR="{outdir}"
IMG="{img.as_posix() if img else ''}"
URL="{url}"

mkdir -p "$OUTDIR"

# wait for url (optional)
while [ -z "$URL" ]; do
  sleep 2
done

exec /usr/bin/ffmpeg -hide_banner -loglevel quiet -re \\
  -loop 1 -framerate 1 -i "$IMG" \\
  -i "$URL" \\
  -c:v libx264 -preset ultrafast -tune stillimage -pix_fmt yuv420p -vf scale=1280:720 \\
  -r 1 -g 1 \\
  -c:a copy \\
  -hls_base_url "http://{SERVER_IP}:{IPTV_PORT}/" \\
  -f hls -hls_time 6 -hls_list_size 10 \\
  -hls_flags delete_segments+append_list+omit_endlist \\
  "$OUTDIR/{ch.id}.m3u8"
"""
    write_text(runner, script)
    os.chmod(runner, 0o755)
    return runner

def write_video_runner(ch: Channel, list_file: Path) -> Path:
    ensure_dir(Path("/usr/local/bin"))
    runner = Path(f"/usr/local/bin/iptv-{ch.id}.sh")

    outdir = BASE_HLS
    files_var = str(list_file)

    # Dein gewünschter Video-Block (ffprobe duration, ffmpeg copy/aac, m3u8 im HLS)
    script = f"""#!/bin/bash
set -e

CHANNEL_ID="{ch.id}"
OUTDIR="{outdir}"
FILES="{files_var}"
FALLBACK_MIN={FALLBACK_MIN}

mkdir -p "$OUTDIR"

last_file=""
last_dur=""

i=0
while true; do
  mapfile -t list < "$FILES"
  count=${{#list[@]}}
  if [ $count -eq 0 ]; then sleep 5; continue; fi

  file="${{list[$((i % count))]}}"

  if [ "$file" != "$last_file" ]; then
    last_file="$file"
    last_dur=$(/usr/bin/ffprobe -v error -show_entries format=duration \
       -of default=noprint_wrappers=1:nokey=1 "$file" 2>/dev/null)
    last_dur=${{last_dur%.*}}
  fi

  dur="$last_dur"

  start=$(date +%s)
  echo "{{\\"file\\":\\"$file\\",\\"start\\":$start,\\"duration\\":$dur}}" > "{BASE_STATE}/{ch.id}.json"


   # ---- START LOG ----
   echo "START file=$file expected=${{dur}}s at=$(date '+%F %T')" >> "/var/log/ffmpeg_${{CHANNEL_ID}}.log"

/usr/bin/ffmpeg -hide_banner -loglevel quiet \\
    -re -fflags +genpts -i "$file" \\
    -map 0:v:0 -map 0:a:0 \\
    -c:v copy \\
    -c:a aac -ac 2 -b:a 192k -af aresample=async=1 \\
    -f hls \\
    -hls_time 6 \\
    -hls_list_size 8 \\
    -hls_flags delete_segments+append_list+omit_endlist \\
    -force_key_frames "expr:gte(t,n_forced*6)" \\
    -hls_segment_filename "$OUTDIR/${{CHANNEL_ID}}_%05d.ts" \\
    -t "$dur" \\
    "$OUTDIR/${{CHANNEL_ID}}.m3u8"
    >> /var/log/ffmpeg_${{CHANNEL_ID}}.log 2>&1

   # ---- END LOG ----
   end=$(date +%s)
   run=$((end-start))

   echo "END   file=${{file}} ran=${{run}}s expected=${{dur}}s diff=$((dur-run))s at=$(date '+%F %T')" >> "/var/log/ffmpeg_${{CHANNEL_ID}}.log"

   # ---- EARLY ABORT CHECK ----
   [ "${{run}}" -lt $((dur-120)) ] && \
   echo "⚠ EARLY_ABORT ${{file}}" >> "/var/log/ffmpeg_${{CHANNEL_ID}}.log"

  i=$((i+1))
done
"""
    write_text(runner, script)
    os.chmod(runner, 0o755)
    return runner

def write_service(channel_id: str, name: str, script_path: Path) -> Path:
    svc = Path(f"/etc/systemd/system/iptv-{channel_id}.service")
    unit = f"""[Unit]
Description={name} TV
After=network-online.target nginx.service
Wants=network-online.target

[Service]
Type=simple
ExecStart={script_path}
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
"""
    write_text(svc, unit)
    return svc

def enable_service(channel_id: str) -> None:
    svc = f"iptv-{channel_id}.service"

    subprocess.run(["systemctl", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "enable", svc], check=False)
    subprocess.run(["systemctl", "start", svc], check=False)

def stream_url(cid: str) -> str:
    return f"http://{SERVER_IP}:{IPTV_PORT}/{cid}.m3u8"


def write_m3u(channels: List[Channel]) -> Path:
    out = BASE_HLS / "iptv.m3u"
    lines = ["#EXTM3U"]
    for ch in channels:
        logo = str(ch.logo) if ch.logo else f"{PICONS_BASE_URL}/{ch.id}.png"
        # TVG-ID ist channel_id
        lines.append(
            f'#EXTINF:-1 tvg-id="{ch.id}" tvg-name="{ch.name}" tvg-logo="{logo}" group-title="{BOUQUET_NAME}"'
        )
        lines.append(stream_url(ch.id))
    write_text(out, "\n".join(lines) + "\n")
    return out

def write_m3u_with_auth(channels: List[Channel]) -> Path:
    """
    Erstellt eine M3U die über player_api.php authentifiziert wird
    """
    out = BASE_HLS / "iptv_auth.m3u"
    lines = ["#EXTM3U"]

    # EPG URL in der ersten Zeile
    epg_url = f"http://{SERVER_IP}:{VOD_PORT}/xmltv.php"
    lines[0] += f' url-tvg="{epg_url}" x-tvg-url="{epg_url}"'

    # Xtream Codes Format mit Auth
    base_url = f"http://{SERVER_IP}:{VOD_PORT}"

    for ch in channels:
        # Logo immer gleich behandeln
        logo = str(ch.logo) if ch.logo else f"{PICONS_BASE_URL}/{ch.id}.png"

        # ALLES in EINER Gruppe - Radio UND Video
        lines.append(
            f'#EXTINF:-1 tvg-id="{ch.id}" tvg-name="{ch.name}" tvg-logo="{logo}" group-title="{BOUQUET_NAME}",{ch.name}'
        )
        lines.append(f"{base_url}/live/{VOD_USER}/{VOD_PASS}/{ch.id}.m3u8")

    write_text(out, "\n".join(lines) + "\n")
    return out

def xmltv_time(dt: datetime) -> str:
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(TIMEZONE)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    else:
        dt = dt.astimezone(tz)

    return dt.strftime("%Y%m%d%H%M%S %z")

def epg_channel_block(ch: Channel) -> str:
    return f'<channel id="{html.escape(ch.id)}"><display-name>{html.escape(ch.name)}</display-name></channel>'


def build_epg_for_radio(radio: dict, now: datetime, end: datetime) -> List[str]:
    out: List[str] = []
    cid = radio["id"]
    blocks = radio["epg_blocks"]

    d = now.replace(minute=0, second=0, microsecond=0)
    while d < end:
        # same day blocks
        for h1, h2, title, desc in blocks:
            start = d.replace(hour=h1, minute=0, second=0, microsecond=0)
            stop  = d.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1) if h2 == 24 else d.replace(hour=h2, minute=0, second=0, microsecond=0)
            if stop <= now:
                continue
            if start < now:
                start = now
            if start >= end:
                break
            if stop > end:
                stop = end
            out.append(
                f'<programme start="{xmltv_time(start)}" stop="{xmltv_time(stop)}" channel="{html.escape(cid)}">'
                f'<title>{html.escape(title)}</title><desc>{html.escape(desc)}</desc></programme>'
            )
        d = (d.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
    return out

# ============================================================================
# PERFEKTER EPG - NULL DRIFT - AUS Log-DATEIEN Oder FFPROBE Oder FALLBACK
# ============================================================================

def get_epg_desc_for_file(ch: Channel, f: Path) -> str:
    try:
        con = sqlite3.connect(VOD_DB)
        cur = con.cursor()

        # erst Episode
        cur.execute("SELECT plot FROM episodes WHERE path=? LIMIT 1", (str(f),))
        row = cur.fetchone()
        if row and row[0]:
            con.close()
            return str(row[0])

        # dann Film
        cur.execute("SELECT plot FROM vod WHERE path=? LIMIT 1", (str(f),))
        row = cur.fetchone()
        if row and row[0]:
            con.close()
            return str(row[0])

        # dann Serienplot über Kanalname
        cur.execute("SELECT plot FROM series WHERE name=? LIMIT 1", (ch.name,))
        row = cur.fetchone()
        if row and row[0]:
            con.close()
            return str(row[0])

        con.close()
    except Exception:
        pass

    return f.stem

def build_epg_for_video_channel(ch: Channel, list_file: Path, now: datetime, end: datetime) -> List[str]:
    # liest die selbe Liste, die der Runner nutzt (shuffle ist damit korrekt)
    files = [Path(x.strip()) for x in list_file.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not files:
        return []

    out: List[str] = []
    state_file = BASE_STATE / f"{ch.id}.json"
    if state_file.exists():
       with open(state_file) as f:
            data = json.load(f)

    current_file = Path(data["file"])
    start_ts = data["start"]  # Unix-Timestamp des Sendestarts
    duration = data["duration"]  # EPG-Dauer in Sekunden
    current_time = int(time.time())
    elapsed = current_time - start_ts

    t = now.replace(second=0, microsecond=0)
    if now.second > 30:
        t = t + timedelta(minutes=1)
    info(f"EPG für {ch.id}: '{current_file.name}' läuft seit {elapsed}s von {duration}s")
    idx = 0
    while t < end:
        f = files[idx % len(files)]
        dur = get_last_run_seconds(f, ch.id) or ffprobe_duration_seconds(f)
        stop = t + timedelta(seconds=dur)
        if stop > end:
            stop = end

        # title aus dateiname
        raw_title = clean_title(strip_tmdb_tag(f.stem))
        title = re.sub(r"\s*\(\d{4}\)\s*$", "", raw_title).strip()

        # Nur bei Serien-Kanälen prefix entfernen
        prefixes = SERIES_PREFIX_STRIP.get(ch.name, [])  # ch.name ist Ordnername/Displayname
        title = strip_series_prefix(title, prefixes)
        # SxxEyy ans Ende verschieben
        m = re.search(r'(S\d{2}E\d{2})', title, re.IGNORECASE)
        if m:
            ep = m.group(1)
            rest = title.replace(ep, '').strip(" -._")
            title = f"{rest} - {ep}" if rest else ep

        desc = get_epg_desc_for_file(ch, f)

        out.append(
            f'<programme start="{xmltv_time(t)}" stop="{xmltv_time(stop)}" channel="{html.escape(ch.id)}">'
            f'<title>{html.escape(title)}</title>'
            f'<desc>{html.escape(desc)}</desc>'
            f'</programme>'
        )

        t = stop
        idx += 1
    return out

def write_epg(channels: List[Channel], list_files: dict) -> Path:
    out = BASE_HLS / "epg_all.xml"

    now = datetime.now()  # local
    end = now + timedelta(days=DAYS_AHEAD)

    ch_blocks = []
    prog_blocks = []

    for ch in channels:
        ch_blocks.append(epg_channel_block(ch))

    # radio epg aus config
    radio_map = {r["id"]: r for r in RADIOS}
    for ch in channels:
        if ch.kind == "radio":
            prog_blocks.extend(build_epg_for_radio(radio_map[ch.id], now, end))
        else:
            lf = list_files.get(ch.id)
            if lf:
                prog_blocks.extend(build_epg_for_video_channel(ch, lf, now, end))

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<tv>\n'
        + "\n".join(ch_blocks) + "\n"
        + "\n".join(prog_blocks) + "\n"
        + "</tv>\n"
    )
    write_text(out, xml)
    return out

def match_any(d: Path, names: set[str]) -> bool:
    return d.name.strip().lower() in {x.lower() for x in names}

def is_shuffle_source_dir(d: Path) -> bool:
    # true if directory name matches ANY configured shuffle source name
    for cfg in SHUFFLES:
        names = cfg.get("dir_names", set())
        if names and match_any(d, set(names)):
            return True
    return False

def collect_videos_recursive(root: Path) -> List[Path]:
    vids: List[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            vids.append(p)
    return vids

def ensure_system_deps() -> None:
    """
    Installiert nur, wenn ein Tool fehlt.
    """
    need_install = False
    packages: list[str] = []

    # ffmpeg / ffprobe
    if not have("ffmpeg") or not have("ffprobe"):
        print("[DEPS] ffmpeg/ffprobe fehlt -> wird installiert")
        packages.append("ffmpeg")
        need_install = True
    else:
        print("[DEPS] ffmpeg/ffprobe: vorhanden")

    # nginx
    if not have("nginx"):
        print("[DEPS] nginx fehlt -> wird installiert")
        packages.append("nginx")
        need_install = True
    else:
        print("[DEPS] nginx: vorhanden")

    # php-fpm (für xstreamity / xtream web root)
    # (php-fpm binary kann je nach distro anders heißen, daher paket-basiert)
    if not shutil.which("php-fpm") and not shutil.which("php8.2-fpm") and not shutil.which("php8.1-fpm"):
        print("[DEPS] php-fpm fehlt -> wird installiert")
        packages += ["php-fpm"]
        need_install = True
    else:
        print("[DEPS] php-fpm: vorhanden (binary gefunden)")

    # php sqlite extension + sqlite3 cli
    php_sqlite_ok = False
    try:
        modcheck = subprocess.run(
            ["php", "-m"],
            capture_output=True,
            text=True,
            check=False
        )
        mods = modcheck.stdout.lower()
        php_sqlite_ok = ("pdo_sqlite" in mods) or ("sqlite3" in mods)
    except Exception:
        php_sqlite_ok = False

    if not php_sqlite_ok:
        print("[DEPS] php8.2-sqlite3/sqlite3 fehlt -> wird installiert")
        packages += ["php8.2-sqlite3", "sqlite3"]
        need_install = True
    else:
        print("[DEPS] php-sqlite/sqlite3: vorhanden")

    # python requests (TMDB API)
    try:
       import requests # type: ignore
       print("[DEPS] python3-requests: vorhanden")
    except ImportError:
        print("[DEPS] python3-requests fehlt -> wird installiert")
        subprocess.run(["apt", "install", "-y", "python3-requests"], check=False)

    if need_install:
        print(f"[DEPS] apt install: {' '.join(packages)}")
        subprocess.run(["apt", "update"], check=False)
        subprocess.run(["apt", "install", "-y", *packages], check=False)

  #  WICHTIG: php-fpm IMMER starten + aktivieren
    print("[DEPS] Starte & aktiviere php-fpm")

    subprocess.run(
    ["systemctl", "enable", "--now", "php8.2-fpm"],
    check=False
)

def _write_if_missing(path: Path, content: str, label: str) -> bool:
    """
    Returns True wenn neu geschrieben wurde.
    """
    if path.exists():
        print(f"[NGINX] {label}: vorhanden -> überspringe ({path})")
        return False
    path.write_text(content, encoding="utf-8")
    print(f"[NGINX] {label}: erstellt -> {path}")
    return True

# =========================
# NGINX CONFIG SETUP
# =========================

def ensure_nginx_sites() -> None:
    sites_avail = Path("/etc/nginx/sites-available")
    sites_en    = Path("/etc/nginx/sites-enabled")

    sites_avail.mkdir(parents=True, exist_ok=True)
    sites_en.mkdir(parents=True, exist_ok=True)

    iptv_conf = f"""server {{
    listen {IPTV_PORT} default_server;
    listen [::]:{IPTV_PORT} default_server;
    server_name _;

    root {IPTV_ROOT};

    types {{
        application/vnd.apple.mpegurl m3u8;
        video/mp2t ts;
        text/xml xml;
    }}

    add_header Cache-Control "no-cache" always;
    add_header Access-Control-Allow-Origin "*" always;

    location = /health {{
        return 200 "OK\\n";
        add_header Content-Type text/plain;
    }}

    location / {{
        try_files $uri =404;
    }}

    location /picons/ {{
        alias {PICONS_ROOT}/;
        autoindex on;
    }}
}}
"""

    vod_conf = f"""server {{
    listen {VOD_PORT} default_server;
    listen [::]:{VOD_PORT} default_server;

    server_name _;
    root {VOD_ROOT};
    index index.php;
    client_max_body_size 0;

    # Wichtige MIME Types
    types {{
        application/vnd.apple.mpegurl m3u8;
        video/mp2t ts;
        text/xml xml;
        application/json json;
    }}

    # CORS für alle Endpunkte
    add_header Access-Control-Allow-Origin "*" always;
    add_header Access-Control-Allow-Methods "GET, HEAD, OPTIONS" always;
    add_header Access-Control-Allow-Headers "*" always;

    # OPTIONS Preflight handling
    location ~* \\.php$ {{
        if ($request_method = 'OPTIONS') {{
            add_header Access-Control-Allow-Origin "*";
            add_header Access-Control-Allow-Methods "GET, HEAD, OPTIONS";
            add_header Access-Control-Allow-Headers "*";
            add_header Content-Length 0;
            add_header Content-Type text/plain;
            return 204;
        }}

        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:{PHP_FPM_SOCK};
    }}

    # ---------------- LIVE STREAM Playback (NEUE VERSION) ----------------
    # ALLES unter /live/bling/vod123/ an Port IPTV_PORT weiterleiten
    location ~ ^/live/(?<u>[^/]+)/(?<p>[^/]+)/(?<sid>[0-9]+)\.ts$ {{
        rewrite ^ /live_ts.php?username=$u&password=$p&id=$sid last;

        # An Port IPTV_PORT weiterleiten
        proxy_pass http://127.0.0.1:{IPTV_PORT};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # User-Agent für Formuler/MyTVOnline
        proxy_set_header User-Agent "VLC/3.0.18 LibVLC/3.0.18";

        # Wichtig für HLS
        proxy_buffering off;
        proxy_cache off;
        proxy_intercept_errors off;

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 3600s;
    }}

    # ---------------- VOD Playback ----------------
    location ~ ^/(movie|vod|series)/([^/]+)/([^/]+)/([0-9]+)\.(m3u8|ts|mp4|mkv|avi|mov|m4v)$ {{
        set $type $1;
        set $user $2;
        set $pass $3;
        set $id   $4;
        set $ext  $5;

        if ($user != "{VOD_USER}") {{
            return 403;
        }}
        if ($pass != "{VOD_PASS}") {{
            return 403;
        }}

        rewrite ^ /stream.php?type=$type&username=$user&password=$pass&id=$id&ext=$ext last;
    }}

    # API Endpoints
    location ~ ^/(player_api.php|panel_api.php|get.php)$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:{PHP_FPM_SOCK};
    }}

    # EPG XMLTV Endpoint (kein PHP parsing, direkte Auslieferung)
    location = /xmltv.php {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:{PHP_FPM_SOCK};
        add_header Content-Type text/xml;
    }}

    # Normal PHP
    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:{PHP_FPM_SOCK};
    }}

    # Statische Dateien
    location / {{
        try_files $uri $uri/ =404;
    }}
}}
"""

    iptv_path = sites_avail / f"{IPTV_NAME}.conf"
    vod_path  = sites_avail / f"{VOD_NAME}.conf"

    changed = False
    changed |= _write_if_missing(iptv_path, iptv_conf, f"{IPTV_NAME}.conf (IPTV)")
    changed |= _write_if_missing(vod_path,  vod_conf,  f"{VOD_NAME}.conf (VOD/Xstreamity)")

    # Symlinks (idempotent)
    def link_site(name: str) -> bool:
        src = sites_avail / f"{name}.conf"
        dst = sites_en / f"{name}.conf"
        if dst.exists():
            print(f"[NGINX] enabled: {name}.conf schon aktiv -> ok")
            return False
        dst.symlink_to(src)
        print(f"[NGINX] enabled: {name}.conf verlinkt")
        return True

    changed |= link_site(IPTV_NAME)
    changed |= link_site(VOD_NAME)

    # nginx reload nur wenn wirklich was neu war
    if changed:
        print("[NGINX] Reload nginx ...")
        subprocess.run(["rm", "-f", "/etc/nginx/sites-enabled/default", "/etc/nginx/sites-available/default"], check=False)
        subprocess.run(["systemctl", "enable", "--now", "nginx"], check=False)
        subprocess.run(["systemctl", "start", "--now", "nginx"], check=False)
        subprocess.run(["systemctl", "reload", "nginx"], check=False)
    else:
        print("[NGINX] Keine Änderungen -> kein Reload nötig.")
# =========================
# VOD WEB FILES schreiben (config.php / player_api.php / stream.php / get.php)
# =========================

def write_vod_web() -> None:
    """
    Writes Xtream/Xstreamity-compatible web stack:
      - config.php
      - player_api.php
      - stream.php
      - live_ts.php   (Formuler Live .ts endpoint)
      - get.php
      - NGINX_REWRITE_EXAMPLE.txt
    Also writes:
      - BASE_HLS/live_map.json (stream_id -> channel_id)
    """

    # ---------- helpers ----------
    def _to_str_list(x):
        if x is None:
            return []
        if isinstance(x, (str, Path)):
            return [str(x)]
        try:
            return [str(i) for i in x]
        except TypeError:
            return [str(x)]

    def _merge_roots(a, b):
        out = []
        for x in (a or []) + (b or []):
            if x and x not in out:
                out.append(x)
        return out

    # Ensure dirs
    ensure_dir(VOD_WEBROOT)
    ensure_dir(BASE_HLS)

    # Merge roots (optional info)
    movie_roots = _to_str_list(_merge_roots(globals().get("MOVIE_ROOTS", []), globals().get("X_MOVIE_ROOTS", [])))
    series_roots = _to_str_list(_merge_roots(globals().get("SERIES_ROOTS", []), globals().get("X_SERIES_ROOTS", [])))
    video_ext = [str(x) for x in globals().get("VIDEO_EXT", ["mp4", "mkv"])]

    # Base URL must include scheme+port
    base_raw = str(globals().get("BASE_URL", "")).strip()
    if not base_raw:
        ip = str(globals().get("SERVER_IP", "127.0.0.1"))
        port = int(globals().get("VOD_PORT"))
        base_raw = f"http://{ip}:{port}"
    if "://" not in base_raw:
        ip = base_raw
        port = int(globals().get("VOD_PORT"))
        base_raw = f"http://{ip}:{port}"
    base_raw = base_raw.rstrip("/")

    # ---------- config.php ----------
    config_php = f"""<?php
return [
  "db" => {json.dumps(str(VOD_DB), ensure_ascii=False)},
  "user" => {json.dumps(str(VOD_USER), ensure_ascii=False)},
  "pass" => {json.dumps(str(VOD_PASS), ensure_ascii=False)},

  // FULL base URL incl. scheme + port (e.g. SERVER_IP:VOD_PORT)
  "base_url" => {json.dumps(base_raw, ensure_ascii=False)},
  "epg_xml" => "/srv/media_hdd/hls/epg_all.xml",

  // Optional info
  "movie_roots" => {json.dumps(movie_roots, ensure_ascii=False)},
  "series_roots" => {json.dumps(series_roots, ensure_ascii=False)},
  "video_ext" => {json.dumps(video_ext, ensure_ascii=False)},
];
"""
    write_text(VOD_WEBROOT / "config.php", config_php)

    # ---------- live_map.json (stream_id -> epg_channel_id) ----------
    # Uses your SQLite live_streams table (stream_id numeric, epg_channel_id is channel id like moviemixuhd)


    # ---------- player_api.php ----------
    # IMPORTANT FIX:
    # get_vod_streams must SELECT path, otherwise extension defaults wrong and MyTVOnline fails.
    player_api_php = r"""<?php
declare(strict_types=1);
header("Content-Type: application/json; charset=UTF-8");
ini_set("display_errors","0");
error_reporting(0);

$log = date("Y-m-d H:i:s") .
    " action=" . ($_GET["action"] ?? "none") .
    " user=" . ($_GET["username"] ?? "") .
    " uri=" . ($_SERVER["REQUEST_URI"] ?? "") .
    " GET=" . json_encode($_GET) .
    PHP_EOL;

file_put_contents("/tmp/factory_player_api.log", $log, FILE_APPEND);

$cfg = require __DIR__ . "/config.php";

function out($x) {
  echo json_encode($x, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
  exit;
}

function b64(string $s): string {
  return base64_encode($s);
}

function xmltv_to_unix(string $v): int {
  $v = trim($v);
  if ($v === "") return 0;

  // erwartet z.B. 20260319102000 +0100
  if (preg_match('/^(\d{14})\s+([+\-]\d{4})$/', $v, $m)) {
    $dt = DateTime::createFromFormat('YmdHis O', $m[1] . ' ' . $m[2]);
    return $dt ? $dt->getTimestamp() : 0;
  }

  // Fallback ohne TZ
  if (preg_match('/^\d{14}$/', $v)) {
    $dt = DateTime::createFromFormat('YmdHis', $v, new DateTimeZone('Europe/Vienna'));
    return $dt ? $dt->getTimestamp() : 0;
  }

  return 0;
}

function short_epg_from_xml(string $epgFile, string $channelId, int $limit = 10, string $sid = "", string $epgId = "0"): array {
  if ($channelId === "" || !file_exists($epgFile)) return [];
  $xml = @simplexml_load_file($epgFile);
  if (!$xml) return [];

  $now = time();
  $rows = [];
  $eventId = abs(crc32($channelId)) * 100000;

  foreach ($xml->programme as $p) {
    $attrs = $p->attributes();
    $ch = (string)($attrs['channel'] ?? '');
    if ($ch !== $channelId) continue;

    $startRaw = (string)($attrs['start'] ?? '');
    $stopRaw  = (string)($attrs['stop'] ?? '');
    $startTs = xmltv_to_unix($startRaw);
    $stopTs  = xmltv_to_unix($stopRaw);
    if ($startTs <= 0 || $stopTs <= 0) continue;

    // WICHTIG: Nicht nur aktuelle, sondern auch vergangene (für Timeline) und zukünftige!
    // Wir wollen Einträge vom Vortag bis +7 Tage
    if ($startTs < ($now - 86400)) continue;  // älter als 1 Tag zurück
    if ($startTs > ($now + 604800)) continue; // mehr als 7 Tage vor

    $title = trim((string)($p->title ?? ''));
    $desc  = trim((string)($p->desc ?? ''));

    $rows[] = [
      'id'       => (string)$eventId,
      'epg_id'   => (string)$epgId,
      'start_ts' => $startTs,
      'stop_ts'  => $stopTs,
      'title'    => $title,
      'desc'     => $desc,
    ];
    $eventId++;
  }

  // Nach Startzeit sortieren (aufsteigend)
  usort($rows, function($a, $b) { return $a['start_ts'] <=> $b['start_ts']; });

  $out = [];
  foreach ($rows as $r) {
    $out[] = [
      "id" => (string)$r['id'],
      "epg_id" => (string)$r['epg_id'],
      "title" => b64($r['title']),
      "lang" => "",
      "start" => date('Y-m-d H:i:s', $r['start_ts']),
      "end" => date('Y-m-d H:i:s', $r['stop_ts']),
      "description" => b64($r['desc']),
      "channel_id" => (string)$channelId,
      "start_timestamp" => (string)$r['start_ts'],
      "stop_timestamp" => (string)$r['stop_ts'],
      "stream_id" => (string)$sid
    ];
  }
  return $out;
}

function simple_data_table_from_xml(string $epgFile, string $channelId, int $limit = 10, string $epgId = "0"): array {
  if ($channelId === "" || !file_exists($epgFile)) {
    return [];
  }

  $xml = @simplexml_load_file($epgFile);
  if (!$xml) {
    return [];
  }

  $now = time();
  $rows = [];
  $eventId = abs(crc32($channelId)) * 100000;

  foreach ($xml->programme as $p) {
    $attrs = $p->attributes();
    $ch = (string)($attrs['channel'] ?? '');
    if ($ch !== $channelId) continue;

    $startRaw = (string)($attrs['start'] ?? '');
    $stopRaw  = (string)($attrs['stop'] ?? '');

    $startTs = xmltv_to_unix($startRaw);
    $stopTs  = xmltv_to_unix($stopRaw);

    if ($startTs <= 0 || $stopTs <= 0) continue;
    if ($stopTs < $now) continue;

    $title = trim((string)($p->title ?? ''));
    $desc  = trim((string)($p->desc ?? ''));

    $rows[] = [
      'id'       => (string)$eventId,
      'epg_id'   => (string)$epgId,
      'start_ts' => $startTs,
      'stop_ts'  => $stopTs,
      'title'    => $title,
      'desc'     => $desc,
    ];
    $eventId++;
  }

  usort($rows, function($a, $b) {
    return $a['start_ts'] <=> $b['start_ts'];
  });

  $out = [];
  foreach ($rows as $r) {
    $out[] = [
      "id" => (string)$r['id'],
      "epg_id" => (string)$r['epg_id'],
      "title" => b64($r['title']),
      "lang" => "",
      "start" => date('Y-m-d H:i:s', $r['start_ts']),
      "end" => date('Y-m-d H:i:s', $r['stop_ts']),
      "description" => b64($r['desc']),
      "channel_id" => (string)$channelId,
      "start_timestamp" => (string)$r['start_ts'],
      "stop_timestamp" => (string)$r['stop_ts'],
      "now_playing" => ($r['start_ts'] <= $now && $r['stop_ts'] > $now) ? 1 : 0,
      "has_archive" => 0
    ];
  }

  return $out;
}

$user = (string)($_GET["username"] ?? "");
$pass = (string)($_GET["password"] ?? "");
$action = (string)($_GET["action"] ?? "");

if (($user !== "" || $pass !== "") &&
    ($user !== (string)($cfg["user"] ?? "") || $pass !== (string)($cfg["pass"] ?? ""))) {
  http_response_code(403);
  out(["user_info"=>["auth"=>0,"status"=>"Disabled"]]);
}

$base = (string)($cfg["base_url"] ?? "");
if ($base === "") $base = "http://127.0.0.1";

$dbPath = (string)($cfg["db"] ?? "");
if (!$dbPath || !file_exists($dbPath)) { http_response_code(500); out([]); }

$pdo = new PDO("sqlite:" . $dbPath, null, null, [
  PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
  PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC
]);

function extOf(string $p, string $fallback="mp4"): string {
  $e = strtolower(pathinfo($p, PATHINFO_EXTENSION));
  return $e ? $e : $fallback;
}

function distinctCats(PDO $pdo, string $table, string $col): array {
  $sql = "SELECT DISTINCT COALESCE(NULLIF(TRIM($col),''),'Unsorted') AS c FROM $table ORDER BY c";
  return $pdo->query($sql)->fetchAll();
}

/* ============ USER / SERVER INFO ============ */
if ($action === "" || $action === "user_info" || $action === "auth") {
  out([
    "user_info" => [
        "auth" => 1,
        "status" => "Active",
        "username" => (string)($cfg["user"] ?? ""),
        "password" => (string)($cfg["pass"] ?? ""),
        "message" => "",
        "exp_date" => "",
        "is_trial" => "0",
        "active_cons" => "1",
        "created_at" => (string)time(),
        "max_connections" => "10",
        "allowed_output_formats" => ["m3u8","ts","mp4","mkv"]
    ],
    "server_info" => [
        "url" => "__SERVER_IP__",
        "port" => "__VOD_PORT__",
        "https_port" => "443",
        "server_protocol" => "http",
        "rtmp_port" => "25462",
        "timezone" => "Europe/Vienna",
        "timestamp_now" => (string)time(),
        "time_now" => date("Y-m-d H:i:s"),
        "process" => true
    ]
  ]);
}

/* ============ EPG ============ */
if ($action === "get_short_epg") {
  $sid = (string)($_GET["stream_id"] ?? "");
  $limit = (int)($_GET["limit"] ?? 10);

  if ($sid === "" || !ctype_digit($sid)) {
    out(["epg_listings" => []]);
  }

  $st = $pdo->prepare("SELECT id, epg_channel_id, stream_id FROM live_streams WHERE stream_id=:sid LIMIT 1");
  $st->execute([":sid" => (int)$sid]);
  $row = $st->fetch();

  if (!$row || empty($row["epg_channel_id"])) {
    out(["epg_listings" => []]);
  }

  $channelId = (string)$row["epg_channel_id"];
  $epgId = (string)($row["id"] ?? "0");
  $epgFile = (string)($cfg["epg_xml"] ?? "/srv/media_hdd/hls/epg_all.xml");

  // WICHTIG: Mehr Einträge laden (z.B. 20 statt 10)
  $list = short_epg_from_xml($epgFile, $channelId, $limit, (string)$sid, (string)$epgId);

  out(["epg_listings" => $list]);
}

if ($action === "get_simple_data_table") {
  $sid = (string)($_GET["stream_id"] ?? "");
  $limit = (int)($_GET["limit"] ?? 10);

  if ($sid === "" || !ctype_digit($sid)) {
    out(["epg_listings" => []]);
  }

  $st = $pdo->prepare("SELECT id, epg_channel_id, stream_id FROM live_streams WHERE stream_id=:sid LIMIT 1");
  $st->execute([":sid" => (int)$sid]);
  $row = $st->fetch();

  if (!$row) {
    out(["epg_listings" => []]);
  }

  $channelId = (string)($row["epg_channel_id"] ?? "");
  $epgId = (string)($row["id"] ?? "0");

  if ($channelId === "") {
    out(["epg_listings" => []]);
  }

  $epgFile = (string)($cfg["epg_xml"] ?? "/srv/media_hdd/hls/epg_all.xml");
  $list = simple_data_table_from_xml($epgFile, $channelId, $limit, $epgId);

  out(["epg_listings" => $list]);
}

/* ============ LIVE ============ */
if ($action === "get_live_categories") {
  out([
    ["category_id"=>"1","category_name"=>"__BOUQUET_NAME__","parent_id"=>0]
  ]);
}

if ($action === "get_live_streams") {
  $rows = [];
  $ok = $pdo->query("SELECT name FROM sqlite_master WHERE type='table' AND name='live_streams'")->fetch();
  if ($ok) {
    $rows = $pdo->query("SELECT stream_id, name, epg_channel_id, logo, category_id FROM live_streams ORDER BY stream_id ASC")->fetchAll();
  }

  $streams = [];
  foreach ($rows as $ch) {
    $sid = (int)($ch["stream_id"] ?? 0);
    $eid = (string)($ch["epg_channel_id"] ?? "");
    $streams[] = [
      "num" => $sid,
      "name" => (string)($ch["name"] ?? ""),
      "stream_type" => "live",
      "stream_id" => $sid,
      "stream_icon" => (string)($ch["logo"] ?? ""),
      "epg_channel_id" => $eid,
      "added" => (string)time(),
      "category_id" => (string)($ch["category_id"] ?? "1"),
      "custom_sid" => "",
      "tv_archive" => 0,
      "direct_source" => "",
      "epg_file" => $base . "/xmltv.php",
      "tv_archive_duration" => 0,
      "container_extension" => "ts"
    ];
  }

  out($streams);
}

/* ============ VOD (Movies) ============ */
if ($action === "get_vod_categories") {
  // Nur eine Kategorie: Movies (ID 0)
  out([
    ["category_id"=>"1","category_name"=>"Movies","parent_id"=>0]
  ]);
}

if ($action === "get_vod_streams") {
  $categoryId = (string)($_GET["category_id"] ?? "1");

  $ok = $pdo->query("SELECT name FROM sqlite_master WHERE type='table' AND name='vod'")->fetch();
  if (!$ok) out([]);

  $catMap = [];
  $rows = distinctCats($pdo, "vod", "cat");
  $i=1;
  foreach ($rows as $r) { $catMap[(string)$i] = (string)$r["c"]; $i++; }

  $where = "";
  $params = [];
  $outCatId = "0";
  if ($categoryId !== "1" && isset($catMap[$categoryId])) {
    $where = "WHERE COALESCE(NULLIF(TRIM(cat),''),'Unsorted') = :c";
    $params[":c"] = $catMap[$categoryId];
    $outCatId = $categoryId;
  }

  // FIX: include path so extOf() works
  $sql = "SELECT id, kinopoisk_url, tmdb_id, title, o_name, backdrop, plot, `cast`, director, genre, release_date, rating, poster, path, COALESCE(NULLIF(TRIM(cat),''),'Unsorted') AS cat, `cast`, `trailer`
          FROM vod $where
          ORDER BY id DESC";
  $st = $pdo->prepare($sql);
  $st->execute($params);
  $rows = $st->fetchAll();

  $outStreams = [];
  $n=1;
  foreach ($rows as $r) {

      $castArray = json_decode((string)($r["cast"] ?? "[]"), true);
      if (!is_array($castArray)) $castArray = [];

      $names = [];
      foreach ($castArray as $actor) {
          if (!empty($actor["name"])) {
              $names[] = $actor["name"];
          }
      }

    $namesString = implode(", ", $names);

    $ext = extOf((string)($r["path"] ?? ""), "mp4");
    $streamId = (int)$r["id"];
    $direct = $base . "/movie/$user/$pass/$streamId.$ext";
    $outStreams[] = [
      "num" => $n++,
      "name" => (string)$r["title"],
      "stream_type" => "movie",
      "stream_id" => $streamId,
      "stream_icon" => (string)($r["poster"] ?? ""),
      "rating" => isset($r["rating"]) ? (float)$r["rating"] : 0.0,
      "rating_5based" => (string)round(((float)($r["rating"] ?? 0)) / 2, 1),
      "tmdb" => (string)($r["tmdb_id"] ?? ""),
      "trailer" => "",
      "added" => (string)time(),
      "is_adult" => "0",
      "category_id" => "1",
      "container_extension" => $ext,
      "direct_source" => $direct
    ];
  }
  out($outStreams);
}

if ($action === "get_vod_info") {
  $vid = (string)($_GET["vod_id"] ?? $_GET["stream_id"] ?? "");
  if ($vid === "" || !ctype_digit($vid)) out(["info"=>new stdClass(),"movie_data"=>new stdClass()]);

  $st = $pdo->prepare("SELECT id, title, o_name, kinopoisk_url, tmdb_id, poster, plot, rating, release_date, backdrop, `cast`, `trailer`, director, genre, country FROM vod WHERE id=:id LIMIT 1");
  $st->execute([":id" => (int)$vid]);
  $r = $st->fetch();
  if (!$r) out(["info"=>new stdClass(),"movie_data"=>new stdClass()]);

  $castArray = json_decode((string)($r["cast"] ?? "[]"), true);
  if (!is_array($castArray)) $castArray = [];

  $names = [];
  $imageUrls = [];
  $characters = [];

  foreach ($castArray as $actor) {
      if (!empty($actor["name"])) $names[] = $actor["name"];
      if (!empty($actor["profile_path"])) $imageUrls[] = $actor["profile_path"];
      if (!empty($actor["character"])) $characters[] = $actor["character"];
  }

  $namesString = implode(", ", $names);
  $imagesString = implode(", ", $imageUrls);
  $charactersString = implode(", ", $characters);

  out([
    "info" => [
      "kinopoisk_url" => (string)($r["kinopoisk_url"] ?? ""),
      "tmdb_id" => (string)($r["tmdb_id"] ?? ""),
      "name" => (string)$r["title"],
      "o_name" => (string)($r["o_name"] ?? ""),
      "cover_big" => (string)($r["poster"] ?? ""),
      "cover" => (string)($r["poster"] ?? ""),
      "movie_image" => (string)($r["poster"] ?? ""),
      "releasedate" => (string)($r["release_date"] ?? ""),
      "releaseDate" => (string)($r["release_date"] ?? ""),
      "release_date" => (string)($r["release_date"] ?? ""),
      "youtube_trailer" => (string)($r["trailer"] ?? ""),
      "director" => (string)($r["director"] ?? ""),
      "actors" => $namesString,
      "cast" => $namesString,
      "description" => (string)($r["plot"] ?? ""),
      "plot" => (string)($r["plot"] ?? ""),
      "rating" => (string)($r["rating"] ?? ""),
      "rating_5based" => (string)round(((float)($r["rating"] ?? 0)) / 2, 1),
      "country" => (string)($r["country"] ?? ""),
      "genre" => (string)($r["genre"] ?? ""),
      "backdrop_path" => ((string)($r["backdrop"] ?? "") !== "") ? [(string)$r["backdrop"]] : [],
      "cast_array" => $castArray
    ],
    "movie_data" => [
      "stream_id" => (int)$r["id"],
      "name" => (string)$r["title"],
      "o_name" => (string)($r["o_name"] ?? ""),
      "added" => (string)time(),
      "category_id" => "1",
      "container_extension" => extOf((string)($r["path"] ?? ""), "mp4")
    ]
  ]);
}

/* ============ SERIES ============ */

if ($action === "get_series_categories") {
  // Nur eine Kategorie: Series (ID 0)
  out([
    ["category_id"=>"0","category_name"=>"Series","parent_id"=>0]
  ]);
}

if ($action === "get_series") {
  $categoryId = (string)($_GET["category_id"] ?? "0");

  $ok = $pdo->query("SELECT name FROM sqlite_master WHERE type='table' AND name='series'")->fetch();
  if (!$ok) out([]);

  $catMap = [];
  $rows = distinctCats($pdo, "series", "cat");
  $i=1;
  foreach ($rows as $r) { $catMap[(string)$i] = (string)$r["c"]; $i++; }

  $where = "";
  $params = [];
  $outCatId = "0";
  if ($categoryId !== "0" && isset($catMap[$categoryId])) {
    $where = "WHERE COALESCE(NULLIF(TRIM(cat),''),'Unsorted') = :c";
    $params[":c"] = $catMap[$categoryId];
    $outCatId = $categoryId;
  }

  $sql = "SELECT id, name, o_name, kinopoisk_url, COALESCE(NULLIF(TRIM(cat),''),'Unsorted') AS cat, tmdb_id, poster, backdrop, plot, rating, release_date, `cast`, `trailer`, director, genre
          FROM series $where
          ORDER BY id DESC";
  $st = $pdo->prepare($sql);
  $st->execute($params);
  $rows = $st->fetchAll();

  $outSeries = [];
  $n=1;
  foreach ($rows as $r) {

      $castArray = json_decode((string)($r["cast"] ?? "[]"), true);
      if (!is_array($castArray)) $castArray = [];

      $names = [];
      foreach ($castArray as $actor) {
          if (!empty($actor["name"])) {
              $names[] = $actor["name"];
          }
      }

    $namesString = implode(", ", $names);

    $outSeries[] = [
      "num" => $n++,
      "name" => (string)$r["name"],
      "cover" => (string)($r["poster"] ?? ""),
      "plot" => (string)($r["plot"] ?? ""),
      "cast" => $namesString,
      "director" => (string)($r["director"] ?? ""),
      "genre" => (string)($r["genre"] ?? ""),
      "releasedate" => (string)($r["release_date"] ?? ""),
      "releaseDate" => (string)($r["release_date"] ?? ""),
      "release_date" => (string)($r["release_date"] ?? ""),
      "rating" => isset($r["rating"]) ? (float)$r["rating"] : 0.0,
      "backdrop_path" => ((string)($r["backdrop"] ?? "") !== "") ? [ (string)$r["backdrop"] ] : [],
      "tmdb" => (string)($r["tmdb_id"] ?? ""),
      "kinopoisk_url" => (string)($r["kinopoisk_url"] ?? ""),
      "series_id" => (int)$r["id"],
      "category_id" => "0"
    ];
  }
  out($outSeries);
}

if ($action === "get_series_info") {
  $sid = (string)($_GET["series_id"] ?? "");
  if ($sid === "" || !ctype_digit($sid)) out(["info"=>new stdClass(),"seasons"=>[],"episodes"=>new stdClass()]);

  $s = $pdo->prepare("SELECT id, name, o_name, kinopoisk_url, COALESCE(NULLIF(TRIM(cat),''),'Unsorted') AS cat, tmdb_id, poster, backdrop, plot, rating, release_date, `cast`, `trailer`, director, genre, country
                      FROM series WHERE id=:id LIMIT 1");
  $s->execute([":id" => (int)$sid]);
  $row = $s->fetch();
  if (!$row) out(["info"=>new stdClass(),"seasons"=>[],"episodes"=>new stdClass()]);

  $e = $pdo->prepare("SELECT id, season, episode, title, path, crew
                      FROM episodes WHERE series_id=:sid
                      ORDER BY season, episode, id");
  $e->execute([":sid" => (int)$sid]);
  $eps = $e->fetchAll();

  $castArray = json_decode((string)($row["cast"] ?? "[]"), true);
  if (!is_array($castArray)) $castArray = [];

  $names = [];
  $imageUrls = [];
  $characters = [];

  foreach ($castArray as $actor) {
      if (!empty($actor["name"])) $names[] = $actor["name"];
  }

  $namesString = implode(", ", $names);

  $grouped = [];
  $seasonsMeta = [];

  foreach ($eps as $ep) {
    $season = (int)($ep["season"] ?? 1);
    if ($season <= 0) $season = 1;
    $epnum  = (int)($ep["episode"] ?? 0);

    $path = (string)($ep["path"] ?? "");
    $ext  = extOf($path, "mkv");
    $seasonKey = (string)$season;

    if (!isset($seasonsMeta[$seasonKey])) $seasonsMeta[$seasonKey] = 0;
    $seasonsMeta[$seasonKey]++;

    $eid = (int)$ep["id"];

    $castNames = [];

    if (!empty($row["cast"])) {
        $castData = json_decode($row["cast"], true);

        if (is_array($castData)) {
            foreach ($castData as $c) {
                if (!empty($c["name"])) {
                    $castNames[] = $c["name"];
                }
            }
        }
    }

    $grouped[$seasonKey][] = [
    "id" => (string)$eid,
    "episode_num" => $epnum,
    "title" => (string)($ep["title"] ?? ""),
    "container_extension" => $ext,
    "info" => [
        "air_date" => (string)($ep["air_date"] ?? ($row["release_date"] ?? "")),
        "crew" => (string)($ep["crew"] ?? ""),
        "rating" => (float)($ep["rating"] ?? ($row["rating"] ?? 0)),
        "id" => (int)($row["tmdb_id"] ?? ($row["tmdb"] ?? 0)),
        "movie_image" => (string)($ep["movie_image"] ?? ($row["poster"] ?? "")),
        "duration_secs" => (int)($ep["duration_secs"] ?? 0),
        "duration" => (string)($ep["duration"] ?? "")
    ],
    "custom_sid" => null,
    "added" => (string)time(),
    "season" => $season,
    "direct_source" => "",
    "stream_id" => $eid
    ];
  }

  $seasons = [];
  foreach ($seasonsMeta as $sk => $cnt) {
    $sn = (int)$sk;
    $seasons[] = [
    "id" => $sn,
    "season_number" => $sn,
    "name" => "Season " . $sn,
    "episode_count" => (string)$cnt,
    "overview" => (string)($row["poster"] ?? ""),
    "air_date" => (string)($row["release_date"] ?? ""),
    "cover" => (string)($row["poster"] ?? ""),
    "cover_tmdb" => (string)($row["poster"] ?? ""),
    "cover_big" => (string)($row["poster"] ?? ""),
    "releaseDate" => (string)($row["release_date"] ?? ""),
    "duration" => "0"
    ];
  }

  $episodes = count($grouped) ? $grouped : new stdClass();

  out([
    "seasons" => $seasons,
    "info" => [
      "name" => (string)$row["name"],
      "cover" => (string)($row["poster"] ?? ""),
      "plot" => (string)($row["plot"] ?? ""),
      "cast" => $namesString,
      "director" => (string)($row["director"] ?? ""),
      "genre" => (string)($row["genre"] ?? ""),
      "releaseDate" => (string)($row["release_date"] ?? ""),
      "release_date" => (string)($row["release_date"] ?? ""),
      "last_modified" => (string)time(),
      "rating" => (string)($row["rating"] ?? ""),
      "rating_5based" => (string)round(((float)$row["rating"] ?? 0) /2, 1),
      "backdrop_path" => ((string)($row["backdrop"] ?? "") !== "") ? [ (string)$row["backdrop"] ] : [],
      "tmdb" => (string)($row["tmdb_id"] ?? ""),
      "kinopoisk_url" => (string)($row["kinopoisk_url"] ?? ""),
      "youtube_trailer" => (string)($row["trailer"] ?? ""),
      "series_id" => (int)$sid
    ],
    "episodes" => $episodes
  ]);
}

out([]);
?>
"""
    player_api_php = player_api_php.replace("__BOUQUET_NAME__", BOUQUET_NAME)
    player_api_php = player_api_php.replace("__SERVER_IP__", SERVER_IP)
    player_api_php = player_api_php.replace("__VOD_PORT__", str(VOD_PORT))

    write_text(VOD_WEBROOT / "player_api.php", player_api_php)

    # ---------- stream.php ----------
    # Includes: Range support + parse Xtream paths + /vod alias
    stream_php = r"""<?php
declare(strict_types=1);
ini_set("display_errors","0");
error_reporting(0);

$cfg = require __DIR__ . "/config.php";

function forbidden(): void { http_response_code(403); exit; }
function bad(): void { http_response_code(400); exit; }
function notfound(): void { http_response_code(404); exit; }

$user = (string)($_GET["username"] ?? "");
$pass = (string)($_GET["password"] ?? "");
$type = (string)($_GET["type"] ?? "");
$id   = (string)($_GET["id"] ?? "");

$uri = (string)($_SERVER["REQUEST_URI"] ?? "");

// Xtream-style paths:
// /movie/user/pass/123.ext
// /vod/user/pass/123.ext
// /series/user/pass/456.ext
if ($user === "" || $pass === "" || $id === "" || $type === "") {
  if (preg_match('~/(movie|vod|series)/([^/]+)/([^/]+)/([0-9]+)(?:\.[a-z0-9]+)?~i', $uri, $m)) {
    $type = strtolower($m[1]);
    $user = $m[2];
    $pass = $m[3];
    $id   = $m[4];
  }
}

// normalize vod->movie
if ($type === "vod") $type = "movie";

if ($user !== (string)($cfg["user"] ?? "") || $pass !== (string)($cfg["pass"] ?? "")) forbidden();
if ($id === "" || !ctype_digit($id)) bad();
if ($type !== "movie" && $type !== "series") $type = "movie";

$dbPath = (string)($cfg["db"] ?? "");
if (!$dbPath || !file_exists($dbPath)) { http_response_code(500); exit; }

$pdo = new PDO("sqlite:" . $dbPath, null, null, [
  PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
  PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC
]);

if ($type === "movie") {
  $st = $pdo->prepare("SELECT path FROM vod WHERE id=:id LIMIT 1");
  $st->execute([":id" => (int)$id]);
} else {
  $st = $pdo->prepare("SELECT path FROM episodes WHERE id=:id LIMIT 1");
  $st->execute([":id" => (int)$id]);
}
$row = $st->fetch();
$path = $row ? (string)$row["path"] : "";
if ($path === "" || !file_exists($path)) notfound();

$size = filesize($path);
$ext  = strtolower(pathinfo($path, PATHINFO_EXTENSION));
$mime = "application/octet-stream";
if ($ext === "mp4") $mime = "video/mp4";
elseif ($ext === "mkv") $mime = "video/x-matroska";
elseif ($ext === "avi") $mime = "video/x-msvideo";
elseif ($ext === "ts")  $mime = "video/mp2t";

$start = 0;
$end   = $size - 1;
$length = $size;

header("Content-Type: ".$mime);
header("Accept-Ranges: bytes");

if (isset($_SERVER["HTTP_RANGE"])) {
  if (preg_match('/bytes=(\d+)-(\d*)/', (string)$_SERVER["HTTP_RANGE"], $m)) {
    $start = (int)$m[1];
    $end = ($m[2] !== "") ? (int)$m[2] : $end;
    if ($start > $end || $end >= $size) { http_response_code(416); exit; }
    $length = $end - $start + 1;
    http_response_code(206);
    header("Content-Range: bytes $start-$end/$size");
  }
}

header("Content-Length: ".$length);
header('Content-Disposition: inline; filename="'.basename($path).'"');

$fp = fopen($path, "rb");
if (!$fp) { http_response_code(500); exit; }
fseek($fp, $start);

$chunk = 1024 * 1024; // 1MB
$sent = 0;
while (!feof($fp) && $sent < $length) {
  $toRead = min($chunk, $length - $sent);
  $buf = fread($fp, $toRead);
  if ($buf === false) break;
  echo $buf;
  $sent += strlen($buf);
  @ob_flush();
  flush();
}
fclose($fp);
?>
"""
    write_text(VOD_WEBROOT / "stream.php", stream_php)

    # ---------- live_ts.php ----------
    # IMPORTANT: must be f-string because we inject BASE_HLS + IPTV_PORT.
    # Therefore PHP braces must be doubled {{ }}
    live_ts_php = f"""<?php
declare(strict_types=1);
ini_set("display_errors","0");
error_reporting(0);

$cfg = require __DIR__ . "/config.php";

$user = (string)($_GET["username"] ?? "");
$pass = (string)($_GET["password"] ?? "");
$id   = (string)($_GET["id"] ?? "");

if ($user !== (string)($cfg["user"] ?? "") || $pass !== (string)($cfg["pass"] ?? "")) {{
  http_response_code(403);
  exit;
}}

if ($id === "" || !ctype_digit($id)) {{
  http_response_code(400);
  exit;
}}

$mapFile = "{BASE_HLS}/live_map.json";
if (!file_exists($mapFile)) {{ http_response_code(500); exit; }}

$map = json_decode((string)file_get_contents($mapFile), true);
if (!is_array($map) || !isset($map[$id])) {{ http_response_code(404); exit; }}

$channel = $map[$id];
$src = "http://127.0.0.1:{IPTV_PORT}/" . rawurlencode($channel) . ".m3u8";

header("Content-Type: video/mp2t");
header("Cache-Control: no-cache");
header("Connection: close");

// stream HLS -> TS (copy)
passthru('/usr/bin/ffmpeg -hide_banner -loglevel quiet -fflags +genpts+discardcorrupt -flags low_delay -i ' . escapeshellarg($src) . ' -c copy -muxdelay 0 -muxpreload 0 -f mpegts -');
?>"""
    write_text(VOD_WEBROOT / "live_ts.php", live_ts_php)

    # ---------- get.php ----------
    get_php = r"""<?php
declare(strict_types=1);
header("Content-Type: application/json; charset=UTF-8");
$cfg = require __DIR__ . "/config.php";

echo json_encode([
  "user_info" => [
    "auth" => 1,
    "status" => "Active",
    "username" => (string)($cfg["user"] ?? ""),
    "password" => (string)($cfg["pass"] ?? ""),
    "exp_date" => null,
    "is_trial" => 0,
    "active_cons" => 1,
    "created_at" => time(),
    "max_connections" => 10,
    "allowed_output_formats" => ["m3u8","ts","mp4","mkv"]
  ],
  "server_info" => [
    "url" => "__SERVER_IP__",
    "port" => "__VOD_PORT__",
    "https_port" => "",
    "server_protocol" => "http",
    "timezone" => "Europe/Vienna",
    "timestamp_now" => time()
  ]
], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
?>
"""
    player_api_php = player_api_php.replace("__SERVER_IP__", SERVER_IP)
    player_api_php = player_api_php.replace("__VOD_PORT__", str(VOD_PORT))

    write_text(VOD_WEBROOT / "get.php", get_php)

    # ---------- nginx rewrite note ----------
#    nginx_note = r"""# NGINX rewrite example for Xtream paths:
# location ~ ^/(movie|vod|series)/([^/]+)/([^/]+)/([0-9]+)\.(.+)$ {
#     rewrite ^/(movie|vod|series)/([^/]+)/([^/]+)/([0-9]+)\.(.+)$ /stream.php?type=$1&username=$2&password=$3&id=$4 last;
# }
# location ~ ^/live/([^/]+)/([^/]+)/([0-9]+)\.ts$ {
#     rewrite ^ /live_ts.php?username=$1&password=$2&id=$3 last;
# }
#"""
#    write_text(VOD_WEBROOT / "NGINX_REWRITE_EXAMPLE.txt", nginx_note)

#    print(f"[VOD] Webfiles geschrieben: {VOD_WEBROOT}")

def write_xmltv_epg() -> None:
    """
    Erstellt eine xmltv.php für MyTVOnline EPG
    """
    xmltv_file = VOD_WEBROOT / "xmltv.php"
    epg_source = "/srv/media_hdd/hls/epg_all.xml"

    content = """<?php
$epg_file = "{epg_source}";

// iOS/MyTVOnline+ braucht korrekte Headers
header("Content-Type: text/xml; charset=UTF-8");
header("Cache-Control: no-cache, must-revalidate");
header("Expires: Mon, 26 Jul 1997 05:00:00 GMT");
header("Access-Control-Allow-Origin: *");

if (file_exists($epg_file) && filesize($epg_file) > 100) {{
    readfile($epg_file);
}} else {{
    // Leeres aber gültiges XMLTV falls EPG noch nicht bereit
    echo '<?xml version="1.0" encoding="UTF-8"?>';
    echo '<tv generator-info-name="TV Factory" generator-info-url="http://localhost"></tv>';
}}
?>
""".format(epg_source=epg_source)

    write_text(xmltv_file, content)
    print(f"[EPG] xmltv.php erstellt: {xmltv_file}")


# =========================
# 4) DB sicherstellen + Schema
# =========================

def ensure_vod_db() -> None:
    # ABSOLUTER SCHUTZ
    print(f"[VOD] DB target = {VOD_DB}")

    # 1. Parent-Dir erzwingen (rekursiv!)
    VOD_DB_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Rechte + Owner VOR sqlite
    run(["chown", "-R", "www-data:www-data", str(VOD_DB_DIR)], check=False)
    run(["chmod", "775", str(VOD_DB_DIR)], check=False)

    # 3. Test: kann ich hier schreiben?
    testfile = VOD_DB_DIR / ".write_test"
    try:
        testfile.write_text("ok")
        testfile.unlink()
    except Exception as e:
        print("[VOD][FATAL] write test failed:", e)
        sys.exit(1)

    # 4. SQLite öffnen (JETZT erst)
    con = sqlite3.connect(str(VOD_DB))
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS vod (
            id INTEGER PRIMARY KEY,
            title TEXT,
            cat TEXT,
            path TEXT,
            director TEXT,
            genre TEXT,
            country TEXT,
            o_name TEXT,
            kinopoisk_url TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS series (
            id INTEGER PRIMARY KEY,
            name TEXT,
            cat TEXT,
            director TEXT,
            genre TEXT,
            country TEXT,
            o_name TEXT,
            kinopoisk_url TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY,
            series_id INTEGER,
            season INTEGER,
            episode INTEGER,
            title TEXT,
            path TEXT,
            plot TEXT,
            crew TEXT
        )
    """)

    ensure_series_tmdb_columns(con)
    ensure_vod_tmdb_columns(con)
    try:
        cur.execute("ALTER TABLE episodes ADD COLUMN plot TEXT")
    except sqlite3.OperationalError:
        pass
    con.commit()
    con.close()

    # 5. Rechte auf DB-Datei
    run(["chown", "www-data:www-data", str(VOD_DB)], check=False)
    run(["chmod", "664", str(VOD_DB)], check=False)

    print("[VOD] DB Rechte Gesetzt")

# =========================
# 5) MOVIES SCAN -> vod table
# =========================
def scan_vod_sqlite() -> int:
    con = sqlite3.connect(VOD_DB)
    cur = con.cursor()

    found = 0

    cur.execute("SELECT COALESCE(MAX(id), 0) FROM vod")
    vid = cur.fetchone()[0] + 1

    EXT = {".mkv", ".mp4", ".avi", ".mov", ".m4v"}

    roots = []
    roots += list(globals().get("MOVIES_ROOTS", []))
    roots += list(globals().get("X_MOVIE_ROOTS", []))

    seen = set()
    roots = [r for r in roots if not (str(r) in seen or seen.add(str(r)))]

    for root in roots:
        root = Path(root)
        if not root.exists():
            continue

        # REKURSIV durch ALLE Unterordner
        for p in root.rglob("*"):
            if not p.is_file():
                continue

            if p.suffix.lower() not in EXT:
                continue

            m = re.match(r"^(.*)\((\d{4})\)$", p.stem.strip())
            if m:
                title = m.group(1).strip()
                year = m.group(2)
            else:
                title = p.stem.strip()
                year = None
            rel = p.relative_to(root)
            cat = rel.parts[0] if len(rel.parts) > 1 else root.name
            path = str(p)

            cur.execute("SELECT path FROM vod")
            existing_paths = {row[0] for row in cur.fetchall()}
            if path in existing_paths:
                continue

            tmdb_id_tag = extract_tmdb_id(title)
            clean_title_db = clean_title(strip_tmdb_tag(title))

            if tmdb_id_tag:
                tmdb = fetch_tmdb_by_id(tmdb_id_tag)
            else:
                tmdb = fetch_tmdb(clean_title(clean_title_db), year)

            if tmdb:
                cur.execute(
                    "INSERT INTO vod(id,title,o_name,kinopoisk_url,cat,path,tmdb_id,poster,backdrop,plot,rating,release_date,cast,trailer,director,genre,country) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (vid, clean_title_db, tmdb.get("o_name", ""), tmdb.get("kinopoisk_url", ""), cat, path, tmdb["tmdb_id"], tmdb["poster"], tmdb["backdrop"],
                     tmdb["plot"], tmdb["rating"], tmdb["release_date"], tmdb.get("cast", ""), tmdb.get("trailer", ""), tmdb.get("director", ""), tmdb.get("genre", ""), tmdb.get("country", ""))
                )
                time.sleep(0.05)
            else:
                cur.execute("INSERT INTO vod(id,clean_db_title,o_name,cat,path) VALUES(?,?,?,?,?)", (vid,title,"",cat,path))

            vid += 1
            found += 1

    con.commit()
    con.close()

    print(f"[SCAN] VOD fertig -> {found} Einträge")
    return found

# =========================
# 6) SERIES SCAN -> series + episodes
# Serienstruktur: /serien/Serienname/Staffel/Dateien
# Titel soll Staffel/Episode aus filename oder fallback (season folder)
# =========================
def scan_series_sqlite() -> tuple[int, int]:
    con = sqlite3.connect(VOD_DB)
    cur = con.cursor()

    EXT = {".mkv", ".mp4", ".avi", ".mov", ".m4v"}

    cur.execute("SELECT COALESCE(MAX(id), 0) FROM series")
    series_id = cur.fetchone()[0] + 1

    cur.execute("SELECT COALESCE(MAX(id), 0) FROM episodes")
    ep_id = cur.fetchone()[0] + 1

    series_count = 0
    ep_count = 0

    roots = []
    roots += list(globals().get("SERIES_ROOTS", []))
    roots += list(globals().get("X_SERIES_ROOTS", []))

    for root in roots:
        for sdir in sorted(root.iterdir()):
            if not sdir.is_dir():
                continue

            sname = sdir.name
            cat = "Series"

            cur.execute("SELECT id FROM series WHERE name=?", (sname,))
            row = cur.fetchone()

            cur.execute("SELECT id FROM series WHERE name=?", (sname,))
            row = cur.fetchone()

            if row:
                current_series_id = row[0]
                tmdb = None
            else:
                tmdb = fetch_tmdb_tv(clean_title(sname))

            cur.execute("SELECT id FROM series WHERE name=?", (sname,))
            row = cur.fetchone()

            if row:
                current_series_id = row[0]
            else:
                if tmdb:
                    cur.execute(
                        "INSERT INTO series(id,name,o_name,kinopoisk_url,cat,tmdb_id,poster,backdrop,plot,rating,release_date,cast,trailer,director,genre,country) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            series_id,
                            sname,
                            tmdb.get("o_name", ""),
                            tmdb.get("kinopoisk_url", ""),
                            cat,
                            tmdb["tmdb_id"],
                            tmdb["poster"],
                            tmdb["backdrop"],
                            tmdb["plot"],
                            tmdb["rating"],
                            tmdb["release_date"],
                            tmdb.get("cast", ""),
                            tmdb.get("trailer", ""),
                            tmdb.get("director", ""),
                            tmdb.get("genre", ""),
                            tmdb.get("country", "")
                        )
                    )
                    time.sleep(0.05)
                else:
                    cur.execute(
                        "INSERT INTO series(id,name,o_name,cat) VALUES(?,?,?,?)",
                        (series_id, sname, "", cat)
                    )

                current_series_id = series_id
                series_id += 1
                series_count += 1

            # --- Staffeln finden (oder fallback ohne Staffel-Ordner) ---
            season_dirs = sorted([d for d in sdir.iterdir() if d.is_dir()])

            if season_dirs:
                # Normal: Serie/StaffelXX/*.mkv
                for season_dir in season_dirs:
                    season_num = parse_season_folder(season_dir.name)

                    for p in sorted(season_dir.iterdir()):
                        if not p.is_file():
                            continue
                        if p.suffix.lower() not in EXT:
                            continue

                        m = re.match(r"^(.*)\((\d{4})\)$", p.stem.strip())
                        if m:
                            title = m.group(1).strip()
                            year = m.group(2)
                        else:
                            title = p.stem.strip()
                            year = None

                        sc = parse_se_from_name(p.stem)
                        if sc:
                            season_num2, ep_num = sc
                            season_num = season_num2
                        else:
                            ep_num = infer_episode_index(season_dir, p)

                        ep_plot = ""
                        ep_title = title
                        ep_crew = ""

                        ep_path = str(p)
                        cur.execute("SELECT 1 FROM episodes WHERE path=?", (ep_path,))
                        exists = cur.fetchone()

                        if exists:
                            continue

                        if tmdb and int(season_num) > 0 and int(ep_num) > 0:
                            epinfo = fetch_tmdb_episode(int(tmdb["tmdb_id"]), int(season_num), int(ep_num))
                            if epinfo:
                                ep_plot = epinfo.get("plot", "") or ""
                                ep_crew = epinfo.get("crew", "") or ""
                                if epinfo.get("title"):
                                    ep_title = epinfo["title"]

                        ep_path = str(p)
                        cur.execute("SELECT 1 FROM episodes WHERE path=?", (ep_path,))
                        exists = cur.fetchone()

                        if not exists:
                            cur.execute(
                                "INSERT INTO episodes(id,series_id,season,episode,title,path,plot,crew) VALUES(?,?,?,?,?,?,?,?)",
                                (ep_id, current_series_id, int(season_num), int(ep_num), ep_title, ep_path, ep_plot, ep_crew)
                            )
                            ep_id += 1
                            ep_count += 1
            else:
                # Fallback: Serie/*.mkv  => Season 1
                season_num = 1
                files = sorted([p for p in sdir.iterdir() if p.is_file() and p.suffix.lower() in EXT])
                for idx, p in enumerate(files, start=1):

                    m = re.match(r"^(.*)\((\d{4})\)$", p.stem.strip())
                    if m:
                        title = m.group(1).strip()
                        year = m.group(2)
                    else:
                        title = p.stem.strip()
                        year = None

                    sc = parse_se_from_name(p.stem)
                    if sc:
                        season_num2, ep_num = sc
                        season_num = season_num2
                    else:
                        ep_num = idx

                    ep_plot = ""
                    ep_title = title
                    ep_crew = ""

                    if tmdb and int(season_num) > 0 and int(ep_num) > 0:
                            epinfo = fetch_tmdb_episode(int(tmdb["tmdb_id"]), int(season_num), int(ep_num))
                            if epinfo:
                                ep_plot = epinfo.get("plot", "") or ""
                                ep_crew = epinfo.get("crew", "") or ""
                                if epinfo.get("title"):
                                    ep_title = epinfo["title"]

                    ep_path = str(p)
                    cur.execute("SELECT 1 FROM episodes WHERE path=?", (ep_path,))
                    exists = cur.fetchone()

                    if not exists:
                        cur.execute(
                            "INSERT INTO episodes(id,series_id,season,episode,title,path,plot,crew) VALUES(?,?,?,?,?,?,?,?)",
                            (ep_id, current_series_id, int(season_num), int(ep_num), ep_title, ep_path, ep_plot, ep_crew)
                        )
                        ep_id += 1
                        ep_count += 1

            series_id += 1

    con.commit()
    con.close()

    print(f"[SCAN] SERIES fertig -> Serien={series_count} Episoden={ep_count}")
    return series_count, ep_count


def parse_season_folder(name: str) -> int:
    # "Staffel 1" / "Season 01" / "S01" / "01" -> 1
    m = re.search(r"(\d{1,2})", name)
    if m:
        return int(m.group(1))
    return 1


def parse_se_from_name(stem: str):
    # erkennt z.B.:
    # S01E02, s1e2, 1x02, S01_E02
    m = re.search(r"[sS](\d{1,2})\D*[eE](\d{1,3})", stem)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = re.search(r"\b(\d{1,2})x(\d{1,3})\b", stem)
    if m:
        return int(m.group(1)), int(m.group(2))

    return None


def infer_episode_index(season_dir: Path, p: Path) -> int:
    # fallback: Sortierung im Staffelordner
    files = [x for x in sorted(season_dir.iterdir())
             if x.is_file() and x.suffix.lower() in EXT]
    for i, x in enumerate(files, start=1):
        if x == p:
            return i
    return 1

# =========================
# LIVE TV KANÄLE IN DB
# =========================
def scan_live_tv_to_db(channels: List[Channel]) -> None:
    """
    Schreibt alle Live-TV Kanäle in die Xtream Datenbank
    Damit sie in player_api.php erscheinen
    """
    con = sqlite3.connect(VOD_DB)
    cur = con.cursor()

    # Tabelle für Live-TV erstellen (falls nicht vorhanden)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS live_streams (
            id INTEGER PRIMARY KEY,
            stream_id INTEGER UNIQUE,
            name TEXT,
            stream_type TEXT DEFAULT 'live',
            epg_channel_id TEXT,
            logo TEXT,
            category_id INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS live_categories (
            id INTEGER PRIMARY KEY,
            category_name TEXT,
            parent_id INTEGER DEFAULT 0
        )
    """)

    # Standard-Kategorie aus "BOUQUET_NAME" anlegen
    cur.execute("INSERT OR IGNORE INTO live_categories (id, category_name) VALUES (1, '{BOUQUET_NAME}')")

    # Alle Kanäle durchgehen und in DB eintragen
    stream_id = 1000  # Start-ID für Live-Streams
    for ch in channels:
        if ch.kind in ["video", "shuffle", "radio"]:
            # Prüfen ob Kanal schon existiert
            cur.execute("SELECT id FROM live_streams WHERE name = ?", (ch.name,))
            if not cur.fetchone():
                logo = str(ch.logo) if ch.logo else f"{PICONS_BASE_URL}/{ch.id}.png"

                cur.execute("""
                    INSERT INTO live_streams
                    (id, stream_id, name, epg_channel_id, logo, category_id)
                    VALUES (?, ?, ?, ?, ?, 1)
                """, (stream_id, stream_id, ch.name, ch.id, logo))

                print(f"[LIVE] {ch.name} in DB eingetragen")
                stream_id += 1

    con.commit()
    con.close()
    print(f"[LIVE] {stream_id -1000} Live-Kanäle in DB")

# =========================
# 7) VOD STACK ALL IN ONE (idempotent)
# =========================

def ensure_vod_stack() -> None:
    print("[VOD] ensure_vod_stack()")

    xstreamity_ok = (
        (VOD_WEBROOT / "player_api.php").exists()
        and VOD_DB.exists()
    )

    if xstreamity_ok:
        print("[VOD] XStreamity vorhanden -> überspringe Install")
    else:
        print("[VOD] XStreamity fehlt -> installiere + konfiguriere")

        ensure_system_deps()
        ensure_nginx_sites()
        ensure_vod_db()
        write_vod_web()
        print(f"[VOD] VOD_WEBROOT target = {VOD_WEBROOT}")
        print(f"[VOD] Web-files geschrieben: {VOD_WEBROOT} & {VOD_DB_DIR}")
        print(f"[SCAN] Starte Filme & Serien Scan...")

    # 🔁 DB & Scan IMMER

    scan_vod_sqlite()
    scan_series_sqlite()

def write_xtream_scan_script(script_path: Path, vod_db: Path, movie_roots, series_roots, tmdb_api_key) -> None:
    # movie_roots/series_roots: Liste aus Path-Objekten (oder Strings)
    script_path = Path(script_path)
    vod_db = Path(vod_db)

    def _p(x):
        return str(Path(x))

    vod_lines = []
    for p in movie_roots:
        vod_lines.append('    Path("%s"),' % _p(p))

    series_lines = []
    for p in series_roots:
        series_lines.append('    Path("%s"),' % _p(p))

    py = """#!/usr/bin/env python3
import os, re, sqlite3, time, json
from pathlib import Path

# optional requests (Scan soll auch ohne laufen)
try:
    import requests
except Exception:
    requests = None

DB = "{DB}"

VOD_ROOTS = [
{VOD_ROOTS}
]

SERIES_ROOTS = [
{SERIES_ROOTS}
]

EXT = {{".mkv", ".mp4", ".avi", ".mov", ".m4v"}}

TMDB_API_KEY       = {TMDB_API_KEY}
TMDB_BASE          = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE    = "https://image.tmdb.org/t/p/w500"

def ensure_columns(con, table, wanted_cols):
    cur = con.cursor()
    cur.execute(f"PRAGMA table_info({{table}})")
    existing = {{row[1] for row in cur.fetchall()}}  # name
    for col_name, col_type in wanted_cols:
        if col_name not in existing:
            cur.execute(f"ALTER TABLE {{table}} ADD COLUMN {{col_name}} {{col_type}}")
    con.commit()


def init_db(con):
    cur = con.cursor()
    # base tables
    cur.execute("CREATE TABLE IF NOT EXISTS vod (id INTEGER PRIMARY KEY, title TEXT, cat TEXT, path TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS series (id INTEGER PRIMARY KEY, name TEXT, cat TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS episodes (id INTEGER PRIMARY KEY, series_id INTEGER, season INTEGER, episode INTEGER, title TEXT, path TEXT, plot TEXT)")
    con.commit()

    # ensure tmdb columns (vod + series)
    ensure_columns(con, "vod", [
        ("tmdb_id", "INTEGER"),
        ("poster", "TEXT"),
        ("cast", "TEXT"),
        ("trailer", "TEXT"),
        ("backdrop", "TEXT"),
        ("plot", "TEXT"),
        ("rating", "REAL"),
        ("release_date", "TEXT"),
        ("director", "TEXT"),
        ("genre", "TEXT"),
        ("country", "TEXT"),
        ("o_name", "TEXT"),
        ("kinopoisk_url", "TEXT"),
    ])

    ensure_columns(con, "series", [
        ("tmdb_id", "INTEGER"),
        ("poster", "TEXT"),
        ("cast", "TEXT"),
        ("trailer", "TEXT"),
        ("backdrop", "TEXT"),
        ("plot", "TEXT"),
        ("rating", "REAL"),
        ("release_date", "TEXT"),
        ("director", "TEXT"),
        ("genre", "TEXT"),
        ("country", "TEXT"),
        ("o_name", "TEXT"),
        ("kinopoisk_url", "TEXT"),
    ])

    # make sure path cols exist (older DBs etc.)
    ensure_columns(con, "vod", [("path", "TEXT")])
    ensure_columns(con, "episodes", [("plot", "TEXT")])

    con.commit()


def clean_title(s: str) -> str:
    s = s.replace(".", " ").replace("_", " ").strip()
    # remove year like (1999) or 1999
    s = re.sub(r"\\((19\\d{{2}}|20\\d{{2}})\\)", "", s).strip()
    # remove extra spaces
    s = re.sub(r"\\s+", " ", s).strip()
    return s

def extract_tmdb_id(name: str):
    m = re.search(r"\\{{tmdb-(\\d+)\\}}", name, re.IGNORECASE)
    return m.group(1) if m else None

def strip_tmdb_tag(name: str):
    return re.sub(r"\\{{tmdb-\\d+\\}}", "", name, flags=re.IGNORECASE).strip()

def tmdb_search(kind: str, query: str, year: str | None = None):
    # kind: "movie" or "tv"
    if not TMDB_API_KEY or requests is None:
        return None
    try:
        url = f"{{TMDB_BASE}}/search/{{kind}}"
        params = {{
            "api_key": TMDB_API_KEY,
            "query": query,
            "include_adult": "false",
            "language": "de-DE",
        }}
        if year:
            params["year"] = year
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        results = data.get("results") or []
        if not results:
            return None
        return results[0]
    except Exception:
        return None

def fetch_tmdb_credits(tmdb_id, kind="movie"):
    try:
        endpoint = f"{{TMDB_BASE}}/{{kind}}/{{tmdb_id}}/credits"
        params = {{"api_key": TMDB_API_KEY, "language": "de-DE"}}
        r = requests.get(endpoint, params=params, timeout=10)
        if r.status_code != 200:
            return json.dumps([])
        data = r.json()
        cast_list = data.get("cast", [])
        result = []
        for actor in cast_list[:10]:
            profile_path = actor.get("profile_path")
            image_url = ""
            if profile_path:
                image_url = f"https://image.tmdb.org/t/p/w500{{profile_path}}"

            result.append({{
                "id": actor.get("id"),
                "name": actor.get("name", ""),
                "character": actor.get("character") or "",
                "profile_path": image_url
            }})
        return json.dumps(result, ensure_ascii=False)
    except Exception:
        return json.dumps([])

def fetch_tmdb_trailer(tmdb_id, kind="movie"):
    try:
        endpoint = f"{{TMDB_BASE}}/{{kind}}/{{tmdb_id}}/videos"
        params = {{"api_key": TMDB_API_KEY, "language": "de-DE"}}

        r = requests.get(endpoint, params=params, timeout=10)
        if r.status_code != 200:
            return ""
        data = r.json()
        results = data.get("results", [])

        if not results:
            params["language"] = "en-US"
            r = requests.get(endpoint, params=params, timeout=10)
            if r.status_code == 200:
                data = r.json()
                results = data.get("results", [])

        priority = {{"Trailer": 1, "Teaser": 2, "Featurette": 3, "Clip": 4}}

        sorted_videos = sorted(
            results,
            key=lambda x: (
                0 if x.get("official") else 1,
                priority.get(x.get("type", ""), 99),
                x.get("published_at", "")
            )
        )

        if sorted_videos:
            key = sorted_videos[0].get("key", "")
            site = sorted_videos[0].get("site", "YouTube")

            if site == "YouTube" and key:
                return key
            elif site == "Vimeo" and key:
                return f"https://vimeo.com/{{key}}"
        return ""
    except Exception:
        return ""

def tmdb_movie_info(title: str, year: str | None = None):
    q = clean_title(title)
    m = tmdb_search("movie", q, year)
    if not m:
        return None
    tmdb_id = m.get("id")
    kinopoisk_url = f"https://www.themoviedb.org/movie/{{tmdb_id}}"
    original_title = m.get("original_title", "") or ""

    detail = requests.get(
        f"{{TMDB_BASE}}/movie/{{tmdb_id}}",
        params={{"api_key": TMDB_API_KEY, "language": "de-DE"}},
        timeout=10
    ).json()

    credits = requests.get(
        f"{{TMDB_BASE}}/movie/{{tmdb_id}}/credits",
        params={{"api_key": TMDB_API_KEY, "language": "de-DE"}},
        timeout=10
    ).json()

    director = ""
    for person in credits.get("crew", []):
        if person.get("job") == "Director":
            director = person.get("name", "") or ""
            break

    genres = ", ".join([g.get("name","") for g in detail.get("genres", []) if g.get("name")])
    country = ", ".join([c.get("name","") for c in detail.get("production_countries", []) if c.get("name")])

    cast = fetch_tmdb_credits(tmdb_id, "movie")
    trailer = fetch_tmdb_trailer(tmdb_id, "movie")
    return {{
        "tmdb_id": tmdb_id,
        "poster": (TMDB_IMAGE_BASE + m["poster_path"]) if m.get("poster_path") else None,
        "backdrop": (TMDB_IMAGE_BASE + m["backdrop_path"]) if m.get("backdrop_path") else None,
        "plot": m.get("overview"),
        "rating": m.get("vote_average"),
        "release_date": m.get("release_date"),
        "cast": cast,
        "trailer": trailer,
        "director": director,
        "genre": genres,
        "country": country,
        "o_name": original_title,
        "kinopoisk_url": kinopoisk_url
    }}

def tmdb_movie_info_by_id(tmdb_id: str):
    kinopoisk_url = f"https://www.themoviedb.org/movie/{{tmdb_id}}"

    detail = requests.get(
        f"{{TMDB_BASE}}/movie/{{tmdb_id}}",
        params={{"api_key": TMDB_API_KEY, "language": "de-DE"}},
        timeout=10
    ).json()

    if not detail or detail.get("success") is False:
        return None

    credits = requests.get(
        f"{{TMDB_BASE}}/movie/{{tmdb_id}}/credits",
        params={{"api_key": TMDB_API_KEY, "language": "de-DE"}},
        timeout=10
    ).json()

    director = ""
    for person in credits.get("crew", []):
        if person.get("job") == "Director":
            director = person.get("name", "") or ""
            break

    genres = ", ".join(
        g.get("name", "") for g in detail.get("genres", []) if g.get("name")
    )

    countries = ", ".join(
        c.get("name", "") for c in detail.get("production_countries", []) if c.get("name")
    )

    cast = fetch_tmdb_credits(int(tmdb_id), "movie")
    trailer = fetch_tmdb_trailer(int(tmdb_id), "movie")

    return {{
        "tmdb_id": int(tmdb_id),
        "poster": (TMDB_IMAGE_BASE + detail["poster_path"]) if detail.get("poster_path") else "",
        "backdrop": (TMDB_IMAGE_BASE + detail["backdrop_path"]) if detail.get("backdrop_path") else "",
        "plot": detail.get("overview", "") or "",
        "rating": str(detail.get("vote_average", "") or ""),
        "release_date": detail.get("release_date", "") or "",
        "cast": cast,
        "trailer": trailer,
        "director": director,
        "genre": genres,
        "country": countries,
        "o_name": detail.get("original_title", "") or "",
        "kinopoisk_url": kinopoisk_url,
    }}

def fetch_tmdb_by_id(tmdb_id: str):
    try:
        kinopoisk_url = f"https://www.themoviedb.org/movie/{{tmdb_id}}"

        detail = requests.get(
            f"https://api.themoviedb.org/3/movie/{{tmdb_id}}",
            params={{"api_key": TMDB_API_KEY, "language": TMDB_LANG}},
            timeout=10
        ).json()

        if not detail or detail.get("success") is False:
            return None

        credits = requests.get(
            f"https://api.themoviedb.org/3/movie/{{tmdb_id}}/credits",
            params={{"api_key": TMDB_API_KEY, "language": TMDB_LANG}},
            timeout=10
        ).json()

        director = ""
        for person in credits.get("crew", []):
            if person.get("job") == "Director":
                director = person.get("name", "") or ""
                break

        genres = ", ".join(
            g.get("name", "") for g in detail.get("genres", []) if g.get("name")
        )

        countries = ", ".join(
            c.get("name", "") for c in detail.get("production_countries", []) if c.get("name")
        )

        cast = fetch_tmdb_credits(int(tmdb_id), "movie")
        trailer = fetch_tmdb_trailer(int(tmdb_id), "movie")

        return {{
            "tmdb_id": int(tmdb_id),
            "poster": (TMDB_IMAGE_BASE + "w500" + detail["poster_path"]) if detail.get("poster_path") else "",
            "backdrop": (TMDB_IMAGE_BASE + "w780" + detail["backdrop_path"]) if detail.get("backdrop_path") else "",
            "plot": detail.get("overview", "") or "",
            "rating": str(detail.get("vote_average", "") or ""),
            "release_date": detail.get("release_date", "") or "",
            "cast": cast,
            "trailer": trailer,
            "director": director,
            "genre": genres,
            "country": countries,
            "o_name": detail.get("original_title", "") or "",
            "kinopoisk_url": kinopoisk_url,
        }}
    except Exception:
        return None

def tmdb_tv_info(name: str):
    q = clean_title(name)
    m = tmdb_search("tv", q)
    if not m:
        return None
    tmdb_id = m.get("id")
    kinopoisk_url = f"https://www.themoviedb.org/movie/{{tmdb_id}}"
    original_name = m.get("original_name", "") or ""

    detail = requests.get(
        f"{{TMDB_BASE}}/tv/{{tmdb_id}}",
        params={{"api_key": TMDB_API_KEY, "language": "de-DE"}},
        timeout=10
    ).json()

    credits = requests.get(
        f"{{TMDB_BASE}}/tv/{{tmdb_id}}/credits",
        params={{"api_key": TMDB_API_KEY, "language": "de-DE"}},
        timeout=10
    ).json()

    director = ""
    creators = detail.get("created_by", []) or []
    if creators:
        director = creators[0].get("name", "") or ""
    else:
        for person in credits.get("crew", []):
            if person.get("job") in ("Executive Producer", "Director"):
                director = person.get("name", "") or ""
                break

    genres = ", ".join([g.get("name","") for g in detail.get("genres", []) if g.get("name")])
    country = ", ".join(detail.get("origin_country", []) or [])

    cast = fetch_tmdb_credits(tmdb_id, "tv")
    trailer = fetch_tmdb_trailer(tmdb_id, "tv")
    return {{
        "tmdb_id": tmdb_id,
        "poster": (TMDB_IMAGE_BASE + m["poster_path"]) if m.get("poster_path") else None,
        "backdrop": (TMDB_IMAGE_BASE + m["backdrop_path"]) if m.get("backdrop_path") else None,
        "plot": m.get("overview"),
        "rating": m.get("vote_average"),
        "release_date": m.get("first_air_date"),
        "cast": cast,
        "trailer": trailer,
        "director": director,
        "genre": genres,
        "country": country,
        "o_name": original_name,
        "kinopoisk_url": kinopoisk_url
    }}

def fetch_tmdb_episode(tmdb_id: int, season: int, episode: int):
    try:
        url = f"https://api.themoviedb.org/3/tv/{{tmdb_id}}/season/{{season}}/episode/{{episode}}"
        params = {{"api_key": TMDB_API_KEY, "language": TMDB_LANG}}
        data = requests.get(url, params=params, timeout=10).json()

        credits_url = f"https://api.themoviedb.org/3/tv/{{tmdb_id}}/season/{{season}}/episode/{{episode}}/credits"
        credits = requests.get(credits_url, params=params, timeout=10).json()

        crew_names = []
        for item in credits.get("crew", []):
            name = str(item.get("name", "")).strip()
            if name and name not in crew_names:
                crew_names.append(name)

        crew_string = ", ".join(crew_names[:5])

        return {{
            "title": data.get("name", "") or "",
            "plot": data.get("overview", "") or "",
            "air_date": data.get("air_date", "") or "",
            "crew": crew_string,
        }}
    except Exception:
        return None

def scan_vod():
    vod = []
    for root in VOD_ROOTS:
        if not root.is_dir():
            continue
        for catdir in sorted(root.iterdir()):
            if not catdir.is_dir():
                continue
            cat = catdir.name
            for f in sorted(catdir.glob("*")):
                if f.is_file() and f.suffix.lower() in EXT:
                    m2 = re.match(r"^(.*)\((\d{{4}})\)$", f.stem.strip())
                    if m2:
                        title = m2.group(1).strip()
                        year = m2.group(2)
                    else:
                        title = f.stem.strip()
                        year = None
                    vod.append((title, year, cat, str(f)))
    return vod


ep_re = re.compile(r"S(\\d{{1,2}})E(\\d{{1,2}})", re.I)

def scan_series():
    series = []
    episodes = []
    for root in SERIES_ROOTS:
        if not root.is_dir():
            continue
        for sdir in sorted(root.iterdir()):
            if not sdir.is_dir():
                continue
            sname = sdir.name
            cat = "Series"
            series.append((sname, cat))

            files = sorted([p for p in sdir.rglob("*") if p.is_file() and p.suffix.lower() in EXT])
            for p in files:
                m = ep_re.search(p.stem)
                if m:
                    season = int(m.group(1))
                    ep = int(m.group(2))
                else:
                    season = 1
                    ep = 0

                m2 = re.match(r"^(.*)\((\d{{4}})\)$", p.stem.strip())
                if m2:
                    title = m2.group(1).strip()
                    year = m2.group(2)
                else:
                    title = p.stem.strip()
                    year = None
                episodes.append((sname, season, ep, title, str(p)))
    return series, episodes


def next_id(cur, table: str) -> int:
    cur.execute(f"SELECT COALESCE(MAX(id),0) FROM {{table}}")
    return int(cur.fetchone()[0] or 0) + 1


def main():
    con = sqlite3.connect(DB)
    init_db(con)
    cur = con.cursor()

    new_vod = 0
    new_series = 0
    new_eps = 0

    # --- VOD: only insert new by path ---
    vod = scan_vod()
    for (title, year, cat, path) in vod:
        cur.execute("SELECT id FROM vod WHERE path=? LIMIT 1", (path,))
        if cur.fetchone():
            continue  # already known
        vid = next_id(cur, "vod")
        tmdb_id_tag = extract_tmdb_id(title)
        clean_title_db = clean_title(strip_tmdb_tag(title))

        if tmdb_id_tag:
            info = tmdb_movie_info_by_id(tmdb_id_tag)
        else:
            info = tmdb_movie_info(clean_title_db, year)
        if info:
            cur.execute(
                "INSERT INTO vod(id,title,o_name,kinopoisk_url,cat,path,tmdb_id,poster,backdrop,plot,rating,release_date,cast,trailer,director,genre,country) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (vid, clean_title_db, info.get("o_name", ""), info.get("kinopoisk_url", ""), cat, path, info["tmdb_id"], info["poster"], info["backdrop"], info["plot"], info["rating"], info["release_date"], info.get("cast", ""), info.get("trailer", ""), info.get("director", ""), info.get("genre", ""),info.get("country", ""))
            )
        else:
            cur.execute(
                "INSERT INTO vod(id,clean_title_db,o_name,cat,path) VALUES(?,?,?,?,?)",
                (vid, title, "", cat, path)
            )
        new_vod += 1
        time.sleep(0.05)

    # --- SERIES: only insert new series by name ---
    series, episodes = scan_series()

    name_to_id = {{}}
    cur.execute("SELECT id, name, tmdb_id FROM series")
    name_to_meta = {{r[1]: {{"id": r[0], "tmdb_id": r[2]}} for r in cur.fetchall()}}

    for (name, cat) in series:
        if name in name_to_meta:
            continue

        sid = next_id(cur, "series")
        info = tmdb_tv_info(name)

        if info:
            cur.execute(
                "INSERT INTO series(id,name,o_name,kinopoisk_url,cat,tmdb_id,poster,backdrop,plot,rating,release_date,cast,trailer,director,genre,country) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, name, info.get("o_name", ""), info.get("kinopoisk_url", ""), cat, info["tmdb_id"], info["poster"], info["backdrop"], info["plot"], info["rating"], info["release_date"], info.get("cast", ""), info.get("trailer", ""), info.get("director", ""), info.get("genre", ""), info.get("country", ""))
            )
            tmdb_id = info["tmdb_id"]
        else:
            cur.execute("INSERT INTO series(id,name,o_name,cat) VALUES(?,?,?,?)", (sid, name, "", cat))
            tmdb_id = None

        name_to_meta[name] = {{"id": sid, "tmdb_id": tmdb_id}}
        new_series += 1
        time.sleep(0.05)
        new_series += 1
        time.sleep(0.05)

    # --- EPISODES: only insert new by path ---
    for (sname, season, epnum, title, path) in episodes:
        meta = name_to_meta.get(sname)
        if not meta:
            continue

        sid = meta["id"]
        series_tmdb_id = meta["tmdb_id"]

        cur.execute("SELECT id FROM episodes WHERE path=? LIMIT 1", (path,))
        if cur.fetchone():
            continue

        eid = next_id(cur, "episodes")

        ep_plot = ""
        ep_title = title
        ep_crew = ""

        if series_tmdb_id and season > 0 and epnum > 0:
            epinfo = fetch_tmdb_episode(series_tmdb_id, season, epnum)
            if epinfo:
                ep_plot = epinfo.get("plot", "") or ""
                ep_crew = epinfo.get("crew", "") or ""
                if epinfo.get("title"):
                    ep_title = epinfo["title"]

        cur.execute(
            "INSERT INTO episodes(id,series_id,season,episode,title,path,plot,crew) VALUES(?,?,?,?,?,?,?,?)",
            (eid, sid, season, epnum, ep_title, path, ep_plot, ep_crew)
        )
        new_eps += 1
        time.sleep(0.05)

    con.commit()
    con.close()

    print("OK NEW_VOD=%d NEW_SERIES=%d NEW_EPISODES=%d" % (new_vod, new_series, new_eps))


if __name__ == "__main__":
    main()
""".format(
        DB=str(vod_db),
        TMDB_API_KEY=repr(tmdb_api_key),
        VOD_ROOTS="\n".join(vod_lines),
        SERIES_ROOTS="\n".join(series_lines),
    )

    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(py, encoding="utf-8")
    os.chmod(str(script_path), 0o755)

def write_xtream_cron(cron_path: Path, scan_script: Path) -> None:
    cron_path = Path(cron_path)
    scan_script = Path(scan_script)

    if cron_path.exists():
        return

    cron = "*/5 * * * * root {script} >> /var/log/xtream_scan.log 2>&1\n".format(
        script=str(scan_script)
    )
    cron_path.parent.mkdir(parents=True, exist_ok=True)
    cron_path.write_text(cron, encoding="utf-8")

def write_factory_weekly_script():
    script = Path("/usr/local/bin/tv_factory_weekly.sh")

    if script.exists():
        print("[SKIP] tv_factory_weekly.sh already exists")
        return

    content = """#!/bin/bash
set -euo pipefail

LOCK="/tmp/tv_factory.lock"
LOG="/var/log/tv_factory_weekly.log"

exec 9>"$LOCK"
flock -n 9 || exit 0

{
echo "=== $(date) weekly rebuild start ==="

# optional: systemctl stop nginx
# optional: rm -f /var/lib/xtream/xtream.db
systemctl stop 'iptv*' 2>/dev/null || true
pkill -9 ffmpeg || true
rm -f /etc/systemd/system/iptv*
rm -f /etc/systemd/system/multi-user.target.wants/iptv*
rm -f /usr/local/bin/iptv*.sh
rm -rf /srv/media_hdd/playlists
rm -rf /srv/media_hdd/state
rm -f /srv/media_hdd/hls/epg_all.xml
rm -rf /srv/media_hdd/hls/*
systemctl daemon-reload

python3 /usr/local/bin/tv_factory.py

# systemctl start nginx

echo "=== $(date) weekly rebuild done ==="
} >> "$LOG" 2>&1
"""

    script.write_text(content)
    script.chmod(0o755)

    print("[SH] tv_factory_weekly.sh created")


def write_factory_weekly_cron():
    cron_line = "3 3 * * 1 root /usr/local/bin/tv_factory_weekly.sh >> /var/log/tv_factory_weekly.log 2>&1"
    cron_file = Path("/etc/cron.d/tv_factory_weekly")

    if cron_file.exists():
        print("[SKIP] weekly cron already exists")
        return

    cron_file.write_text(
        f"{cron_line}\n"
    )

    print("[CRON] weekly factory cron installed")

def write_hls_cleanup_cron(cron_path: Path) -> None:
    cron_path = Path(cron_path)

    if cron_path.exists():
        print(f"[CRON] exists, skip: {cron_path}")
        return

    content = """SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

*/10 * * * * root find /srv/media_hdd/hls -type f -name "*.ts" -mmin +5 -delete
"""

    cron_path.write_text(content, encoding="utf-8")
    # Rechte sind bei cron.d wichtig:
    cron_path.chmod(0o644)
    print(f"[CRON] created: {cron_path}")

def write_log_cleanup_cron(cron_path: Path) -> None:
    cron_path = Path(cron_path)

    if cron_path.exists():
        print(f"[CRON] log clean exists, skip: {cron_path}")
        return

    content = """SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

*/30 * * * * root ls /var/log/ffmpeg_*.log 1>/dev/null 2>&1 && \
for f in /var/log/ffmpeg_*.log; do \
  tail -n 1500 "$f" > "$f.tmp" && mv "$f.tmp" "$f"; \
done

0 4 * * * root find /var/log -name "ffmpeg_*.log" -mtime +7 -delete
"""

    cron_path.write_text(content, encoding="utf-8")
    # Rechte sind bei cron.d wichtig:
    cron_path.chmod(0o644)
    print(f"[CRON] log clean: created")

def ensure_vod_tmdb_columns(con: sqlite3.Connection) -> None:
    cur = con.cursor()
    cur.execute("PRAGMA table_info(vod)")
    cols = {r[1] for r in cur.fetchall()}

    want = [
        ("tmdb_id", "INTEGER"),
        ("poster", "TEXT"),
        ("backdrop", "TEXT"),
        ("plot", "TEXT"),
        ("rating", "TEXT"),
        ("release_date", "TEXT"),
        ("cast", "TEXT"),
        ("trailer", "TEXT"),  # NEU
    ]
    for name, typ in want:
        if name not in cols:
            cur.execute(f"ALTER TABLE vod ADD COLUMN {name} {typ}")
    con.commit()

def ensure_series_tmdb_columns(con: sqlite3.Connection) -> None:
    cur = con.cursor()
    cur.execute("PRAGMA table_info(series)")
    cols = {r[1] for r in cur.fetchall()}

    want = [
        ("tmdb_id", "INTEGER"),
        ("poster", "TEXT"),
        ("backdrop", "TEXT"),
        ("plot", "TEXT"),
        ("rating", "TEXT"),
        ("release_date", "TEXT"),
        ("cast", "TEXT"),
        ("trailer", "TEXT"),  # NEU
    ]
    for name, typ in want:
        if name not in cols:
            cur.execute(f"ALTER TABLE series ADD COLUMN {name} {typ}")
    con.commit()

def write_live_map_json(channels: list[Channel], start_id: int = 1000) -> Path:
    """
    Mappt numerische Live-IDs (1000,1001,...) auf echte channel ids (moviemixuhd,...)
    """
    out = BASE_HLS / "live_map.json"
    mapping = {}
    sid = start_id
    for ch in channels:
        # mapping nur für live video/radio (alles was als "live" rausgeht)
        mapping[str(sid)] = ch.id
        sid += 1
    write_text(out, json.dumps(mapping, ensure_ascii=False, indent=2) + "\n")
    return out

def main() -> None:
    if os.geteuid() != 0:
        die("Als root ausführen: sudo /usr/local/bin/tv_factory.py")

    ensure_vod_stack()

    all_movie_roots = list(MOVIE_ROOTS) + list(X_MOVIE_ROOTS)
    all_series_roots = list(SERIES_ROOTS) + list(X_SERIES_ROOTS)

    scan_script = Path("/usr/local/bin/xtream_scan.py")
    write_xtream_scan_script(
        script_path=scan_script,
        vod_db=Path("/var/lib/xtream/xtream.db"),
        movie_roots=all_movie_roots,
        series_roots=all_series_roots,
        tmdb_api_key=TMDB_API_KEY,
    )

    write_xtream_cron(
        cron_path=Path("/etc/cron.d/xtream_scan"),
        scan_script=scan_script,
    )

    write_factory_weekly_script()
    write_factory_weekly_cron()
    write_hls_cleanup_cron(Path("/etc/cron.d/hls_cleanup"))
    write_log_cleanup_cron(Path("/etc/cron.d/log_cleanup"))

    ensure_dir(BASE_HLS)
    ensure_dir(BASE_STATE)
    ensure_dir(BASE_PLAY)

    # HLS aufräumen
    for p in BASE_HLS.glob("*.ts"):
        p.unlink(missing_ok=True)
    for p in BASE_HLS.glob("*.m3u8"):
        p.unlink(missing_ok=True)

    channels: List[Channel] = []
    list_files: dict[str, Path] = {}
    channels_created: List[str] = []

    # ===== 1. RADIO CHANNELS =====
    for r in RADIOS:
        url = read_url(r["url_txt"])
        ch = Channel(
            id=r["id"],
            name=r["name"],
            kind="radio",
            logo=r["logo"],
            background=r.get("background"),
            radio_url=url,
        )
        channels.append(ch)

    # ===== 2. SCAN MOVIES/SERIES =====
    movie_dirs = find_media_dirs(MOVIE_ROOTS)
    series_dirs = find_media_dirs(SERIES_ROOTS)

    # ===== 3. SHUFFLE-CHANNELS =====
    for cfg in SHUFFLES:
        scope = str(cfg.get("scope", "both"))
        recursive = bool(cfg.get("recursive", False))
        names = set(cfg.get("dir_names", set()))

        src_dirs = []
        if scope in ("movies", "both"):
            src_dirs += movie_dirs
        if scope in ("series", "both"):
            src_dirs += series_dirs

        pool = []
        for d in src_dirs:
            if match_any(d, names):
                if recursive:
                    pool.extend(collect_videos_recursive(d))
                else:
                    pool.extend(collect_videos_in_dir(d))

        if pool:
            sh = Channel(
                id=cfg["id"],
                name=cfg["name"],
                kind="shuffle",
                files=pool,
            )
            channels.append(sh)

    # ===== 4. MOVIE CHANNELS =====
    for d in movie_dirs:
        if is_shuffle_source_dir(d):
            continue
        files = collect_videos_in_dir(d)
        if d.name in SORT_BY_YEAR_DIRS:
            files.sort(key=lambda p: (extract_year(p), natural_key))
        if not files:
            continue
        ch = Channel(
            id=slugify(d.name),
            name=d.name,
            kind="video",
            logo=detect_logo_in_dir(d),
            files=files,
        )
        channels.append(ch)

    # ===== 5. SERIES CHANNELS =====
    for d in series_dirs:
        if is_shuffle_source_dir(d):
            continue
        files = collect_videos_in_dir(d)
        if not files:
            continue
        ch = Channel(
            id=slugify(d.name),
            name=d.name,
            kind="video",
            logo=detect_logo_in_dir(d),
            files=files,
        )
        channels.append(ch)

    # ===== 6. ALLE KANÄLE VORBEREITEN (Dateilisten + Runner + Service-Dateien) =====
    print(f"\n[INFO] Bereite {len(channels)} Kanäle vor...")

    for ch in channels:
        if ch.kind == "radio":
            runner = write_radio_runner(ch)
            write_service(ch.id, ch.name, runner)
            channels_created.append(ch.id)
            print(f"  → {ch.id} (Radio) vorbereitet")
        else:
            if ch.kind == "shuffle":
                lf = write_shuffle_list_file(ch.id, ch.files)
            else:
                lf = write_video_list_file(ch.id, ch.files)
            list_files[ch.id] = lf
            runner = write_video_runner(ch, lf)
            write_service(ch.id, ch.name, runner)
            channels_created.append(ch.id)
            print(f"  → {ch.id} (Video) vorbereitet")

    # ===== 7. SYSTEMD RELOAD (vor dem Start) =====
    run(["/bin/systemctl", "daemon-reload"], check=False)

    # ===== 8. SYNCHRONISIERTER START ALLER KANÄLE =====
    print("\n" + "=" * 60)
    print("[SYNC] Warte auf nächste volle Minute für Kanalstart...")

    now = datetime.now()
    next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    wait_seconds = (next_minute - now).total_seconds()

    print(f"  Aktuelle Zeit: {now.strftime('%H:%M:%S')}")
    print(f"  Start um:      {next_minute.strftime('%H:%M:%S')}")
    print(f"  Warte {wait_seconds:.1f} Sekunden...")

    time.sleep(max(0, wait_seconds))

    print(f"\n[SYNC] Starte alle {len(channels_created)} Kanäle UM {next_minute.strftime('%H:%M:%S')}:")
    for ch_id in channels_created:
        enable_service(ch_id)
        print(f"  ✅ {ch_id} gestartet")
    print("=" * 60 + "\n")

    # ===== 9. EPG JETZT GENERIEREN (state.json existiert durch gestartete Kanäle) =====
    print("[LIVE] Befülle DB mit Live Channels ")
    scan_live_tv_to_db(channels)
    write_m3u(channels)
    write_m3u_with_auth(channels)
    write_live_map_json(channels, start_id=1000)

    print("[EPG] Warte 5 Sekunden, damit Services/State sauber bereit sind...")
    time.sleep(5)

    print("[EPG] Generiere EPG mit Start aus state.json Daten. Dauer aus logs, falls vorhanden, falls nicht vorhanden, ffprobe")
    write_epg(channels, list_files)
    write_xmltv_epg()
    print("[EPG] Fertig.\n")



    print("")
    print("")
    print("")
    print("[FACTORY] .")
    print("[FACTORY] . . ")
    print("[FACTORY] . . .")
    print("[FACTORY] Setup Check: All required programs are installed, and running")
    print("[FACTORY] CRON & Script Setup: VOD Scan every 5 min")
    print("[FACTORY] CRON & Script Setup: Weekly Factory for EPG Rebuild every Sunday Night 03:03")
    print("[FACTORY] CRON: HLS Cleanup every 10 min")
    print(f"[FACTORY] HLS: {BASE_HLS}")
    print(f"[FACTORY] M3U: {BASE_HLS/'iptv.m3u'}")
    print(f"[FACTORY] EPG: {BASE_HLS/'epg_all.xml'}")
    print(f"[FACTORY] NGINX: {IPTV_NAME} OK on :{IPTV_PORT}")
    print(f"[FACTORY] NGINX: {VOD_NAME} OK on : {VOD_PORT}")
    print(f"[FACTORY] EPG: Rebuild for: {DAYS_AHEAD} - Days")
    print("[FACTORY] Finish")
    print("[FACTORY] . . .")
    print("[FACTORY] . . ")
    print("[FACTORY] .")
    print("[FACTORY] ✅ TV Factory Ready... Job Done")


if __name__ == "__main__":
    main()




