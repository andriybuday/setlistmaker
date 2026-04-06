import requests
from datetime import datetime
from typing import Optional

SETLISTFM_BASE = "https://api.setlist.fm/rest/1.0"


def _headers(api_key: str) -> dict:
    return {
        "x-api-key": api_key,
        "Accept": "application/json",
    }


def _parse_date(date_str: str) -> datetime:
    """setlist.fm returns dates as DD-MM-YYYY."""
    return datetime.strptime(date_str, "%d-%m-%Y")


def _extract_songs(setlist: dict) -> list[str]:
    songs = []
    for section in setlist.get("sets", {}).get("set", []):
        for song in section.get("song", []):
            name = song.get("name", "").strip()
            if name:
                songs.append(name)
    return songs


def search_artists(name: str, api_key: str, limit: int = 3) -> list[str]:
    """
    Return up to `limit` artist name suggestions from setlist.fm for a given query.
    Useful for surfacing the correct name when a typo returns no setlist.
    """
    try:
        resp = requests.get(
            f"{SETLISTFM_BASE}/search/artists",
            params={"artistName": name, "p": 1, "sort": "relevance"},
            headers=_headers(api_key),
            timeout=10,
        )
    except requests.RequestException:
        return []

    if not resp.ok:
        return []

    artists = resp.json().get("artist", [])
    return [a["name"] for a in artists[:limit] if "name" in a]


def get_most_recent_setlist(
    artist_name: str, before_date: str, api_key: str
) -> Optional[dict]:
    """
    Return the most recent setlist for an artist that occurred before before_date.

    before_date: YYYY-MM-DD
    Returns a dict with keys: songs, date, venue, city, url
    Returns None if nothing found.
    """
    cutoff = datetime.strptime(before_date, "%Y-%m-%d")

    for page in range(1, 4):  # max 3 pages to avoid hammering the API
        try:
            resp = requests.get(
                f"{SETLISTFM_BASE}/search/setlists",
                params={"artistName": artist_name, "p": page},
                headers=_headers(api_key),
                timeout=10,
            )
        except requests.RequestException as e:
            raise RuntimeError(f"Network error fetching setlists for {artist_name}: {e}")

        if resp.status_code == 404:
            return None
        if resp.status_code == 429:
            raise RuntimeError("setlist.fm rate limit hit — wait a moment and try again.")
        if not resp.ok:
            raise RuntimeError(f"setlist.fm returned {resp.status_code} for {artist_name}")

        data = resp.json()
        setlists = data.get("setlist", [])

        if not setlists:
            break

        for setlist in setlists:
            try:
                show_date = _parse_date(setlist["eventDate"])
            except (KeyError, ValueError):
                continue

            if show_date >= cutoff:
                continue  # skip shows on/after the event date

            songs = _extract_songs(setlist)
            if not songs:
                continue  # skip empty setlists (soundcheck-only, etc.)

            venue = setlist.get("venue", {})
            city = venue.get("city", {})

            return {
                "songs": songs,
                "date": setlist["eventDate"],  # DD-MM-YYYY
                "venue": venue.get("name", ""),
                "city": city.get("name", ""),
                "country": city.get("country", {}).get("name", ""),
                "url": setlist.get("url", ""),
            }

    return None
