// Disrupted Journey Model
// UK DfT Transport Personas
//
// Model type : Concurrent Stochastic Game (CSG)
// Players    : persona, operator, environment (disruption)
//
// Corridor   : Giffnock -> University of Glasgow
// Journey    : home (Giffnock) -> stop (Giffnock station) -> interchange (Glasgow Central) -> destination (UofG)
// Distances  : home->station 350m  |  Giffnock->Central 5 km  |  Central->UofG 2 km  |  direct 8 km
// Modes      : car, walk, bus (First Glasgow, Sc.2-GBP cap), ScotRail, taxi
// Sources    : ScotRail timetables | Scottish 2-GBP bus cap | UK DfT 2024 CO2e emission factors
//
// Persona files (params/personas/):
//   less_mobile          Seg 1 - Less Mobile Car Reliant     (Brian / Betty)
//   young_family         Seg 2 - Young Urban Families        (Farah)
//   older_less_affluent  Seg 3 - Older Less Affluent         (Gina)
//   empty_nester         Seg 4 - Comfortable Empty-nesters   (Jeff)
//   suburban_family      Seg 5 - Suburban Families           (Nigel)
//   elderly_no_car       Seg 7 - Elderly Low Income No Car   (Peter)
//   urban_professional   Seg 8 - Urban Professionals No Car  (Rosa)
//   young_low_income     Seg 9 - Young Low Income No Car     (Zoe / Zahir)

csg

player persona      m_persona                  endplayer
player operator     m_operator                 endplayer
player environment  m_service, m_accessibility, m_weather endplayer
//player environment m_service, m_accessibility, m_information_system, m_aggregate_demand endplayer


// -------------------------------------------------------
// Constants - set via param file or -const on command line
// -------------------------------------------------------
const bool   CAR_AVAILABLE;               // is the car available today?
const bool   NEEDS_STEP_FREE;             // requires step-free/accessible vehicle
const bool   HAS_BUS_PASS;               // free bus travel (persona=2 eligible)
const bool   HAS_BIKE;                   // persona owns a bike
const int    WALK_TOLERANCE;             // max walkable distance in metres
const int    BIKE_TOLERANCE;             // max cyclable distance in metres
const int    DISRUPTION_BUDGET;          // max number of disruptions the environment can apply
const int    FARE_MAX;                   // max fare persona is willing/able to spend (pence)
const double MINOR_DELAY_PROB;           // probability of a minor delay
const double MODERATE_DELAY_PROB;        // probability of a moderate delay
const double SEVERE_DELAY_PROB;          // probability of a severe delay
const double CANCEL_PROB;               // probability of service cancellation
const double LIFT_BREAK_PROB;           // probability lift breaks at interchange
const double NO_ACCESSIBLE_BUS_PROB;    // probability accessible bus unavailable (network-wide)
const double ASSIST_ALLOC_PROB;         // probability operator successfully allocates assistance
const int    ACCESSIBILITY_DISRUPTION_BUDGET;
const double RAIN_PROB;                  // probability of rain when weather disruption fires
const double SEVERE_WEATHER_PROB;        // probability of severe weather (forces congestion >= medium)
const int    WEATHER_DISRUPTION_BUDGET;  // max number of weather disruptions the environment can apply

formula can_disrupt         = disruptions_used         < DISRUPTION_BUDGET;
formula can_disrupt_access  = access_disruptions_used  < ACCESSIBILITY_DISRUPTION_BUDGET;
formula can_disrupt_weather = weather_disruptions_used < WEATHER_DISRUPTION_BUDGET;

// -------------------------------------------------------
// Locations
//   0 = at_home
//   1 = at_stop        (bus stop or station)
//   2 = at_interchange (transfer hub)
//   3 = at_destination
//   4 = journey_failed (absorbing: persona gave up after abandoning at home)
//
// Modes
//   0 = none  1=car  2=walk  3=bus  4=taxi  5=rail  6=bike
// ------------------------------------------------------- 

module m_persona

    loc                  : [0..4] init 0;
    mode                 : [0..6] init 0;
    abandon_journey      : bool   init false;
    fare_spent           : int    init 0;
    assistance_requested : bool   init false;
    planned              : bool   init false;

    // --- Planning step: gives environment one round to set conditions before departure ---
    [plan_trip] loc=0 & !planned & !abandon_journey
        -> (planned'=true);

    // --- Direct journeys from home ---

    // Car: all personas if available
    [choose_car] loc=0 & planned & CAR_AVAILABLE & !abandon_journey
        -> (loc'=3) & (mode'=1);

    // Taxi direct: all personas (expensive but always accessible)
    [taxi_direct] loc=0 & planned & !abandon_journey & fare_spent+1750<=FARE_MAX
        -> (loc'=3) & (mode'=4) & (fare_spent'=fare_spent+1750);

    // Walk direct: only if walk tolerance allows (8 km Giffnock->UofG; unreachable for all current personas)
    [walk_to_destination] loc=0 & planned & WALK_TOLERANCE>=8000 & !abandon_journey
        -> (loc'=3) & (mode'=2);

    // Bike direct: only if persona has a bike, tolerance covers 10.9 km corridor, and weather is good
    [bike_direct] loc=0 & planned & HAS_BIKE & BIKE_TOLERANCE>=10900 & weather=0 & !abandon_journey
        -> (loc'=3) & (mode'=6);


    // --- Access leg: home to stop ---

    [walk_to_stop] loc=0 & planned & WALK_TOLERANCE>=350 & !abandon_journey
        -> (loc'=1) & (mode'=2);


    // --- At stop ---

    // Request assistance: NEEDS_STEP_FREE personas only, before boarding
    [request_assistance] loc=1 & NEEDS_STEP_FREE & !assistance_requested & assistance_status=0 & !accessible_bus_stop & lift_status=1
        -> (assistance_requested'=true);

    // Bus: accessible vehicle required for NEEDS_STEP_FREE
    [board_bus] loc=1 & service_status<2 & (!NEEDS_STEP_FREE | accessible_bus_stop) & (HAS_BUS_PASS | fare_spent+245<=FARE_MAX)
        -> (loc'=2) & (mode'=3) & (fare_spent'=fare_spent+(HAS_BUS_PASS?0:245)) & (assistance_requested'=false);

    // Rail: lift or confirmed assistance required for NEEDS_STEP_FREE
    [board_rail] loc=1 & service_status<2 & (!NEEDS_STEP_FREE | lift_status=0 | assistance_status=3) & fare_spent+430<=FARE_MAX
        -> (loc'=2) & (mode'=5) & (fare_spent'=fare_spent+430) & (assistance_requested'=false);

    // Wait at stop: if service is delayed
    [wait_at_stop] loc=1 & service_status=1
        -> (loc'=loc);

    // Taxi from stop: all personas
    [taxi_from_stop] loc=1 & fare_spent+1600<=FARE_MAX
        -> (loc'=3) & (mode'=4) & (fare_spent'=fare_spent+1600);

    // Walk back home: if service is cancelled and no other option
    [walk_back_home] loc=1 & service_status=2 & WALK_TOLERANCE>=350
        -> (loc'=0) & (mode'=2) & (abandon_journey'=true);

    // Exit stop: last-resort escape for NEEDS_STEP_FREE personas in accessibility deadlock
    // All boarding options exhausted: lift broken, no accessible bus, assistance failed, taxi unaffordable
    [exit_stop] loc=1 & NEEDS_STEP_FREE
                & lift_status=1 & !accessible_bus_stop
                & assistance_status=4
                & fare_spent+1600>FARE_MAX
                & WALK_TOLERANCE>=350
        -> (loc'=0) & (mode'=2) & (abandon_journey'=true);


    // --- Final leg: interchange to destination ---

    // Request assistance at interchange: if accessible bus unavailable
    [request_assistance] loc=2 & NEEDS_STEP_FREE & !assistance_requested & assistance_status=0 & !accessible_bus_interchange
        -> (assistance_requested'=true);
    
    [final_leg_bus] loc=2 & service_status<2 & (!NEEDS_STEP_FREE | accessible_bus_interchange) & (HAS_BUS_PASS | fare_spent+245<=FARE_MAX)
        -> (loc'=3) & (mode'=3) & (fare_spent'=fare_spent+(HAS_BUS_PASS?0:245));

    [final_leg_walk] loc=2 & WALK_TOLERANCE>=2000
        -> (loc'=3) & (mode'=2);

    [final_leg_taxi] loc=2 & fare_spent+660<=FARE_MAX
        -> (loc'=3) & (mode'=4) & (fare_spent'=fare_spent+660);

    // Wait at interchange: if service is delayed
    [wait_at_stop] loc=2 & service_status=1
        -> (loc'=loc);

    [taxi_back_home_from_interchange] loc=2 & service_status=2 & fare_spent+1400<=FARE_MAX
        -> (loc'=0) & (mode'=4) & (abandon_journey'=true) & (fare_spent'=fare_spent+1400);


    // --- Absorbing states ---
    [done] loc=3
        -> (loc'=3);

    // Journey failed: persona walked back home and has no remaining options
    // abandon_journey=true means all loc=0 actions are blocked — give_up is the only exit
    [give_up] loc=0 & abandon_journey=true
        -> (loc'=4);

    [done_failed] loc=4
        -> (loc'=4);

endmodule





// -------------------------------------------------------
// Operator: manages passenger assistance lifecycle
// assistance_status: 0=none  1=requested  2=allocated  3=arrived  4=failed
// Reset at interchange enables a second assistance cycle if needed
// -------------------------------------------------------

module m_operator
    assistance_status : [0..4] init 0;

    [respond_to_request] assistance_requested & assistance_status=0
        -> ASSIST_ALLOC_PROB      : (assistance_status'=2)
         + (1-ASSIST_ALLOC_PROB)  : (assistance_status'=4);

    [assistance_arrives] assistance_status=2
        -> (assistance_status'=3);

    // Reset at interchange: allows new assistance cycle for final leg
    [reset_assistance] loc=2 & assistance_status>0
        -> (assistance_status'=0);

    [idle_m_operator] true
        -> true;

endmodule





// -------------------------------------------------------
// Environment: service disruptions
// service_status: 0=normal  1=delayed  2=cancelled
// delay_level:    0=none  1=minor  2=moderate  3=severe
// -------------------------------------------------------

module m_service
    service_status   : [0..2] init 0;
    delay_level      : [0..3] init 0;
    disruptions_used : [0..DISRUPTION_BUDGET] init 0;

    [add_disruption] can_disrupt
        -> MINOR_DELAY_PROB           : (service_status'=1) & (delay_level'=1) & (disruptions_used'=disruptions_used+1)
         + MODERATE_DELAY_PROB        : (service_status'=1) & (delay_level'=2) & (disruptions_used'=disruptions_used+1)
         + SEVERE_DELAY_PROB          : (service_status'=1) & (delay_level'=3) & (disruptions_used'=disruptions_used+1)
         + CANCEL_PROB                : (service_status'=2) & (delay_level'=0) & (disruptions_used'=disruptions_used+1)
         + (1-MINOR_DELAY_PROB-MODERATE_DELAY_PROB-SEVERE_DELAY_PROB-CANCEL_PROB)   : (service_status'=0) & (delay_level'=0);

    [idle_m_service] true
        -> true;

endmodule


// -------------------------------------------------------
// Environment: accessibility disruptions
// lift_status:            0=working  1=broken
// accessible_bus_stop:    true=available  false=unavailable
// accessible_bus_interchange: true=available  false=unavailable
// -------------------------------------------------------

module m_accessibility
    lift_status                : [0..1] init 0;
    accessible_bus_stop        : bool   init true;
    accessible_bus_interchange : bool   init true;
    access_disruptions_used    : [0..ACCESSIBILITY_DISRUPTION_BUDGET] init 0;

    [disrupt_accessibility] can_disrupt_access
        -> LIFT_BREAK_PROB           : (lift_status'=1) & (access_disruptions_used'=access_disruptions_used+1)
         + NO_ACCESSIBLE_BUS_PROB    : (accessible_bus_stop'=false) & (accessible_bus_interchange'=false) & (access_disruptions_used'=access_disruptions_used+1)
         + (1-LIFT_BREAK_PROB-NO_ACCESSIBLE_BUS_PROB)  : (lift_status'=0) & (accessible_bus_stop'=true) & (accessible_bus_interchange'=true);

    [idle_m_accessibility] true
        -> true;

endmodule



// -------------------------------------------------------
// Environment: weather and road conditions
// weather:         0=good  1=rain  2=severe
// road_congestion: 0=low   1=medium  2=high
// Severe weather always forces road_congestion >= medium.
// Congestion slows car/taxi (x1.5 medium, x2.0 high).
// Public transport and walking are unaffected by congestion.
// [bike_direct] guarded by weather=0 (no cycling in rain or severe)
// -------------------------------------------------------
module m_weather
    weather                  : [0..2] init 0;
    road_congestion          : [0..2] init 0;
    weather_disruptions_used : [0..WEATHER_DISRUPTION_BUDGET] init 0;

    [add_weather] can_disrupt_weather
        -> RAIN_PROB           : (weather'=1) & (road_congestion'=1) & (weather_disruptions_used'=weather_disruptions_used+1)
         + SEVERE_WEATHER_PROB : (weather'=2) & (road_congestion'=2) & (weather_disruptions_used'=weather_disruptions_used+1)
         + (1-RAIN_PROB-SEVERE_WEATHER_PROB) : (weather'=0) & (road_congestion'=0);

    [idle_m_weather] true -> true;

endmodule



// -------------------------------------------------------
// Rewards: travel time (minutes)
// Corridor: Giffnock -> UofG
//   car/taxi direct ~8 km | rail Giffnock->Central 12 min | bus ~35 min
//   Central->UofG walk 25 min (2 km) | bus 20 min | taxi 10 min
// Car/taxi times scale with road_congestion (x1.5 medium, x2.0 high).
// Public transport and walking are unaffected by congestion.
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
    [exit_stop]                          true              :   5;
endrewards

// -------------------------------------------------------
// Rewards: carbon emissions (grams CO2e)
// Source: UK DfT 2025 condensed set (scope 3, passenger-km)
//   car ~168 g/vkm | regular taxi 148.6 g/pkm | local bus 125.25 g/pkm | national rail 35.46 g/pkm
// Distances: car/taxi direct 8 km | bus/rail leg 5 km | final leg 2 km
//   taxi_from_stop 7 km | taxi_back_home 6 km
// -------------------------------------------------------
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

// -------------------------------------------------------
// Rewards: fare cost (pence)
// ScotRail Giffnock->Central anytime single: 430p (£4.30) — scotrail.co.uk
// First Glasgow adult single minimum: 245p (£2.45) — firstbus.co.uk/greater-glasgow
// Glasgow licensed taxi: £4.40 flag fall + £1.83/km — Glasgow City Council tariff
//   taxi_direct 8km: 1750p | taxi_from_stop 7km: 1600p
//   taxi_back_home 6km: 1400p | final_leg_taxi 2km: 660p
// -------------------------------------------------------
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

// -------------------------------------------------------
// Rewards: walking distance (metres)
// home->Giffnock station 350m | Glasgow Central->UofG 2000m | direct 8000m
// -------------------------------------------------------
rewards "walking_distance"
    [walk_to_stop]                       true          :  350;
    [walk_back_home]                     true          :  350;
    [exit_stop]                          true          :  350;
    [final_leg_walk]                     true          : 2000;
    [walk_to_destination]                true          : 8000;
endrewards






// Maybe grids ?
// Maybe : input : number of stops, time and mode of transport between each stop, and accessibility of each stop.
// For each stop : good stop ? (bus, rail, tram...), medium stop ? (bus only), bad stop ? (no service, or inaccessible) 
