"""
run_all.py - Run PRISM-games experiments for transport personas

Usage:
  python run_all.py                                                    # run everything (reliability.props)
  python run_all.py --props-file thresholds                           # use thresholds.props
  python run_all.py --persona less_mobile                              # one persona
  python run_all.py --persona less_mobile --props 1 2 3               # one persona, specific props
  python run_all.py --persona less_mobile empty_nester                 # two personas
  python run_all.py --props-file thresholds --scenario high_disruption # thresholds, one scenario
"""

import subprocess, json, os, glob, argparse, sys

sys.path.insert(0, os.path.dirname(__file__))
from preprocessing import get_trip_constants, to_prism_const_string

# -------------------------------------------------------
# Edit these paths if needed
# -------------------------------------------------------
PRISM   = r"C:\prism-games\bin\prism.bat"
BASE    = r"E:\Utilisateurs\hassa\Bureau\BDI Agents\transport-personas-games"
# -------------------------------------------------------

parser = argparse.ArgumentParser()
parser.add_argument("--persona",    nargs="+")
parser.add_argument("--model",      nargs="+")
parser.add_argument("--props",      nargs="+", type=int)
parser.add_argument("--scenario",   nargs="+")
parser.add_argument("--props-file", default="reliability")
parser.add_argument("--trip",  default="giffnock_glasgow",       help="Trip config name (params/trip/)")
parser.add_argument("--fares", default="giffnock_glasgow_fares", help="Fares config name (params/fares/)")
parser.add_argument("--exportstrat", action="store_true",        help="Export optimal strategy as .dot file")
args = parser.parse_args()

# Precompute trip constants (used only for transport_smg model)
trip_consts_str = to_prism_const_string(get_trip_constants(trip=args.trip, fares=args.fares))

# Defaults
personas_to_run = args.persona or None   # None = all
models_to_run   = args.model   or ["transport_smg"]  # default model

def count_props(path):
    count = 0
    with open(path) as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("//") and not s.startswith("label"):
                count += 1
    return count

props_file_name = vars(args)["props_file"]
props_file_path = f"{BASE}/props/{props_file_name}.props"
props_to_run    = args.props or list(range(1, count_props(props_file_path) + 1))


# Load persona files
personas = []
for f in glob.glob(f"{BASE}/params/personas/*.json"):
    p = json.load(open(f))
    if personas_to_run is None or p["name"] in personas_to_run:
        personas.append(p)

# Load scenario files
scenarios_to_run = args.scenario or None
scenarios = []
for f in glob.glob(f"{BASE}/params/scenarios/*.json"):
    s = json.load(open(f))
    if scenarios_to_run is None or s["name"] in scenarios_to_run:
        scenarios.append(s)

# Run experiments
os.makedirs(f"{BASE}/results/raw", exist_ok=True)

for persona in personas:
    persona_consts = ",".join(
        f"{k}={'true' if v is True else 'false' if v is False else v}"
        for k, v in persona.items() if k != "name"
    )

    for model in models_to_run:
        model_file = f"{BASE}/models/{model}.pm"
        props_file = f"{BASE}/props/{props_file_name}.props"

        if not os.path.exists(model_file):
            print(f"[SKIP] {model}.pm not found")
            continue

        if model == "disrupted" and not scenarios:
            print(f"[SKIP] {model} requires a scenario (none found in params/scenarios/)")
            continue

        run_scenarios = scenarios 

        for scenario in run_scenarios:
            if scenario is not None:
                scenario_consts = ",".join(
                    f"{k}={'true' if v is True else 'false' if v is False else v}"
                    for k, v in scenario.items() if k != "name"
                )
                consts = persona_consts + "," + scenario_consts
                scenario_tag = "_" + scenario["name"]
            else:
                consts = persona_consts
                scenario_tag = ""

            if model == "transport_smg":
                consts = trip_consts_str + "," + consts

            run_label = f"{persona['name']}{scenario_tag}_{model}"
            print(f"\nRunning {run_label} ...")

            for prop_n in props_to_run:
                label = f"{run_label}_{props_file_name}_prop{prop_n}"
                print(f"  prop {prop_n}:", end=" ", flush=True)
                cmd = [PRISM, model_file, props_file, "-prop", str(prop_n), "-const", consts]
                if args.exportstrat:
                    strat_file = f"{BASE}/results/strategies/{label}.dot"
                    os.makedirs(f"{BASE}/results/strategies", exist_ok=True)
                    cmd += ["-exportstrat", strat_file]
                result = subprocess.run(cmd, capture_output=True, text=True,
                    cwd=r"C:\prism-games\bin"
                )

                output = result.stdout + result.stderr
                with open(f"{BASE}/results/raw/{label}.txt", "w") as f:
                    f.write(output)
                for line in output.splitlines():
                    if line.startswith("Result:"):
                        print(line)
                        break
                else:
                    print("ERROR (see output file)")

print("\nResults saved to results/raw/")
