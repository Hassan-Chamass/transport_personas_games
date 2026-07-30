"""
app.py
Flask server for the PRISM transport SMG verificator.

Routes
------
GET  /                         Serve the frontend
GET  /api/trips                List available trip names
GET  /api/trips/<name>         Return trip JSON
GET  /api/personas             List available persona names
GET  /api/personas/<name>      Return persona JSON
GET  /api/scenarios            List available scenario names
GET  /api/scenarios/<name>     Return scenario JSON
GET  /api/factors              Return dft_factors.json
GET  /api/fares/<trip>         Return fares JSON for a trip
GET  /api/props                Return [{index, description, formula}] for all 52 props
POST /api/save-persona         Save a custom persona JSON to params/personas/
POST /api/save-scenario        Save a custom scenario JSON to params/scenarios/
POST /api/save-trip            Save a custom trip JSON to params/trip/
POST /api/run                  SSE stream: run PRISM for all (persona x scenario x prop) combos
"""

import base64
import csv
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, request, Response, send_from_directory

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).resolve().parent.parent   # transport-personas-games/
PARAMS_DIR   = BASE_DIR / "params"
STATIC_DIR   = Path(__file__).resolve().parent / "static"
SCRIPTS_DIR  = BASE_DIR / "scripts"
PROPS_FILE          = BASE_DIR / "props" / "transport_smg.props"
POLICY_CONFIG_FILE  = PARAMS_DIR / "run_config.json"

# Make scripts importable (preprocessing.py lives there)
sys.path.insert(0, str(SCRIPTS_DIR))
from runner import build_const_string, run_combination, export_dot  # noqa: E402

app = Flask(__name__, static_folder=str(STATIC_DIR))


# ── Helpers ─────────────────────────────────────────────────────────────────

def _list_json_names(folder: Path) -> list[str]:
    """Return sorted list of JSON file stems (without extension) in a folder."""
    return sorted(p.stem for p in folder.glob("*.json") if not p.stem.startswith("_"))


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_custom(folder: Path, data: dict, name: str) -> Path:
    """Save a custom config JSON, appending _custom to the filename."""
    safe_name = re.sub(r"[^\w\-]", "_", name.strip())
    if not safe_name.endswith("_custom"):
        safe_name = safe_name + "_custom"
    path = folder / f"{safe_name}.json"
    data["name"] = safe_name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def _parse_props(props_file: Path) -> list[dict]:
    """
    Parse transport_smg.props and return a mixed list of:
      { type: "section", title: str }          — emitted for // SECTION X — ... lines
      { index: int, description: str, formula: str } — one per property formula
    Section entries are inserted just before the first property of that section,
    so the frontend can render headers without any hardcoded index mapping.
    """
    props = []
    idx = 0
    current_comment = ""
    with open(props_file, encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip().strip("\x00")
            if s.startswith("//"):
                comment = s.lstrip("/ ").strip()
                if comment.upper().startswith("SECTION"):
                    props.append({"type": "section", "title": comment})
                else:
                    current_comment = re.sub(r'^\d+\.\s*', '', comment)
            elif s and (s.startswith("<<") or "=?" in s or ">=" in s or "<=" in s):
                idx += 1
                props.append({
                    "index":       idx,
                    "description": current_comment,
                    "formula":     s,
                })
                current_comment = ""
    return props


# ── Static ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


# ── Trip routes ──────────────────────────────────────────────────────────────

@app.route("/api/trips")
def list_trips():
    return jsonify(_list_json_names(PARAMS_DIR / "trip"))


@app.route("/api/trips/<name>")
def get_trip(name):
    path = PARAMS_DIR / "trip" / f"{name}.json"
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    return jsonify(_load_json(path))


@app.route("/api/save-trip", methods=["POST"])
def save_trip():
    body = request.get_json()
    name = body.get("name", "custom_trip")
    _save_custom(PARAMS_DIR / "trip", body, name)
    return jsonify({"ok": True, "saved_as": name + "_custom"})


# ── Persona routes ────────────────────────────────────────────────────────────

@app.route("/api/personas")
def list_personas():
    return jsonify(_list_json_names(PARAMS_DIR / "personas"))


@app.route("/api/personas/<name>")
def get_persona(name):
    path = PARAMS_DIR / "personas" / f"{name}.json"
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    return jsonify(_load_json(path))


@app.route("/api/save-persona", methods=["POST"])
def save_persona():
    body = request.get_json()
    name = body.get("name", "custom")
    _save_custom(PARAMS_DIR / "personas", body, name)
    return jsonify({"ok": True, "saved_as": name + "_custom"})


# ── Scenario routes ───────────────────────────────────────────────────────────

@app.route("/api/scenarios")
def list_scenarios():
    return jsonify(_list_json_names(PARAMS_DIR / "scenarios"))


@app.route("/api/scenarios/<name>")
def get_scenario(name):
    path = PARAMS_DIR / "scenarios" / f"{name}.json"
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    return jsonify(_load_json(path))


@app.route("/api/save-scenario", methods=["POST"])
def save_scenario():
    body = request.get_json()
    name = body.get("name", "custom")
    _save_custom(PARAMS_DIR / "scenarios", body, name)
    return jsonify({"ok": True, "saved_as": name + "_custom"})


# ── Factors & Fares ───────────────────────────────────────────────────────────

@app.route("/api/factors")
def get_factors():
    return jsonify(_load_json(PARAMS_DIR / "dft_factors.json"))


@app.route("/api/save-fares", methods=["POST"])
def save_fares():
    body = request.get_json()
    name = body.pop("name", "custom")
    safe_name = re.sub(r"[^\w\-]", "_", name.strip())
    if not safe_name.endswith("_custom"):
        safe_name = safe_name + "_custom"
    path = PARAMS_DIR / "fares" / f"{safe_name}_fares.json"
    body["name"] = safe_name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=2)
    return jsonify({"ok": True, "saved_as": safe_name})


@app.route("/api/fares-list")
def list_fares():
    """Return sorted list of fares file names (without _fares suffix or extension)."""
    folder = PARAMS_DIR / "fares"
    names = []
    for p in folder.glob("*.json"):
        stem = p.stem
        if stem.endswith("_fares"):
            stem = stem[:-6]
        names.append(stem)
    return jsonify(sorted(names))


@app.route("/api/fares/<trip>")
def get_fares(trip):
    # Fares files are named <trip>_fares.json
    path = PARAMS_DIR / "fares" / f"{trip}_fares.json"
    if not path.exists():
        # Fallback: try exact name
        path = PARAMS_DIR / "fares" / f"{trip}.json"
    if not path.exists():
        return jsonify({"error": "Fares file not found for this trip"}), 404
    return jsonify(_load_json(path))


# ── Policy config ─────────────────────────────────────────────────────────────

@app.route("/api/run-config")
def get_run_config():
    return jsonify(_load_json(POLICY_CONFIG_FILE))


# ── Properties ────────────────────────────────────────────────────────────────

@app.route("/api/props")
def get_props():
    return jsonify(_parse_props(PROPS_FILE))


# ── Persona / Scenario templates ──────────────────────────────────────────────

@app.route("/api/templates/persona")
def persona_template():
    path = PARAMS_DIR / "templates" / "persona_template.json"
    return jsonify(_load_json(path))


@app.route("/api/templates/scenario")
def scenario_template():
    path = PARAMS_DIR / "templates" / "scenario_template.json"
    return jsonify(_load_json(path))


@app.route("/api/templates/trip")
def trip_template():
    # Use the existing trip as a template for custom trips
    path = PARAMS_DIR / "trip" / "giffnock_glasgow.json"
    return jsonify(_load_json(path))


# ── Export CSV ───────────────────────────────────────────────────────────────

EXPORTS_DIR = BASE_DIR / "results" / "exports"

@app.route("/api/export-csv", methods=["POST"])
def export_csv():
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    body     = request.get_json()
    results  = body.get("results", [])
    ts       = datetime.now().strftime("%Y-%m-%d_%H-%M")
    filename = f"results_{ts}.csv"
    path     = EXPORTS_DIR / filename
    fieldnames = ["policy", "persona", "scenario", "prop_index", "description", "formula", "result",
                  "const_name", "const_value"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    return jsonify({"filename": filename})


# ── Save sweep charts (SVG / PNG) to results/exports/plots/ ─────────────────

PLOTS_DIR = EXPORTS_DIR / "plots"

@app.route("/api/save-chart", methods=["POST"])
def save_chart():
    """
    Expects JSON body: { "filename": str, "format": "svg"|"png", "data": str }
    data is raw SVG text for svg, or a data-URL (base64) for png.
    Writes to results/exports/plots/<filename>.<format>.
    """
    body = request.get_json()
    fmt  = body.get("format")
    name = re.sub(r"[^A-Za-z0-9_\-.]", "_", body.get("filename", "chart"))
    data = body.get("data", "")
    if fmt not in ("svg", "png") or not data:
        return jsonify({"error": "format must be svg or png, with data"}), 400
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = PLOTS_DIR / f"{name}.{fmt}"
    if fmt == "svg":
        path.write_text(data, encoding="utf-8")
    else:
        try:
            b64 = data.split(",", 1)[1]
            path.write_bytes(base64.b64decode(b64))
        except (IndexError, ValueError):
            return jsonify({"error": "invalid PNG data URL"}), 400
    return jsonify({"saved": f"results/exports/plots/{name}.{fmt}"})


# ── Export DOT ───────────────────────────────────────────────────────────────

@app.route("/api/export-dot", methods=["POST"])
def export_dot_route():
    """
    Export a PRISM strategy as a prettified DOT graph for a single
    (persona × scenario × property) combination.

    Expects JSON body:
    {
        "trip":      { ...trip JSON... },
        "fares":     { ...fares JSON... },
        "factors":   { ...factors JSON... },
        "persona":   { ...persona JSON... },
        "scenario":  { ...scenario JSON... },
        "prop":      1                        // 1-based property index
    }

    Returns: { "dot": "<dot content>" }
    """
    body         = request.get_json()
    trip_data     = body.get("trip",           {})
    fares_data    = body.get("fares",          {})
    factors_data  = body.get("factors",        {})
    policy_data   = body.get("policy",         {})
    persona       = body.get("persona",        {})
    scenario      = body.get("scenario",       {})
    prop_index    = body.get("prop")

    if not persona or not scenario or prop_index is None:
        return jsonify({"error": "persona, scenario, and prop are required"}), 400

    try:
        const_str = build_const_string(
            trip_name     = trip_data.get("_corridor", "custom"),
            trip_data     = trip_data,
            fares_data    = fares_data,
            factors_data  = factors_data,
            policy_config = policy_data,
            persona       = persona,
            scenario      = scenario,
        )
        p_name = persona.get("name", "persona")
        s_name = scenario.get("name", "scenario")
        label  = f"{p_name}_{s_name}_transport_smg"
        dot_content = export_dot(label, const_str, int(prop_index))
        return jsonify({"dot": dot_content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Run (SSE) ─────────────────────────────────────────────────────────────────

@app.route("/api/run", methods=["POST"])
def run():
    """
    SSE endpoint. Expects JSON body:
    {
        "trip":      { ...trip JSON... },
        "fares":     { ...fares JSON... },
        "factors":   { ...factors JSON... },
        "personas":  [ { ...persona JSON... }, ... ],
        "scenarios": [ { ...scenario JSON... }, ... ],
        "props":     [1, 3, 5, ...]   // 1-based property indices
    }

    Streams SSE events:
        { "type": "start",    "run": "label", "total": N }
        { "type": "progress", "run": "label", "prop_n": N, "result": "X", "error": bool }
        { "type": "done",     "run": "label" }
        { "type": "finished" }
        { "type": "error",    "message": "..." }
    """
    body = request.get_json()

    trip_data     = body.get("trip",      {})
    fares_data    = body.get("fares",     {})
    factors_data  = body.get("factors",   {})
    policy_data   = body.get("policy",    {})
    personas      = body.get("personas",  [])
    scenarios     = body.get("scenarios", [])
    prop_indices  = body.get("props",     [])
    sweep_cfg     = body.get("sweep")    or None

    if not personas or not scenarios or not prop_indices:
        return jsonify({"error": "personas, scenarios, and props are required"}), 400

    if sweep_cfg:
        try:
            sweep_cfg = {"const": str(sweep_cfg["const"]),
                         "from":  float(sweep_cfg["from"]),
                         "to":    float(sweep_cfg["to"]),
                         "step":  float(sweep_cfg["step"])}
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "sweep requires const, from, to, step"}), 400
        if sweep_cfg["step"] <= 0 or sweep_cfg["to"] <= sweep_cfg["from"]:
            return jsonify({"error": "sweep needs to > from and step > 0"}), 400

    def generate():
        try:
            combos = [
                (p, s)
                for p in personas
                for s in scenarios
            ]

            for persona, scenario in combos:
                p_name = persona.get("name", "persona")
                s_name = scenario.get("name", "scenario")
                label  = f"{p_name}_{s_name}_transport_smg_transport_smg"

                const_str = build_const_string(
                    trip_name     = trip_data.get("_corridor", "custom"),
                    trip_data     = trip_data,
                    fares_data    = fares_data,
                    factors_data  = factors_data,
                    policy_config = policy_data,
                    persona       = persona,
                    scenario      = scenario,
                )

                yield _sse({"type": "start", "run": label,
                            "persona": p_name, "scenario": s_name,
                            "total": len(prop_indices)})

                for progress in run_combination(label, const_str, prop_indices,
                                                sweep=sweep_cfg):
                    ev = {
                        "type":    "progress",
                        "run":     label,
                        "persona": p_name,
                        "scenario":s_name,
                        "prop_n":  progress["prop_n"],
                        "result":  progress["result"],
                        "error":   progress["error"],
                    }
                    if "series" in progress:
                        ev["series"]     = progress["series"]
                        ev["const_name"] = progress["const_name"]
                    yield _sse(ev)

                yield _sse({"type": "done", "run": label,
                            "persona": p_name, "scenario": s_name})

            yield _sse({"type": "finished"})

        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Starting PRISM Verificator at http://localhost:5000")
    app.run(debug=True, threaded=True, port=5000)
