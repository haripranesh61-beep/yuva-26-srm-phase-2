# VibeCraft Round 2 — Final

A Phase 1 + Phase 2 Smart Room Finder for the SRM YUVA challenge.

## Product flow

**Find. See. Go.**

1. Describe the room in natural language.
2. Gemini interprets the request when `GEMINI_API_KEY` is configured.
3. The local timetable engine verifies room occupancy across every touched period.
4. Matching rooms appear as simple, understandable cards.
5. The Smart Floor Explorer shows the rooms on an interactive isometric floor map.
6. Select a room to see live status, countdown, timetable evidence and WhatsApp squad sharing.
7. The timetable grid remains available as an auditable detail view.

## Gemini setup

Create `.env` beside `app.py`:

```env
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.5-flash
```

The API key is server-side only. `.env` is ignored by Git.

If Gemini is unavailable, the application automatically uses its local parser.

## Run on Windows

```powershell
.\\run.bat
```

Then open `http://127.0.0.1:5000`.

## Data integrity

Gemini only interprets the request. Room availability is calculated from the normalized uploaded timetable. AC, capacity and unsupported floor metadata are not invented; the UI marks them as unverified where the source data does not establish them.

The visual floor explorer is intentionally schematic rather than pretending to be an architectural survey. Room labels and occupancy are tied to the dataset.
