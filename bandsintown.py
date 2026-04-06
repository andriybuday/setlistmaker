import requests
from datetime import datetime
from typing import Optional

BANDSINTOWN_BASE = "https://rest.bandsintown.com"


def get_lineup(artist_name: str, event_date: str, app_id: str) -> Optional[list[str]]:
    """
    Find the lineup for a headliner's show on or near event_date.

    event_date: YYYY-MM-DD
    Returns list of band names with support acts first, headliner last.
    Returns None if no matching event found.
    """
    encoded = requests.utils.quote(artist_name, safe="")
    try:
        resp = requests.get(
            f"{BANDSINTOWN_BASE}/artists/{encoded}/events",
            params={"app_id": app_id, "date": "upcoming"},
            timeout=10,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Network error contacting BandsInTown: {e}")

    if resp.status_code in (404, 400):
        return None
    if not resp.ok:
        raise RuntimeError(f"BandsInTown returned {resp.status_code}")

    events = resp.json()
    if not isinstance(events, list) or not events:
        return None

    target = datetime.strptime(event_date, "%Y-%m-%d").date()

    for event in events:
        try:
            dt_str = event.get("datetime", "")
            event_dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00")).date()
        except (ValueError, AttributeError):
            continue

        if abs((event_dt - target).days) <= 1:
            lineup: list[str] = event.get("lineup", [])
            if not lineup:
                continue
            # BandsInTown usually lists headliner first — move searched artist to end
            headliner_normalized = artist_name.lower().strip()
            lineup_normalized = [b.lower().strip() for b in lineup]
            if headliner_normalized in lineup_normalized:
                idx = lineup_normalized.index(headliner_normalized)
                headliner_entry = lineup.pop(idx)
                lineup.append(headliner_entry)
            return lineup

    return None
