// Disrupted Journey Model — Turn-Based SMG
// UK DfT Transport Personas
//
// Model type : Stochastic Multi-Player Game (SMG)
// Players    : environment, persona, operator
//
// Turn order : environment -> persona -> operator -> repeat
//
// Turn enforcement (NO shared action labels between players):
//   Each player owns a boolean "done" flag in its own module.
//   Turn conditions derived purely by reading other players' flags:
//
//   env acts    when: !env_done & !pers_done & !op_done
//   persona acts when: env_done  & !pers_done
//   operator acts when: pers_done & !op_done
//
//   Between rounds (all three done), a reset cycle fires sequentially:
//     env fires   [env_new_round]  (env_done=T,pers_done=T,op_done=T) -> env_done=false
//     persona fires [pers_reset]   (!env_done,pers_done=T,op_done=T)  -> pers_done=false
//     operator fires [op_reset]    (!env_done,!pers_done,op_done=T)   -> op_done=false
//   -> back to !env_done & !pers_done & !op_done (env's turn)
//
//   This guarantees exactly one player has available actions in every state,
//   with fully disjoint action label sets across players.
//
// Differences from disrupted.pm (CSG):
//   - smg instead of csg
//   - plan_trip removed — environment always acts first
//   - wait_for_assistance added
//   - skip_operator + op_reset added
//   - Multi-objective properties (multi(...)) now supported
//
// Corridor : Giffnock -> University of Glasgow
// Modes    : car=1  walk=2  bus=3  taxi=4  rail=5  bike=6

smg

player environment  m_environment,
    [add_service_disruption], [disrupt_accessibility], [add_weather], [env_idle], [env_new_round]
endplayer
player persona      m_persona,
    [pers_reset], [done], [done_failed], [give_up],
    [choose_car], [taxi_direct], [walk_to_destination], [bike_direct], [walk_to_stop],
    [request_assistance], [board_bus], [board_rail], [wait_at_stop], [wait_for_assistance],
    [taxi_from_stop], [walk_back_home], [exit_stop],
    [final_leg_bus], [final_leg_walk], [final_leg_taxi], [taxi_back_home_from_interchange]
endplayer
player operator     m_operator,
    [op_reset], [respond_to_request], [assistance_arrives], [reset_assistance], [skip_operator]
endplayer


// -------------------------------------------------------
// Constants — identical to disrupted.pm
// -------------------------------------------------------
const bool   CAR_AVAILABLE;
const bool   NEEDS_STEP_FREE;
const bool   HAS_BUS_PASS;
const bool   HAS_BIKE;
const int    WALK_TOLERANCE;
const int    BIKE_TOLERANCE;
const int    DISRUPTION_BUDGET;
const int    FARE_MAX;
const double MINOR_DELAY_PROB;
const double MODERATE_DELAY_PROB;
const double SEVERE_DELAY_PROB;
const double CANCEL_PROB;
const double LIFT_BREAK_PROB;
const double NO_ACCESSIBLE_BUS_PROB;
const double ASSIST_ALLOC_PROB;
const int    ACCESSIBILITY_DISRUPTION_BUDGET;
const double RAIN_PROB;
const double SEVERE_WEATHER_PROB;
const int    WEATHER_DISRUPTION_BUDGET;

formula can_disrupt         = disruptions_used         < DISRUPTION_BUDGET;
formula can_disrupt_access  = access_disruptions_used  < ACCESSIBILITY_DISRUPTION_BUDGET;
formula can_disrupt_weather = weather_disruptions_used < WEATHER_DISRUPTION_BUDGET;

// -------------------------------------------------------
// Locations
//   0=home  1=stop  2=interchange  3=destination  4=journey_failed
// Modes
//   0=none  1=car  2=walk  3=bus  4=taxi  5=rail  6=bike
// -------------------------------------------------------


// -------------------------------------------------------
// Environment: merged service + accessibility + weather
// Acts when: !env_done & !pers_done & !op_done
// After acting: env_done=true
// -------------------------------------------------------
module m_environment

    env_done : bool init false;

    // Service
    service_status   : [0..2] init 0;
    delay_level      : [0..3] init 0;
    disruptions_used : [0..DISRUPTION_BUDGET] init 0;

    // Accessibility
    lift_status                : [0..1] init 0;
    accessible_bus_stop        : bool   init true;
    accessible_bus_interchange : bool   init true;
    access_disruptions_used    : [0..ACCESSIBILITY_DISRUPTION_BUDGET] init 0;

    // Weather
    weather                  : [0..2] init 0;
    road_congestion          : [0..2] init 0;
    weather_disruptions_used : [0..WEATHER_DISRUPTION_BUDGET] init 0;

    // --- Disruption choices (adversary picks one) ---

    [add_service_disruption] !env_done & !pers_done & !op_done & can_disrupt & loc<3
        -> MINOR_DELAY_PROB                                                        : (service_status'=1) & (delay_level'=1) & (disruptions_used'=disruptions_used+1) & (env_done'=true)
         + MODERATE_DELAY_PROB                                                     : (service_status'=1) & (delay_level'=2) & (disruptions_used'=disruptions_used+1) & (env_done'=true)
         + SEVERE_DELAY_PROB                                                       : (service_status'=1) & (delay_level'=3) & (disruptions_used'=disruptions_used+1) & (env_done'=true)
         + CANCEL_PROB                                                             : (service_status'=2) & (delay_level'=0) & (disruptions_used'=disruptions_used+1) & (env_done'=true)
         + (1-MINOR_DELAY_PROB-MODERATE_DELAY_PROB-SEVERE_DELAY_PROB-CANCEL_PROB) : (service_status'=0) & (delay_level'=0) & (disruptions_used'=disruptions_used+1) & (env_done'=true);

    [disrupt_accessibility] !env_done & !pers_done & !op_done & can_disrupt_access & loc<3
        -> LIFT_BREAK_PROB                            : (lift_status'=1) & (access_disruptions_used'=access_disruptions_used+1) & (env_done'=true)
         + NO_ACCESSIBLE_BUS_PROB                     : (accessible_bus_stop'=false) & (accessible_bus_interchange'=false) & (access_disruptions_used'=access_disruptions_used+1) & (env_done'=true)
         + (1-LIFT_BREAK_PROB-NO_ACCESSIBLE_BUS_PROB) : (lift_status'=0) & (accessible_bus_stop'=true) & (accessible_bus_interchange'=true) & (access_disruptions_used'=access_disruptions_used+1) & (env_done'=true);

    [add_weather] !env_done & !pers_done & !op_done & can_disrupt_weather & loc<3
        -> RAIN_PROB                          : (weather'=1) & (road_congestion'=1) & (weather_disruptions_used'=weather_disruptions_used+1) & (env_done'=true)
         + SEVERE_WEATHER_PROB                : (weather'=2) & (road_congestion'=2) & (weather_disruptions_used'=weather_disruptions_used+1) & (env_done'=true)
         + (1-RAIN_PROB-SEVERE_WEATHER_PROB)  : (weather'=0) & (road_congestion'=0) & (weather_disruptions_used'=weather_disruptions_used+1) & (env_done'=true);

    // --- Pass turn (no disruption chosen, or in absorbing state) ---
    [env_idle] !env_done & !pers_done & !op_done
        -> (env_done'=true);

    // --- Between-round reset: fires when all three players are done ---
    [env_new_round] env_done & pers_done & op_done
        -> (env_done'=false);

endmodule


// -------------------------------------------------------
// Persona: journey decision-making
// Acts when: env_done & !pers_done
// After acting: pers_done=true
// -------------------------------------------------------
module m_persona

    pers_done : bool init false;

    loc                  : [0..4] init 0;
    mode                 : [0..6] init 0;
    abandon_journey      : bool   init false;
    fare_spent           : int    init 0;
    assistance_requested : bool   init false;

    // --- Between-round reset ---
    [pers_reset] !env_done & pers_done & op_done
        -> (pers_done'=false);

    // --- Absorbing states ---
    [done]        loc=3 & env_done & !pers_done -> (pers_done'=true);
    [done_failed] loc=4 & env_done & !pers_done -> (pers_done'=true);

    // --- Give up ---
    [give_up] loc=0 & abandon_journey & env_done & !pers_done
        -> (loc'=4) & (pers_done'=true);


    // -------------------------------------------------------
    // At home (loc=0)
    // -------------------------------------------------------

    [choose_car] loc=0 & !abandon_journey & env_done & !pers_done & CAR_AVAILABLE
        -> (loc'=3) & (mode'=1) & (pers_done'=true);

    [taxi_direct] loc=0 & !abandon_journey & env_done & !pers_done & fare_spent+1750<=FARE_MAX
        -> (loc'=3) & (mode'=4) & (fare_spent'=fare_spent+1750) & (pers_done'=true);

    [walk_to_destination] loc=0 & !abandon_journey & env_done & !pers_done & WALK_TOLERANCE>=8000
        -> (loc'=3) & (mode'=2) & (pers_done'=true);

    [bike_direct] loc=0 & !abandon_journey & env_done & !pers_done & HAS_BIKE & BIKE_TOLERANCE>=10900 & weather=0
        -> (loc'=3) & (mode'=6) & (pers_done'=true);

    [walk_to_stop] loc=0 & !abandon_journey & env_done & !pers_done & WALK_TOLERANCE>=350
        -> (loc'=1) & (mode'=2) & (pers_done'=true);


    // -------------------------------------------------------
    // At stop (loc=1)
    // -------------------------------------------------------

    [request_assistance] loc=1 & env_done & !pers_done & NEEDS_STEP_FREE & !assistance_requested & assistance_status=0 & !accessible_bus_stop & lift_status=1
        -> (assistance_requested'=true) & (pers_done'=true);

    [board_bus] loc=1 & env_done & !pers_done & service_status<2 & (!NEEDS_STEP_FREE | accessible_bus_stop) & (HAS_BUS_PASS | fare_spent+245<=FARE_MAX)
        -> (loc'=2) & (mode'=3) & (fare_spent'=fare_spent+(HAS_BUS_PASS?0:245)) & (assistance_requested'=false) & (pers_done'=true);

    [board_rail] loc=1 & env_done & !pers_done & service_status<2 & (!NEEDS_STEP_FREE | lift_status=0 | assistance_status=3) & fare_spent+430<=FARE_MAX
        -> (loc'=2) & (mode'=5) & (fare_spent'=fare_spent+430) & (assistance_requested'=false) & (pers_done'=true);

    [wait_at_stop] loc=1 & env_done & !pers_done & service_status=1
        -> (pers_done'=true);

    [wait_for_assistance] loc=1 & env_done & !pers_done & NEEDS_STEP_FREE & assistance_status=2
        -> (pers_done'=true);

    [taxi_from_stop] loc=1 & env_done & !pers_done & fare_spent+1600<=FARE_MAX
        -> (loc'=3) & (mode'=4) & (fare_spent'=fare_spent+1600) & (pers_done'=true);

    [walk_back_home] loc=1 & env_done & !pers_done & service_status=2 & WALK_TOLERANCE>=350
        -> (loc'=0) & (mode'=2) & (abandon_journey'=true) & (pers_done'=true);

    [exit_stop] loc=1 & env_done & !pers_done & NEEDS_STEP_FREE
                & lift_status=1 & !accessible_bus_stop
                & assistance_status=4
                & fare_spent+1600>FARE_MAX
                & WALK_TOLERANCE>=350
        -> (loc'=0) & (mode'=2) & (abandon_journey'=true) & (pers_done'=true);


    // -------------------------------------------------------
    // At interchange (loc=2)
    // -------------------------------------------------------

    [request_assistance] loc=2 & env_done & !pers_done & NEEDS_STEP_FREE & !assistance_requested & assistance_status=0 & !accessible_bus_interchange
        -> (assistance_requested'=true) & (pers_done'=true);

    [final_leg_bus] loc=2 & env_done & !pers_done & service_status<2 & (!NEEDS_STEP_FREE | accessible_bus_interchange) & (HAS_BUS_PASS | fare_spent+245<=FARE_MAX)
        -> (loc'=3) & (mode'=3) & (fare_spent'=fare_spent+(HAS_BUS_PASS?0:245)) & (pers_done'=true);

    [final_leg_walk] loc=2 & env_done & !pers_done & WALK_TOLERANCE>=2000
        -> (loc'=3) & (mode'=2) & (pers_done'=true);

    [final_leg_taxi] loc=2 & env_done & !pers_done & fare_spent+660<=FARE_MAX
        -> (loc'=3) & (mode'=4) & (fare_spent'=fare_spent+660) & (pers_done'=true);

    [wait_at_stop] loc=2 & env_done & !pers_done & service_status=1
        -> (pers_done'=true);

    [wait_for_assistance] loc=2 & env_done & !pers_done & NEEDS_STEP_FREE & assistance_status=2
        -> (pers_done'=true);

    [taxi_back_home_from_interchange] loc=2 & env_done & !pers_done & service_status=2 & fare_spent+1400<=FARE_MAX
        -> (loc'=0) & (mode'=4) & (abandon_journey'=true) & (fare_spent'=fare_spent+1400) & (pers_done'=true);

endmodule


// -------------------------------------------------------
// Operator: manages passenger assistance lifecycle
// Acts when: pers_done & !op_done
// After acting: op_done=true
// -------------------------------------------------------
module m_operator

    op_done : bool init false;
    assistance_status : [0..4] init 0;

    // --- Between-round reset ---
    [op_reset] !env_done & !pers_done & op_done
        -> (op_done'=false);

    // --- Assistance actions ---

    [respond_to_request] pers_done & !op_done & assistance_requested & assistance_status=0
        -> ASSIST_ALLOC_PROB     : (assistance_status'=2) & (op_done'=true)
         + (1-ASSIST_ALLOC_PROB) : (assistance_status'=4) & (op_done'=true);

    [assistance_arrives] pers_done & !op_done & assistance_status=2
        -> (assistance_status'=3) & (op_done'=true);

    [reset_assistance] pers_done & !op_done & loc=2 & assistance_status>0 & assistance_status!=2
        -> (assistance_status'=0) & (op_done'=true);

    // --- Skip: nothing to do this turn ---
    [skip_operator] pers_done & !op_done
                  & !(assistance_requested & assistance_status=0)
                  & assistance_status!=2
                  & !(loc=2 & assistance_status>0 & assistance_status!=2)
        -> (op_done'=true);

endmodule


// -------------------------------------------------------
// Rewards — action labels identical to disrupted.pm
// (env_new_round, pers_reset, op_reset have no reward entries -> 0)
// -------------------------------------------------------

rewards "time"
    [choose_car]                         road_congestion=0 :  30;
    [choose_car]                         road_congestion=1 :  45;
    [choose_car]                         road_congestion=2 :  60;
    [taxi_direct]                        road_congestion=0 :  28;
    [taxi_direct]                        road_congestion=1 :  42;
    [taxi_direct]                        road_congestion=2 :  56;
    [taxi_from_stop]                     road_congestion=0 :  22;
    [taxi_from_stop]                     road_congestion=1 :  33;
    [taxi_from_stop]                     road_congestion=2 :  44;
    [final_leg_taxi]                     road_congestion=0 :  10;
    [final_leg_taxi]                     road_congestion=1 :  15;
    [final_leg_taxi]                     road_congestion=2 :  20;
    [taxi_back_home_from_interchange]    road_congestion=0 :  20;
    [taxi_back_home_from_interchange]    road_congestion=1 :  30;
    [taxi_back_home_from_interchange]    road_congestion=2 :  40;
    [bike_direct]                        true              :  44;
    [walk_to_destination]                true              :  96;
    [walk_to_stop]                       true              :   5;
    [walk_back_home]                     true              :   5;
    [board_bus]                          true              :  35;
    [board_rail]                         true              :  12;
    [final_leg_bus]                      true              :  20;
    [final_leg_walk]                     true              :  25;
    [wait_at_stop]                       delay_level=1     :   5;
    [wait_at_stop]                       delay_level=2     :  15;
    [wait_at_stop]                       delay_level=3     :  30;
    [request_assistance]                 true              :   5;
    [assistance_arrives]                 true              :  10;
    [wait_for_assistance]                true              :   5;
    [exit_stop]                          true              :   5;
endrewards

rewards "co2e"
    [choose_car]                         true : 1350;
    [taxi_direct]                        true : 1189;
    [bike_direct]                        true :    0;
    [walk_to_destination]                true :    0;
    [walk_to_stop]                       true :    0;
    [walk_back_home]                     true :    0;
    [taxi_from_stop]                     true : 1040;
    [board_bus]                          true :  626;
    [board_rail]                         true :  177;
    [final_leg_bus]                      true :  251;
    [final_leg_walk]                     true :    0;
    [final_leg_taxi]                     true :  297;
    [taxi_back_home_from_interchange]    true :  892;
    [exit_stop]                          true :    0;
endrewards

rewards "fare"
    [bike_direct]                        true          :    0;
    [choose_car]                         true          :    0;
    [taxi_direct]                        true          : 1750;
    [taxi_from_stop]                     true          : 1600;
    [board_bus]                          HAS_BUS_PASS  :    0;
    [board_bus]                          !HAS_BUS_PASS :  245;
    [board_rail]                         true          :  430;
    [final_leg_bus]                      HAS_BUS_PASS  :    0;
    [final_leg_bus]                      !HAS_BUS_PASS :  245;
    [final_leg_taxi]                     true          :  660;
    [taxi_back_home_from_interchange]    true          : 1400;
endrewards

rewards "walking_distance"
    [walk_to_stop]                       true          :  350;
    [walk_back_home]                     true          :  350;
    [exit_stop]                          true          :  350;
    [final_leg_walk]                     true          : 2000;
    [walk_to_destination]                true          : 8000;
endrewards
