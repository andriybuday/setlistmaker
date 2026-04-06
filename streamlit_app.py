import html
import streamlit as st
import streamlit.components.v1 as components
from datetime import date
from setlistfm import get_most_recent_setlist, search_artists
from ticketmaster import get_lineup

st.set_page_config(page_title="SetlistMaker", page_icon="🎸", layout="centered")

st.title("🎸 SetlistMaker")
st.caption("Look up tonight's setlists and generate a YouTube Music playlist via Gemini.")

# ─── API key ──────────────────────────────────────────────────────────────────

try:
    setlistfm_key = st.secrets["SETLISTFM_API_KEY"]
except (KeyError, FileNotFoundError):
    st.error("**Missing API key.** Add `SETLISTFM_API_KEY` to your Streamlit secrets.")
    st.stop()

tm_key: str | None = st.secrets.get("TICKETMASTER_API_KEY")

# ─── Step 1: Event details ────────────────────────────────────────────────────

st.subheader("Event details")

# Session state for pre-fillable fields + "Did you mean?" corrections
if "lineup_version" not in st.session_state:
    st.session_state["lineup_version"] = 0
if "bands_default" not in st.session_state:
    st.session_state["bands_default"] = ""
if "venue_default" not in st.session_state:
    st.session_state["venue_default"] = ""

col1, col2 = st.columns([2, 1])
headliner = col1.text_input("Headliner", placeholder="Metallica")
event_date = col2.date_input("Event date", value=date.today())

event_venue = st.text_input(
    "Venue (optional)",
    value=st.session_state["venue_default"],
    key=f"venue_{st.session_state['lineup_version']}",
    placeholder="Auto-filled when lineup is found",
)

if tm_key:
    if st.button("Find Lineup →", disabled=not headliner.strip()):
        with st.spinner(f"Looking up lineup for {headliner}…"):
            try:
                result = get_lineup(headliner.strip(), event_date.strftime("%Y-%m-%d"), tm_key)
            except RuntimeError as e:
                result = None
                st.warning(str(e))

        if result:
            st.session_state["bands_default"] = "\n".join(result["lineup"])
            st.session_state["venue_default"] = result["venue"]
            st.session_state["tour_name"] = result.get("tour_name", "")
            st.session_state["lineup_version"] += 1
            st.rerun()
        else:
            st.info("No lineup found on Ticketmaster for that date. Enter bands manually.")

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
    suggestions: dict[str, list[str]] = {}
    for i, band in enumerate(bands):
        progress.progress((i + 1) / len(bands), text=f"Looking up {band}…")
        try:
            results[band] = get_most_recent_setlist(band, date_str, setlistfm_key)
        except RuntimeError as e:
            st.error(str(e))
            st.stop()
        if results[band] is None:
            suggestions[band] = search_artists(band, setlistfm_key)
    progress.empty()

    st.session_state["setlists"] = results
    st.session_state["suggestions"] = suggestions
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
            band_suggestions = st.session_state.get("suggestions", {}).get(band, [])
            if band_suggestions:
                st.warning(f"No setlist found for **{band}**. Did you mean one of these?")
                for suggestion in band_suggestions:
                    if st.button(f'Use "{suggestion}"', key=f"suggest_{band}_{suggestion}"):
                        current = st.session_state.get("bands_default") or "\n".join(
                            st.session_state["bands"]
                        )
                        corrected = [
                            suggestion if b.strip() == band else b
                            for b in current.splitlines()
                        ]
                        st.session_state["bands_default"] = "\n".join(corrected)
                        st.session_state["lineup_version"] += 1
                        for k in ["setlists", "suggestions", "bands", "event_name", "event_date_str"]:
                            st.session_state.pop(k, None)
                        st.rerun()
            else:
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
        for i, song in enumerate(data["songs"]):
            if st.checkbox(song, value=True, key=f"check_{band}_{i}_{song}"):
                band_songs.append(song)
        selected[band] = band_songs

# ─── Step 3: Generate Gemini prompt ──────────────────────────────────────────

st.divider()

total = sum(len(s) for s in selected.values())
bands_with_songs = sum(1 for s in selected.values() if s)
st.caption(f"**{total} songs** selected across **{bands_with_songs}** band(s)")

if st.button("Generate Gemini Prompt & Copy →", type="primary", disabled=total == 0):
    event_date_str = st.session_state["event_date_str"]
    year = event_date_str[:4]
    tour_name = st.session_state.get("tour_name", "")

    # "Band A & Band B" or "Band A, Band B & Band C"
    band_list = [b for b in bands if selected.get(b)]
    if len(band_list) <= 2:
        bands_str = " & ".join(band_list)
    else:
        bands_str = ", ".join(band_list[:-1]) + " & " + band_list[-1]

    if tour_name:
        playlist_title = f"{tour_name} — {bands_str} {year}"
    else:
        playlist_title = f"{bands_str} {year}"

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

    # Auto-copy using hidden textarea + execCommand (works without user gesture)
    components.html(
        f"<textarea id='p' style='position:fixed;top:-9999px;opacity:0'>"
        f"{html.escape(prompt)}</textarea>"
        f"<script>var e=document.getElementById('p');e.select();"
        f"document.execCommand('copy');</script>",
        height=0,
    )

    st.subheader("Your Gemini prompt")
    st.success("✅ Prompt copied to clipboard!")
    st.info(
        "1. Open [gemini.google.com](https://gemini.google.com)  \n"
        "2. Make sure **YouTube Music extension** is enabled "
        "(Settings → Extensions → YouTube Music)  \n"
        "3. Paste the text below and send it",
        icon="ℹ️",
    )
    with st.expander("Show full prompt"):
        st.code(prompt, language=None)
