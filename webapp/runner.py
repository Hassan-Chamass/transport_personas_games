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
from preprocessing import get_trip_constants_from_data, to_prism_const_string

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


def parse_result(output: str) -> str:
    """Extract the Result value from raw PRISM output. Returns 'ERROR' if not found."""
    for line in output.splitlines():
        if line.strip().startswith("Result:"):
            # e.g. "Result: 1.0 (exact floating point)" -> "1.0"
            match = re.search(r"Result:\s*(\S+)", line)
            if match:
                return match.group(1)
    return "ERROR"


# ── Sweep (PRISM experiment) helpers ─────────────────────────────────────────

def _fmt_range_value(v) -> str:
    """Format a range bound: integral floats become ints (PRISM rejects
    '0.0' for int constants; int literals are accepted for doubles)."""
    f = float(v)
    return str(int(f)) if f.is_integer() else str(f)


def make_range_const(const_str: str, name: str, lo, step, hi) -> str:
    """Replace 'NAME=value' with the PRISM experiment range 'NAME=lo:step:hi'."""
    pattern = rf"(^|,){re.escape(name)}=[^,]*"
    if not re.search(pattern, const_str):
        raise ValueError(f"Swept constant {name} not found in the -const string")
    lo, step, hi = _fmt_range_value(lo), _fmt_range_value(step), _fmt_range_value(hi)
    return re.sub(pattern, rf"\g<1>{name}={lo}:{step}:{hi}", const_str, count=1)


def parse_experiment_file(path) -> list[dict]:
    """
    Parse a PRISM -exportresults file: tab-separated, one header line
    (constant name(s) + 'Result'), then one row per swept value.
    Returns [{"value": "...", "result": "..."}, ...].
    """
    rows = []
    with open(path, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    for line in lines[1:]:                       # skip header
        parts = line.split("\t")
        if len(parts) >= 2:
            rows.append({"value": parts[0], "result": parts[-1]})
    return rows


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
    sweep: dict = None,
):
    """
    Generator: runs PRISM for each property index in prop_indices.
    Yields dicts with progress info after each property completes.

    sweep (optional): {"const": name, "from": x, "to": y, "step": z} —
        each property is run as a single PRISM experiment over the range
        (native ranged constant + -exportresults), and the yielded dict
        carries the whole series instead of a single value.

    Yielded dict keys:
        prop_n   : int   — property number (1-based)
        result   : str   — parsed result value / summary, or 'ERROR'
        error    : bool  — True if the run failed
        series     (sweep only) : [{"value": v, "result": r}, ...]
        const_name (sweep only) : swept constant name
    """
    for prop_n in prop_indices:
        series   = []
        exp_file = None
        try:
            cs = const_str
            if sweep:
                cs = make_range_const(const_str, sweep["const"],
                                      sweep["from"], sweep["step"], sweep["to"])
                exp_file = RESULTS_DIR / f"{label}_prop{prop_n}_sweep_{sweep['const']}.txt"

            cmd = [
                PRISM_EXE,
                str(MODEL_FILE),
                str(PROPS_FILE),
                "-prop", str(prop_n),
                "-const", cs,
            ]
            if exp_file is not None:
                cmd += ["-exportresults", str(exp_file)]

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(Path(PRISM_EXE).parent),
            )
            output = proc.stdout + proc.stderr

            if sweep:
                if exp_file.exists():
                    series = parse_experiment_file(exp_file)
                had_error = len(series) == 0
                result = f"{len(series)} values" if not had_error else "ERROR"
            else:
                result = parse_result(output)
                had_error = proc.returncode != 0 and result == "ERROR"
        except Exception as e:
            output = str(e)
            result = "ERROR"
            had_error = True

        save_result(label, prop_n, output)

        out = {
            "prop_n":  prop_n,
            "result":  result,
            "error":   had_error,
        }
        if sweep:
            out["series"]     = series
            out["const_name"] = sweep["const"]
        yield out
