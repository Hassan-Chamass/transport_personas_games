"""
dot_prettify.py
Transforms a raw PRISM-games strategy .dot file into a human-readable version.

Usage:
    python scripts/dot_prettify.py results/strategies/<file>.dot
    python scripts/dot_prettify.py results/strategies/<file>.dot -o out.dot

When transport_smg.pm changes (variable added or removed), update STATE_VARS below.
Order must match the PRISM state-tuple order: global variables first, then module
variables in declaration order. To verify, check the header line of any .sta file
generated alongside the strategy (e.g. results/strategies/*.sta).
"""

import re
import argparse
from pathlib import Path

# ── Update this list when transport_smg.pm variables change ──────────────────
# Current model: phase (global) | policy, weather, acc_bus | loc, mode, done,
#                abandon, service_status, disruptions_used, fare_spent
STATE_VARS = [
    "phase", "policy", "weather", "acc_bus",
    "loc", "mode", "done", "abandon",
    "service_status", "disruptions_used", "fare_spent",
]
# ─────────────────────────────────────────────────────────────────────────────

# Human-readable mappings
POLICY  = {0: "normal", 1: "high_freq", 2: "low_fare", 3: "road_charge", 4: "accessible"}
WEATHER = {0: "clear", 1: "rain", 2: "severe"}
LOC     = {0: "home", 1: "stop", 2: "interchange", 3: "dest"}
MODE    = {0: "—", 1: "car", 2: "walk", 3: "bus", 4: "taxi", 5: "rail", 6: "bike"}
SVC     = {0: "ok", 1: "delayed", 2: "cancelled"}

def parse_tuple(raw):
    parts = raw.strip("()").split(",")
    vals = []
    for p in parts:
        p = p.strip()
        if p == "true":   vals.append(True)
        elif p == "false": vals.append(False)
        else:              vals.append(int(p))
    return vals

def decode(vals):
    return dict(zip(STATE_VARS, vals))

def make_label(sid, d):
    lines = [f"#{sid}"]
    lines.append(f"pol={POLICY.get(d['policy'], d['policy'])}  wthr={WEATHER.get(d['weather'], d['weather'])}")
    lines.append(f"loc={LOC.get(d['loc'], d['loc'])}  mode={MODE.get(d['mode'], d['mode'])}")
    extras = []
    if not d.get("acc_bus", True): extras.append("no acc.bus")
    if d.get("service_status", 0) != 0:  extras.append(f"svc={SVC[d['service_status']]}")
    if d.get("disruptions_used", 0) > 0: extras.append(f"disrupt={d['disruptions_used']}")
    if d.get("fare_spent", 0) > 0:       extras.append(f"fare={d['fare_spent']}p")
    if extras:
        lines.append(" | ".join(extras))
    if d.get("done"):
        lines.append("ABANDONED" if d.get("abandon") else "ARRIVED")
    return "\\n".join(lines)

def node_style(d):
    if d.get("done") and d.get("abandon"):
        return 'style="filled" fillcolor="lightcoral"'
    if d.get("done") and not d.get("abandon"):
        return 'style="filled" fillcolor="lightgreen"'
    return 'style="filled" fillcolor="white"'

def prettify(dot_text):
    node_re  = re.compile(r'^(\d+)\s*\[label="(\d+)\\n(\([^)]+\))"\];', re.MULTILINE)
    edge_re  = re.compile(r'^(\d+)\s*->\s*(\d+)\s*\[label="([^"]+)"\];', re.MULTILINE)
    first_re = re.compile(r'^0\s*\[', re.MULTILINE)

    nodes = {}
    for m in node_re.finditer(dot_text):
        nid, _, raw_tuple = m.group(1), m.group(2), m.group(3)
        vals = parse_tuple(raw_tuple)
        d    = decode(vals)
        nodes[nid] = d

    lines = ["digraph M {",
             '  node [shape="box" fontname="Courier" fontsize=10];',
             '  edge [fontsize=9];',
             ""]

    # Nodes
    for nid, d in nodes.items():
        label = make_label(nid, d)
        style = node_style(d)
        # Initial state gets a blue border
        extra = ' color="steelblue" penwidth=2' if nid == "0" else ""
        lines.append(f'  {nid} [label="{label}" {style}{extra}];')

    lines.append("")

    # Edges — skip done_loop self-loops (visual noise)
    for m in edge_re.finditer(dot_text):
        src, dst, lbl = m.group(1), m.group(2), m.group(3)
        if src == dst and "done_loop" in lbl:
            continue
        lines.append(f'  {src} -> {dst} [label="{lbl}"];')

    lines.append("}")
    return "\n".join(lines)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Raw .dot file from PRISM -exportstrat")
    parser.add_argument("-o", "--output", help="Output .dot file (default: <input>_pretty.dot)")
    args = parser.parse_args()

    src  = Path(args.input)
    dest = Path(args.output) if args.output else src.with_stem(src.stem + "_pretty")

    text   = src.read_text()
    result = prettify(text)
    dest.write_text(result)
    print(f"Written: {dest}")
