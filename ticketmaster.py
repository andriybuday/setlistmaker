import requests
from datetime import datetime, timedelta
from typing import Optional

TICKETMASTER_BASE = "https://app.ticketmaster.com/discovery/v2"


def get_lineup(artist_name: str, event_date: str, api_key: str) -> Optional[list[str]]:
    """
    Find the lineup for an artist's show on event_date via Ticketmaster Discovery API.

    event_date: YYYY-MM-DD
    Returns band names with support acts first, headliner last. None if not found.
    """
    target = datetime.strptime(event_date, "%Y-%m-%d")
    start = (target - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    end = (target + timedelta(days=1)).strftime("%Y-%m-%dT23:59:59Z")

    try:
        resp = requests.get(
            f"{TICKETMASTER_BASE}/events.json",
            params={
                "keyword": artist_name,
                "classificationName": "music",
                "startDateTime": start,
                "endDateTime": end,
                "apikey": api_key,
                "size": 5,
            },
            timeout=10,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Network error contacting Ticketmaster: {e}")

    if resp.status_code == 401:
        raise RuntimeError("Invalid Ticketmaster API key.")
    if not resp.ok:
        raise RuntimeError(f"Ticketmaster returned {resp.status_code}")

    events = resp.json().get("_embedded", {}).get("events", [])
    if not events:
        return None

    for event in events:
        attractions = event.get("_embedded", {}).get("attractions", [])
        names = [a["name"] for a in attractions if "name" in a]
        if not names:
            continue

        # Ticketmaster lists headliner first — move the searched artist to last
        artist_lower = artist_name.lower()
        headliner = next((n for n in names if n.lower() == artist_lower), None)
        if headliner:
            others = [n for n in names if n.lower() != artist_lower]
            return others + [headliner]
        return names  # couldn't identify headliner, return as-is

    return None
