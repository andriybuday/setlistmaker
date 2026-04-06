import streamlit as st
from datetime import date
from setlistfm import get_most_recent_setlist
from bandsintown import get_lineup

st.set_page_config(page_title="SetlistMaker", page_icon="🎸", layout="centered")

st.title("🎸 SetlistMaker")
st.caption("Look up tonight's setlists and generate a YouTube Music playlist via Gemini.")

# ─── API keys ─────────────────────────────────────────────────────────────────

try:
    setlistfm_key = st.secrets["SETLISTFM_API_KEY"]
except (KeyError, FileNotFoundError):
    st.error("**Missing API key.** Add `SETLISTFM_API_KEY` to your Streamlit secrets.")
    st.stop()

bit_key: str | None = st.secrets.get("BANDSINTOWN_APP_ID")

# ─── Step 1: Event details ────────────────────────────────────────────────────

st.subheader("Event details")

col1, col2 = st.columns([2, 1])
headliner = col1.text_input("Headliner", placeholder="Metallica")
event_date = col2.date_input("Event date", value=date.today())
event_venue = st.text_input("Venue", placeholder="Madison Square Garden, New York")

# Session state for lineup pre-fill
if "lineup_version" not in st.session_state:
    st.session_state["lineup_version"] = 0
if "bands_default" not in st.session_state:
    st.session_state["bands_default"] = ""
if "lineup_msg" not in st.session_state:
    st.session_state["lineup_msg"] = None  # (type, text) tuple

# "Find Lineup" button — only shown when BandsInTown is configured
if bit_key:
    if st.button("Find Lineup →", disabled=not headliner.strip()):
        with st.spinner(f"Looking up lineup for {headliner}…"):
            try:
                lineup = get_lineup(headliner.strip(), event_date.strftime("%Y-%m-%d"), bit_key)
            except RuntimeError as e:
                lineup = None
                st.session_state["lineup_msg"] = ("warning", str(e))

        if lineup:
            st.session_state["bands_default"] = "\n".join(lineup)
            st.session_state["lineup_version"] += 1
            st.session_state["lineup_msg"] = (
                "success",
                f"Found **{len(lineup)} act(s)** for {headliner} on {event_date.strftime('%b %d %Y')}. "
                "Edit below if needed.",
            )
        else:
            st.session_state["lineup_msg"] = (
                "info",
                "No lineup found on BandsInTown for that date. Enter bands manually.",
            )

    msg = st.session_state["lineup_msg"]
    if msg:
        kind, text = msg
        {"success": st.success, "info": st.info, "warning": st.warning}[kind](text)
else:
    st.caption("💡 Add `BANDSINTOWN_APP_ID` to secrets to enable automatic lineup lookup.")

# Bands textarea — pre-filled when a lineup is found, always editable
bands_raw = st.text_area(
    "Bands — one per line, support acts first, headliner last",
    value=st.session_state["bands_default"],
    key=f"bands_raw_{st.session_state['lineup_version']}",
    placeholder="Mammoth WVH\nMetallica",
    height=130,
)

fetch_btn = st.button(
    "Fetch Setlists →",
    type="primary",
    disabled=not bands_raw.strip(),
)

if fetch_btn:
    bands = [b.strip() for b in bands_raw.strip().splitlines() if b.strip()]

    # Clear previous results
    for key in ["setlists", "bands", "event_name", "event_date_str"]:
        st.session_state.pop(key, None)

    date_str = event_date.strftime("%Y-%m-%d")
    results = {}

    progress = st.progress(0, text="Fetching setlists…")
    for i, band in enumerate(bands):
        progress.progress((i + 1) / len(bands), text=f"Looking up {band}…")
        try:
            results[band] = get_most_recent_setlist(band, date_str, setlistfm_key)
        except RuntimeError as e:
            st.error(str(e))
            st.stop()
    progress.empty()

    st.session_state["setlists"] = results
    st.session_state["bands"] = bands
    st.session_state["event_name"] = event_venue
    st.session_state["event_date_str"] = date_str

# ─── Step 2: Review & edit setlists ──────────────────────────────────────────

if "setlists" not in st.session_state:
    st.stop()

st.divider()
st.subheader("Review setlists")
st.caption("Uncheck songs you want to leave out.")

bands: list[str] = st.session_state["bands"]
setlists: dict = st.session_state["setlists"]
selected: dict[str, list[str]] = {}

for band in bands:
    is_headliner = band == bands[-1]
    header = f"{'👑 ' if is_headliner else '🎵 '}{band}"
    data = setlists[band]

    with st.expander(header, expanded=True):
        if data is None:
            st.warning(
                f"No setlist found for **{band}** before {st.session_state['event_date_str']}. "
                "They may not have played recently or setlist.fm has no data."
            )
            selected[band] = []
            continue

        location_parts = [p for p in [data["venue"], data["city"], data["country"]] if p]
        location = ", ".join(location_parts)
        st.caption(
            f"Based on show: **{data['date']}** — {location}  "
            f"[view on setlist.fm]({data['url']})"
        )

        band_songs = []
        for song in data["songs"]:
            if st.checkbox(song, value=True, key=f"check_{band}_{song}"):
                band_songs.append(song)
        selected[band] = band_songs

# ─── Step 3: Generate Gemini prompt ──────────────────────────────────────────

st.divider()

total = sum(len(s) for s in selected.values())
bands_with_songs = sum(1 for s in selected.values() if s)
st.caption(f"**{total} songs** selected across **{bands_with_songs}** band(s)")

if st.button("Generate Gemini Prompt →", type="primary", disabled=total == 0):
    event_name = st.session_state["event_name"] or "Tonight's Show"
    event_date_str = st.session_state["event_date_str"]
    playlist_title = f"{event_name} — {event_date_str}"

    lines = [
        f'Create a YouTube Music playlist called "{playlist_title}" '
        f"with the following songs in this exact order:\n"
    ]

    for band in bands:
        songs = selected.get(band, [])
        if not songs:
            continue
        role = "Headliner" if band == bands[-1] else "Support"
        lines.append(f"— {role}: {band} —")
        for i, song in enumerate(songs, 1):
            lines.append(f"{i}. {band} - {song}")
        lines.append("")

    prompt = "\n".join(lines).strip()

    st.subheader("Your Gemini prompt")
    st.info(
        "1. Open [gemini.google.com](https://gemini.google.com)  \n"
        "2. Make sure **YouTube Music extension** is enabled "
        "(Settings → Extensions → YouTube Music)  \n"
        "3. Paste the text below and send it",
        icon="ℹ️",
    )
    st.code(prompt, language=None)
