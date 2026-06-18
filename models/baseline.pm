// Baseline Journey Model
// UK DfT Transport Personas - Glasgow Internship 2026
//
// Model type : Concurrent Stochastic Game (CSG)
// Players    : persona, environment (passive - no disruption)
//
// Journey    : home -> stop -> interchange -> destination
// Modes      : car, walk, bus, rail, taxi
//
// Persona types:
//   persona=0  less mobile, car reliant (e.g. Brian)
//   persona=1  young urban family       (e.g. Farah, Nigel)
//   persona=2  comfortable empty-nester (e.g. Jeff)

csg

player persona     m_persona     endplayer
player environment m_environment endplayer

// -------------------------------------------------------
// Constants - set via param file or -const on command line
// -------------------------------------------------------
const int  PERSONA;           // 0=less_mobile 1=young_family 2=empty_nester
const bool CAR_AVAILABLE;     // is the car available today?
const bool NEEDS_STEP_FREE;   // requires step-free/accessible vehicle (persona=0)
const bool HAS_BUS_PASS;      // free bus travel (persona=2 eligible)
const int  WALK_TOLERANCE;    // max walkable distance in metres

// -------------------------------------------------------
// Locations
//   0 = at_home
//   1 = at_stop        (bus stop or station)
//   2 = at_interchange (transfer hub)
//   3 = at_destination
//
// Modes
//   0 = none  1=car  2=walk  3=bus  4=taxi  5=rail
// -------------------------------------------------------

module m_persona

    loc  : [0..3] init 0;
    mode : [0..5] init 0;

    // --- Direct journeys from home ---

    // Car: all personas if available
    [choose_car] loc=0 & CAR_AVAILABLE -> (loc'=3) & (mode'=1);

    // Taxi direct: all personas (expensive but always accessible)
    [taxi_direct] loc=0 -> (loc'=3) & (mode'=4);

    // Walk direct: only if walk tolerance allows (not less-mobile)
    [walk_to_destination] loc=0 & WALK_TOLERANCE>=2000 -> (loc'=3) & (mode'=2);


    // --- Access leg: home to stop ---

    // Walk to stop: only if tolerance allows
    [walk_to_stop] loc=0 & WALK_TOLERANCE>=150 -> (loc'=1) & (mode'=2);


    // --- At stop: board public transport or taxi ---

    // Bus: available to all; less-mobile needs accessible vehicle (baseline: always available)
    [board_bus] loc=1 -> (loc'=2) & (mode'=3);

    // Rail: all personas
    [board_rail]  loc=1 -> (loc'=2) & (mode'=5);

    // Taxi from stop: all personas
    [taxi_from_stop] loc=1 & fare_spent+1200<=FARE_MAX -> (loc'=3) & (mode'=4) & (fare_spent'=fare_spent+1200);


    // --- Final leg: interchange to destination ---

    [final_leg_bus] loc=2 -> (loc'=3) & (mode'=3);

    [final_leg_walk] loc=2 & WALK_TOLERANCE>=500 -> (loc'=3) & (mode'=2);

    [final_leg_taxi] loc=2 -> (loc'=3) & (mode'=4);

    // --- Absorbing state ---
    [done] loc=3 -> (loc'=3);

endmodule

// -------------------------------------------------------
// Environment - passive in baseline
// (gains disruptive actions in disrupted.pm)
// -------------------------------------------------------
module m_environment

    env : [0..1] init 0;

    [idle] true -> 1 : (env'=0);

endmodule

// -------------------------------------------------------
// Rewards: travel time (minutes)
// -------------------------------------------------------
rewards "time"
    [choose_car]          true :  20;
    [taxi_direct]         true :  25;
    [walk_to_destination] true :  100;
    [walk_to_stop]        true :  10;
    [board_bus]           true :  20;
    [board_rail]          true :  15;
    [taxi_from_stop]      true :  20;
    [final_leg_bus]       true :  10;
    [final_leg_walk]      true :  25;
    [final_leg_taxi]      true :  10;
endrewards

// -------------------------------------------------------
// Rewards: carbon emissions (grams CO2e)
// -------------------------------------------------------
rewards "co2e"
    [choose_car]          true : 2800;
    [taxi_direct]         true : 2500;
    [walk_to_destination] true :    0;
    [walk_to_stop]        true :    0;
    [board_bus]           true :  300;
    [board_rail]          true :  200;
    [taxi_from_stop]      true :  2000;
    [final_leg_bus]       true :  150;
    [final_leg_walk]      true :    0;
    [final_leg_taxi]      true : 1000;
endrewards

// -------------------------------------------------------
// Rewards: fare cost (pence)
// HAS_BUS_PASS makes bus free for persona=2
// -------------------------------------------------------
rewards "fare"
    [choose_car]          true :   0;    // own car: fuel cost only (simplified)
    [taxi_direct]         true : 1500;   // taxi: expensive
    [board_bus]           HAS_BUS_PASS  :    0;   // free with bus pass
    [board_bus]           !HAS_BUS_PASS :  200;   // standard fare
    [board_rail]          true :  350;
    [taxi_from_stop]      true : 1200;
    [final_leg_bus]       HAS_BUS_PASS  :    0;
    [final_leg_bus]       !HAS_BUS_PASS :  150;
    [final_leg_taxi]      true :  600;
endrewards
