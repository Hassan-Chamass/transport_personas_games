"""
preprocessing.py
Compute PRISM const values from JSON config files.

Usage (standalone):
    python preprocessing.py [--trip giffnock_glasgow] [--fares giffnock_glasgow_fares]

Usage (imported):
    from preprocessing import get_trip_constants
    consts = get_trip_constants(trip="giffnock_glasgow", fares="giffnock_glasgow_fares")
    # consts is a dict {name: value} ready to be joined as PRISM -const arguments
"""

import json
import argparse
from pathlib import Path

PARAMS_DIR = Path(__file__).resolve().parent.parent / "params"


def _load(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def get_trip_constants(trip: str = "giffnock_glasgow",
                       fares: str = "giffnock_glasgow_fares") -> dict[str, int | float]:
    factors = _load(PARAMS_DIR / "dft_factors.json")
    trip_data = _load(PARAMS_DIR / "trip" / f"{trip}.json")
    fares_data = _load(PARAMS_DIR / "fares" / f"{fares}.json")

    seg   = trip_data["segments"]
    stop_modes  = trip_data.get("available_modes_from_stop",       {"bus": True, "rail": True})
    final_modes = trip_data.get("available_modes_from_interchange", {"bus": True})
    f_taxi  = factors["factors_g_per_pkm"]["taxi"]
    f_bus   = factors["factors_g_per_pkm"]["local_bus"]
    f_rail  = factors["factors_g_per_pkm"]["national_rail"]
    f_car   = factors["car_g_per_vkm"]

    def co2e(dist_km: float, factor: float) -> int:
        return round(dist_km * factor)

    base  = fares_data["base_fares"]
    lf    = fares_data["policy_overrides"]["low_fare"]
    rc    = fares_data["policy_overrides"]["road_charge"]
    surge = rc["surcharge"]

    consts: dict[str, int | float] = {
        # --- distance constants (metres) ---
        "DIST_HOME_TO_STOP":         round(seg["walk_to_stop"]["dist_km"] * 1000),
        "DIST_INTERCHANGE_TO_DEST":  round(seg["walk_interchange_to_dest"]["dist_km"] * 1000),
        "DIST_HOME_TO_DEST":         round(seg["walk_direct"]["dist_km"] * 1000),

        # --- CO2e constants (grams, rounded to nearest integer) ---
        "CO2E_CAR_DIRECT":       co2e(seg["car_direct"]["dist_km"],        f_car),
        "CO2E_TAXI_DIRECT":      co2e(seg["taxi_direct"]["dist_km"],       f_taxi),
        "CO2E_TAXI_STOP":        co2e(seg["taxi_from_stop"]["dist_km"],    f_taxi),
        "CO2E_TAXI_FINAL":       co2e(seg["taxi_final_leg"]["dist_km"],    f_taxi),
        "CO2E_TAXI_HOME":        co2e(seg["taxi_back_home"]["dist_km"],    f_taxi),
        "CO2E_BUS_STOP_TO_INT":  co2e(seg["bus_stop_to_interchange"]["dist_km"],  f_bus),
        "CO2E_RAIL_STOP_TO_INT": co2e(seg["rail_stop_to_interchange"]["dist_km"], f_rail),
        "CO2E_BUS_FINAL":        co2e(seg["bus_interchange_to_dest"]["dist_km"],  f_bus),
        "CO2E_RAIL_FINAL":       co2e(seg["rail_interchange_to_dest"]["dist_km"], f_rail),

        # --- time constants (minutes) ---
        "TIME_CAR_CLEAR":             seg["car_direct"]["time_min"]["clear"],
        "TIME_CAR_RAIN":              seg["car_direct"]["time_min"]["rain"],
        "TIME_CAR_SEVERE":            seg["car_direct"]["time_min"]["severe"],
        "TIME_TAXI_DIRECT_CLEAR":     seg["taxi_direct"]["time_min"]["clear"],
        "TIME_TAXI_DIRECT_RAIN":      seg["taxi_direct"]["time_min"]["rain"],
        "TIME_TAXI_DIRECT_SEVERE":    seg["taxi_direct"]["time_min"]["severe"],
        "TIME_TAXI_STOP_CLEAR":       seg["taxi_from_stop"]["time_min"]["clear"],
        "TIME_TAXI_STOP_RAIN":        seg["taxi_from_stop"]["time_min"]["rain"],
        "TIME_TAXI_STOP_SEVERE":      seg["taxi_from_stop"]["time_min"]["severe"],
        "TIME_TAXI_FINAL_CLEAR":      seg["taxi_final_leg"]["time_min"]["clear"],
        "TIME_TAXI_FINAL_RAIN":       seg["taxi_final_leg"]["time_min"]["rain"],
        "TIME_TAXI_FINAL_SEVERE":     seg["taxi_final_leg"]["time_min"]["severe"],
        "TIME_TAXI_HOME_CLEAR":       seg["taxi_back_home"]["time_min"]["clear"],
        "TIME_TAXI_HOME_RAIN":        seg["taxi_back_home"]["time_min"]["rain"],
        "TIME_TAXI_HOME_SEVERE":      seg["taxi_back_home"]["time_min"]["severe"],
        "TIME_BUS_STOP_TO_INT":       seg["bus_stop_to_interchange"]["time_min"],
        "TIME_RAIL_STOP_TO_INT":      seg["rail_stop_to_interchange"]["time_min"],
        "TIME_FINAL_BUS":             seg["bus_interchange_to_dest"]["time_min"],
        "TIME_FINAL_RAIL":            seg["rail_interchange_to_dest"]["time_min"],
        "TIME_FINAL_WALK":            seg["walk_interchange_to_dest"]["time_min"],
        "TIME_WALK_TO_STOP":          seg["walk_to_stop"]["time_min"],
        "TIME_BIKE_DIRECT":           seg["bike_direct"]["time_min"],
        "TIME_WALK_TO_DEST":          seg["walk_direct"]["time_min"],

        # --- fare constants (pence) ---
        "BUS_FARE_BASE":              base["bus"],
        "BUS_FARE_LOW":               lf["bus"],
        "RAIL_FARE_BASE":             base["rail"],
        "RAIL_FARE_LOW":              lf["rail"],
        "TAXI_DIRECT_FARE_BASE":      base["taxi_direct"],
        "TAXI_STOP_FARE_BASE":        base["taxi_stop"],
        "TAXI_FINAL_FARE_BASE":       base["taxi_final"],
        "TAXI_HOME_FARE_BASE":        base["taxi_home"],
        "ROAD_CHARGE_SURCHARGE":      surge,

        # --- mode availability flags ---
        "HAS_BUS_STOP":  "true" if stop_modes["bus"]    else "false",
        "HAS_RAIL_STOP": "true" if stop_modes["rail"]   else "false",
        "HAS_BUS_FINAL": "true" if final_modes["bus"]   else "false",
        "HAS_RAIL_FINAL":"true" if final_modes["rail"]  else "false",
    }

    return consts


def to_prism_const_string(consts: dict) -> str:
    """Return a comma-separated PRISM -const argument string."""
    return ",".join(f"{k}={v}" for k, v in consts.items())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute PRISM constants from JSON config.")
    parser.add_argument("--trip",  default="giffnock_glasgow")
    parser.add_argument("--fares", default="giffnock_glasgow_fares")
    args = parser.parse_args()

    consts = get_trip_constants(trip=args.trip, fares=args.fares)

    print("Computed constants:")
    for name, val in consts.items():
        print(f"  {name} = {val}")

    print("\nPRISM -const string:")
    print(to_prism_const_string(consts))
