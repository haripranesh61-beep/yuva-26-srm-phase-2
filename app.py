
from flask import Flask, render_template, jsonify, request
from pathlib import Path
from datetime import datetime
import json, re, os, urllib.request, urllib.error
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")
app = Flask(__name__)

with open(BASE/"data"/"timetables.json", encoding="utf-8") as f:
    DATA=json.load(f)
with open(BASE/"data"/"rooms.json", encoding="utf-8") as f:
    ROOMS=json.load(f)["rooms"]

DAYS=["Mon","Tue","Wed","Thu","Fri"]

def mins(v):
    h,m=map(int,v.split(":"))
    return h*60+m

def norm(v):
    return re.sub(r"\s+"," ",str(v or "")).strip()

def active_sections():
    return [s for s in DATA["sections"] if s.get("dataset_status")=="active-2026-27"]

def occupied(day, period):
    result={}
    for s in active_sections():
        cells=s["days"].get(day,[])
        if not 1 <= period <= len(cells):
            continue
        room=norm(cells[period-1])
        if room:
            result.setdefault(room,[]).append(s["name"])
    return result

def _gemini_available():
    return bool(os.getenv("GEMINI_API_KEY"))

def _gemini_extract(text):
    """Use Gemini only to interpret language; timetable truth stays deterministic."""
    key=os.getenv("GEMINI_API_KEY")
    if not key:
        return None, "fallback"
    model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    prompt=f"""Extract room-search requirements from the student's request.
Return ONLY JSON matching this schema:
{{
  \"floor\": string|null,
  \"ac\": boolean|null,
  \"duration_hours\": number,
  \"start_time\": string|null,
  \"team_size\": integer|null,
  \"room_type\": \"lab\"|\"classroom\"|\"any\"|null
}}
Rules:
- Do not invent missing requirements.
- Ground/ground floor -> Ground.
- Convert first/1st and second/2nd floor to First/Second.
- If no duration is stated, use 1.0.
- Time must be 24-hour HH:MM when explicitly stated.
- "any" room_type means no room-type constraint.
Student request: {text}"""
    payload={"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"responseMimeType":"application/json","responseSchema":{"type":"OBJECT","properties":{"floor":{"type":"STRING","nullable":True},"ac":{"type":"BOOLEAN","nullable":True},"duration_hours":{"type":"NUMBER"},"start_time":{"type":"STRING","nullable":True},"team_size":{"type":"INTEGER","nullable":True},"room_type":{"type":"STRING","nullable":True}}}}}
    url=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    req=urllib.request.Request(url,data=json.dumps(payload).encode("utf-8"),headers={"Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=12) as resp:
            data=json.loads(resp.read().decode("utf-8"))
        raw=data["candidates"][0]["content"]["parts"][0]["text"]
        parsed=json.loads(raw)
        return parsed, "gemini"
    except Exception:
        return None, "fallback"

def parse_query(text):
    q=(text or "").lower()
    out={
        "floor":None,"ac":None,"duration_hours":1.0,
        "start_time":None,"team_size":None,"room_type":None,
        "raw":text or ""
    }
    if "ground" in q or "ground floor" in q:
        out["floor"]="Ground"
    elif re.search(r"\b(?:1st|first)\s+floor\b",q):
        out["floor"]="First"
    elif re.search(r"\b(?:2nd|second)\s+floor\b",q):
        out["floor"]="Second"
    if re.search(r"\b(?:ac|air[- ]?conditioned|air conditioned)\b",q):
        out["ac"]=True
    elif re.search(r"\bnon[- ]?ac\b",q):
        out["ac"]=False
    m=re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)",q)
    if m: out["duration_hours"]=float(m.group(1))
    m=re.search(r"(?:team of|for|with)\s*(\d+)\s*(?:people|students|members|persons)",q)
    if m: out["team_size"]=int(m.group(1))
    if "lab" in q or "laboratory" in q: out["room_type"]="lab"
    elif "classroom" in q or "lecture room" in q: out["room_type"]="classroom"
    m=re.search(r"\b(?:at|from)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",q)
    if m:
        h=int(m.group(1)); minute=int(m.group(2) or 0); ap=m.group(3)
        if ap=="pm" and h<12: h+=12
        if ap=="am" and h==12: h=0
        out["start_time"]=f"{h:02d}:{minute:02d}"
    return out

def periods_for_window(start,duration):
    start_m=mins(start); end_m=start_m+int(duration*60)
    periods=DATA["period_sets"]["2026-27"]
    result=[]
    for p in periods:
        if p.get("type")=="lunch": continue
        if start_m < mins(p["end"]) and end_m > mins(p["start"]):
            result.append(p["period"])
    return result

def current_time():
    return datetime.now().strftime("%H:%M")

@app.get("/")
def index(): return render_template("index.html")

@app.get("/api/health")
def health():
    return jsonify({"ok":True,"active_sections":len(active_sections()),"rooms":len(ROOMS)})

@app.get("/api/dataset")
def dataset():
    return jsonify({
        "sections":[{"id":s["id"],"name":s["name"],"venue":s["venue"],"source":s["source"],
                     "status":s.get("dataset_status")} for s in DATA["sections"]],
        "rooms":ROOMS,
        "periods":DATA["period_sets"]["2026-27"],
        "note":DATA["source_note"]
    })

@app.get("/api/grid")
def grid():
    day=request.args.get("day","Mon")
    period=int(request.args.get("period","1"))
    floor=request.args.get("floor","")
    occ=occupied(day,period)
    out=[]
    for r in ROOMS:
        if floor and r.get("floor")!=floor: continue
        out.append({**r,"status":"Occupied" if r["name"] in occ else "Available",
                    "used_by":occ.get(r["name"],[])})
    return jsonify({"day":day,"period":period,"rooms":out})

@app.post("/api/search")
def search():
    body=request.get_json(force=True) or {}
    query=body.get("query","")
    day=body.get("day","Mon")
    ai_parsed, interpretation_source=_gemini_extract(query)
    parsed=parse_query(query)
    if ai_parsed:
        for k in ("floor","ac","duration_hours","start_time","team_size","room_type"):
            if k in ai_parsed and ai_parsed[k] is not None:
                parsed[k]=ai_parsed[k]
        if parsed.get("room_type")=="any": parsed["room_type"]=None
    start=parsed["start_time"] or body.get("current_time") or current_time()
    parsed["start_time"]=start
    wanted=periods_for_window(start,parsed["duration_hours"])

    if not wanted:
        # If current time is between timetable periods or after class hours,
        # use the next teaching period as a transparent fallback.
        now=mins(start)
        future=[p for p in DATA["period_sets"]["2026-27"]
                if p.get("type")!="lunch" and mins(p["end"])>now]
        if future: wanted=[future[0]["period"]]

    occ_by={p:occupied(day,p) for p in wanted}
    candidates=[]
    for r in ROOMS:
        if parsed["floor"] and r.get("floor")!=parsed["floor"]:
            continue
        busy=[p for p in wanted if r["name"] in occ_by[p]]
        if busy: continue
        ac_unverified=parsed["ac"] is not None and r.get("ac") is None
        candidates.append({
            **r,
            "ac_unverified":ac_unverified,
            "available_for_periods":wanted,
            "match_reason":"No timetable occupancy in any requested period."
        })
    warning=None
    if parsed["ac"] is not None:
        warning="AC status is not present in the uploaded timetable dataset; availability is verified by timetable only."
    if parsed["team_size"] is not None and any(r.get("capacity") is None for r in candidates):
        warning=(warning+" " if warning else "")+"Capacity is not present in the uploaded timetable dataset, so team-size capacity cannot be verified."
    if parsed["room_type"] is not None and any(r.get("room_type") is None for r in candidates):
        warning=(warning+" " if warning else "")+"Room type is not present in the uploaded timetable dataset, so lab/classroom type cannot be verified."
    return jsonify({"query":query,"parsed":parsed,"periods":wanted,
                    "candidates":candidates,"warning":warning,"interpretation_source":interpretation_source,
                    "ai_enabled":_gemini_available()})

if __name__=="__main__":
    app.run(host="0.0.0.0",port=5000,debug=True)
