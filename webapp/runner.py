"""
runner.py
Handles all PRISM execution logic: building constant strings,
spawning subprocesses, parsing results, saving output files.

Design note: build_const_string never hardcodes field names.
It iterates over whatever keys exist in the JSON dicts,
so adding new constants only requires updating the JSON files.
"""

import subprocess
import re
import os
from pathlib import Path
from preprocessing import get_trip_constants, to_prism_const_string

# ── Paths ──────────────────────────────────────────────────────────────────
PRISM_EXE   = r"C:\prism-games\bin\prism.bat"
BASE_DIR    = Path(__file__).resolve().parent.parent          # transport-personas-games/
MODEL_FILE  = BASE_DIR / "models" / "transport_smg.pm"
PROPS_FILE  = BASE_DIR / "props"  / "transport_smg.props"
RESULTS_DIR = BASE_DIR / "results" / "raw"
STRAT_DIR   = BASE_DIR / "results" / "strategies"
SCRIPTS_DIR = BASE_DIR / "scripts"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)
STRAT_DIR.mkdir(parents=True, exist_ok=True)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _to_prism_value(v) -> str:
    """Convert a Python value to its PRISM constant string."""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _dict_to_const_str(d: dict, skip_keys: set = None) -> str:
    """
    Convert a flat dict to a PRISM -const fragment.
    Keys in skip_keys are excluded (e.g. 'name', metadata keys starting with '_').
    """
    skip_keys = skip_keys or set()
    parts = []
    for k, v in d.items():
        if k in skip_keys or k.startswith("_"):
            continue
        parts.append(f"{k}={_to_prism_value(v)}")
    return ",".join(parts)


# ── Public API ───────────────────────────────────────────────────────────────

def build_const_string(
    trip_name: str,
    trip_data: dict,
    fares_data: dict,
    factors_data: dict,
    persona: dict,
    scenario: dict,
    policy_config: dict = None,
) -> str:
    """
    Build the full PRISM -const string for one (persona, scenario) combination.

    Parameters
    ----------
    trip_name     : name of the trip (used to call preprocessing helpers)
    trip_data     : raw trip JSON dict
    fares_data    : raw fares JSON dict (possibly user-edited)
    factors_data  : raw dft_factors JSON dict (possibly user-edited)
    persona       : persona dict (all fields except 'name')
    scenario      : scenario dict (all fields except 'name')
    policy_config : policy_config JSON dict (ALLOW_* booleans); None = all allowed

    Returns
    -------
    Comma-separated PRISM -const string ready for subprocess call.
    """
    # Trip geometry + CO2e + time + fare constants via preprocessing
    trip_consts = get_trip_constants_from_data(trip_data, fares_data, factors_data)
    trip_str    = to_prism_const_string(trip_consts)

    # Persona constants (skip 'name')
    persona_str  = _dict_to_const_str(persona,  skip_keys={"name"})

    # Scenario constants (skip 'name')
    scenario_str = _dict_to_const_str(scenario, skip_keys={"name"})

    # Policy config constants (ALLOW_* booleans)
    policy_str = _dict_to_const_str(policy_config) if policy_config else ""

    parts = [trip_str, persona_str, scenario_str, policy_str]
    return ",".join(p for p in parts if p)


def get_trip_constants_from_data(trip_data: dict, fares_data: dict, factors_data: dict) -> dict:
    """
    Recompute PRISM trip constants from raw JSON dicts (user may have edited values).
    Mirrors the logic in preprocessing.py but accepts dicts directly instead of file paths.
    """
    seg   = trip_data["segments"]
    stop_modes  = trip_data.get("available_modes_from_stop",        {"bus": True, "rail": True})
    final_modes = trip_data.get("available_modes_from_interchange",  {"bus": True, "rail": False})

    f_taxi = factors_data["factors_g_per_pkm"]["taxi"]
    f_bus  = factors_data["factors_g_per_pkm"]["local_bus"]
    f_rail = factors_data["factors_g_per_pkm"]["national_rail"]
    f_car  = factors_data["car_g_per_vkm"]

    def co2e(dist_km: float, factor: float) -> int:
        return round(dist_km * factor)

    base  = fares_data["base_fares"]
    lf    = fares_data["policy_overrides"]["low_fare"]
    rc    = fares_data["policy_overrides"]["road_charge"]
    surge = rc["surcharge"]

    return {
        # Distance (metres)
        "DIST_HOME_TO_STOP":        round(seg["walk_to_stop"]["dist_km"] * 1000),
        "DIST_INTERCHANGE_TO_DEST": round(seg["walk_interchange_to_dest"]["dist_km"] * 1000),
        "DIST_HOME_TO_DEST":        round(seg["walk_direct"]["dist_km"] * 1000),

        # CO2e (grams)
        "CO2E_CAR_DIRECT":      co2e(seg["car_direct"]["dist_km"],                   f_car),
        "CO2E_TAXI_DIRECT":     co2e(seg["taxi_direct"]["dist_km"],                  f_taxi),
        "CO2E_TAXI_STOP":       co2e(seg["taxi_from_stop"]["dist_km"],               f_taxi),
        "CO2E_TAXI_FINAL":      co2e(seg["taxi_final_leg"]["dist_km"],               f_taxi),
        "CO2E_BUS_STOP_TO_INT": co2e(seg["bus_stop_to_interchange"]["dist_km"],      f_bus),
        "CO2E_RAIL_STOP_TO_INT":co2e(seg["rail_stop_to_interchange"]["dist_km"],     f_rail),
        "CO2E_BUS_FINAL":       co2e(seg["bus_interchange_to_dest"]["dist_km"],      f_bus),
        "CO2E_RAIL_FINAL":      co2e(seg["rail_interchange_to_dest"]["dist_km"],     f_rail),

        # Time (minutes)
        "TIME_CAR_CLEAR":          seg["car_direct"]["time_min"]["clear"],
        "TIME_CAR_RAIN":           seg["car_direct"]["time_min"]["rain"],
        "TIME_CAR_SEVERE":         seg["car_direct"]["time_min"]["severe"],
        "TIME_TAXI_DIRECT_CLEAR":  seg["taxi_direct"]["time_min"]["clear"],
        "TIME_TAXI_DIRECT_RAIN":   seg["taxi_direct"]["time_min"]["rain"],
        "TIME_TAXI_DIRECT_SEVERE": seg["taxi_direct"]["time_min"]["severe"],
        "TIME_TAXI_STOP_CLEAR":    seg["taxi_from_stop"]["time_min"]["clear"],
        "TIME_TAXI_STOP_RAIN":     seg["taxi_from_stop"]["time_min"]["rain"],
        "TIME_TAXI_STOP_SEVERE":   seg["taxi_from_stop"]["time_min"]["severe"],
        "TIME_TAXI_FINAL_CLEAR":   seg["taxi_final_leg"]["time_min"]["clear"],
        "TIME_TAXI_FINAL_RAIN":    seg["taxi_final_leg"]["time_min"]["rain"],
        "TIME_TAXI_FINAL_SEVERE":  seg["taxi_final_leg"]["time_min"]["severe"],
        "TIME_BUS_STOP_TO_INT":    seg["bus_stop_to_interchange"]["time_min"],
        "TIME_RAIL_STOP_TO_INT":   seg["rail_stop_to_interchange"]["time_min"],
        "TIME_FINAL_BUS":          seg["bus_interchange_to_dest"]["time_min"],
        "TIME_FINAL_RAIL":         seg["rail_interchange_to_dest"]["time_min"],
        "TIME_FINAL_WALK":         seg["walk_interchange_to_dest"]["time_min"],
        "TIME_WALK_TO_STOP":       seg["walk_to_stop"]["time_min"],
        "TIME_BIKE_DIRECT":        seg["bike_direct"]["time_min"],
        "TIME_WALK_TO_DEST":       seg["walk_direct"]["time_min"],

        # Fares (pence)
        "BUS_FARE_BASE":         base["bus"],
        "BUS_FARE_LOW":          lf["bus"],
        "RAIL_FARE_BASE":        base["rail"],
        "RAIL_FARE_LOW":         lf["rail"],
        "TAXI_DIRECT_FARE_BASE": base["taxi_direct"],
        "TAXI_STOP_FARE_BASE":   base["taxi_stop"],
        "TAXI_FINAL_FARE_BASE":  base["taxi_final"],
        "ROAD_CHARGE_SURCHARGE": surge,

        # Mode availability
        "HAS_BUS_STOP":  "true" if stop_modes.get("bus",   True)  else "false",
        "HAS_RAIL_STOP": "true" if stop_modes.get("rail",  True)  else "false",
        "HAS_BUS_FINAL": "true" if final_modes.get("bus",  True)  else "false",
        "HAS_RAIL_FINAL":"true" if final_modes.get("rail", False) else "false",
    }


def parse_result(output: str) -> str:
    """Extract the Result value from raw PRISM output. Returns 'ERROR' if not found."""
    for line in output.splitlines():
        if line.strip().startswith("Result:"):
            # e.g. "Result: 1.0 (exact floating point)" -> "1.0"
            match = re.search(r"Result:\s*(\S+)", line)
            if match:
                return match.group(1)
    return "ERROR"


def save_result(label: str, prop_n: int, output: str):
    """Write raw PRISM output to results/raw/{label}_prop{n}.txt"""
    path = RESULTS_DIR / f"{label}_prop{prop_n}.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(output)


def export_dot(
    label: str,
    const_str: str,
    prop_index: int,
) -> str:
    """
    Run PRISM to export the strategy for one property as a DOT graph,
    then prettify it with dot_prettify.py.

    Returns the prettified DOT content as a string.
    Raises RuntimeError if PRISM does not produce the strategy file.
    """
    import sys
    raw_dot    = STRAT_DIR / f"{label}_prop{prop_index}_raw.dot"
    pretty_dot = STRAT_DIR / f"{label}_prop{prop_index}_pretty.dot"

    cmd = [
        PRISM_EXE,
        str(MODEL_FILE),
        str(PROPS_FILE),
        "-prop", str(prop_index),
        "-const", const_str,
        "-exportstrat", str(raw_dot),
    ]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(Path(PRISM_EXE).parent),
    )

    if not raw_dot.exists():
        raise RuntimeError(
            f"PRISM did not produce a strategy file.\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )

    # Prettify with dot_prettify.py
    prettify_script = SCRIPTS_DIR / "dot_prettify.py"
    subprocess.run(
        [sys.executable, str(prettify_script), str(raw_dot), "-o", str(pretty_dot)],
        check=True,
    )

    return pretty_dot.read_text(encoding="utf-8", errors="replace")


def run_combination(
    label: str,
    const_str: str,
    prop_indices: list[int],
):
    """
    Generator: runs PRISM for each property index in prop_indices.
    Yields dicts with progress info after each property completes.

    Yielded dict keys:
        prop_n   : int   — property number (1-based)
        result   : str   — parsed result value or 'ERROR'
        error    : bool  — True if PRISM returned non-zero exit code
    """
    for prop_n in prop_indices:
        cmd = [
            PRISM_EXE,
            str(MODEL_FILE),
            str(PROPS_FILE),
            "-prop", str(prop_n),
            "-const", const_str,
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(Path(PRISM_EXE).parent),
            )
            output = proc.stdout + proc.stderr
            result = parse_result(output)
            had_error = proc.returncode != 0 and result == "ERROR"
        except Exception as e:
            output = str(e)
            result = "ERROR"
            had_error = True

        save_result(label, prop_n, output)

        yield {
            "prop_n":  prop_n,
            "result":  result,
            "error":   had_error,
        }
