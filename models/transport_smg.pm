// ============================================================
// transport_smg.pm
// UK DfT Transport Personas -- Turn-Based Stochastic Multi-Player Game
//
// Formalism  : Turn-Based SMG (smg) for PRISM-games 3.2.4
// Players    : manager (sets transport policy once), persona (navigates journey)
// Environment: probabilistic, embedded in player action outcomes -- no env player
//
// Corridor   : home(0) -> stop/station(1) -> interchange(2) -> destination(3)
//   Distances and times supplied via preprocessing constants (see params/scenarios/)
//
// Modes      : 0=none  1=car  2=walk  3=bus  4=taxi  5=rail  6=bike
// Policies   : 0=normal  1=high_freq  2=low_fare  3=road_charge  4=accessible_service
//
// Phase structure (global phase variable):
//   phase=0  manager acts once: picks policy + observable conditions sampled
//   phase=1  persona acts per leg until done=true
//
// Key design choices:
//   - Manager acts exactly once at phase=0 (12-branch sampling of weather x lift_ok x acc_bus)
//   - set_accessible_service guarantees lift_ok=true and acc_bus=true (3 branches: weather only)
//   - In-journey disruptions are probabilistic outcomes within persona's boarding actions
//   - disruptions_used tracks budget; once exhausted, all service runs without disruption
//   - done=true is absorbing (success at loc=3 or abandon via give_up)
//   - FAIL_PENALTY=999 in time reward makes give_up never strategically optimal unless stuck
//
// Note on fare reward: charged on every boarding attempt including failed ones (delay/cancel).
//   fare_spent state variable tracks actual payments (successful boardings only).
//   Discrepancy is at most 1 extra fare per disrupted leg (small for DISRUPTION_BUDGET<=2).
// ============================================================

smg

player manager
    m_manager,
    [set_normal], [set_high_freq], [set_low_fare], [set_road_charge], [set_accessible_service]
endplayer

player persona
    m_persona,
    [done_loop], [give_up],
    [choose_car], [taxi_direct], [bike_direct], [walk_to_destination], [walk_to_stop],
    [board_bus], [board_rail], [wait_at_stop], [taxi_from_stop], [walk_back_home],
    [final_leg_bus], [final_leg_rail], [final_leg_walk], [final_leg_taxi], [taxi_back_home]
endplayer

global phase : [0..1] init 0;

// -------------------------------------------------------
// Constants -- Persona (supplied via params/personas/*.json)
// -------------------------------------------------------
const bool CAR_AVAILABLE;
const bool NEEDS_STEP_FREE;
const bool HAS_BUS_PASS;
const bool HAS_BIKE;
const int  WALK_TOLERANCE;
const int  BIKE_TOLERANCE;
const int  FARE_MAX;

// -------------------------------------------------------
// Constants -- Scenario (supplied via params/scenarios/*.json)
// -------------------------------------------------------
const int    DISRUPTION_BUDGET;
const double MINOR_DELAY_PROB;
const double MODERATE_DELAY_PROB;
const double SEVERE_DELAY_PROB;
const double CANCEL_PROB;
const double LIFT_BREAK_PROB;
const double NO_ACCESSIBLE_BUS_PROB;
const double RAIN_PROB;
const double SEVERE_WEATHER_PROB;

// Legacy constants (removed from new model logic; kept for backward compatibility with old scenario JSONs)
const double ASSIST_ALLOC_PROB              ;
const int    ACCESSIBILITY_DISRUPTION_BUDGET;
const int    WEATHER_DISRUPTION_BUDGET      ;

// -------------------------------------------------------
// Failure penalty
// 999 min >> any realistic journey time; give_up is never
// strategically preferred over any valid transport option
// -------------------------------------------------------
const int FAIL_PENALTY = 999;

// -------------------------------------------------------
// Constants -- Trip geometry (supplied via preprocessing.py)
// -------------------------------------------------------

// Distance constants (metres)
const int DIST_HOME_TO_STOP;
const int DIST_INTERCHANGE_TO_DEST;
const int DIST_HOME_TO_DEST;

// CO2e constants (grams, computed from distances x DfT factors)
const int CO2E_CAR_DIRECT;
const int CO2E_TAXI_DIRECT;
const int CO2E_TAXI_STOP;
const int CO2E_TAXI_FINAL;
const int CO2E_TAXI_HOME;
const int CO2E_BUS_STOP_TO_INT;
const int CO2E_RAIL_STOP_TO_INT;
const int CO2E_BUS_FINAL;
const int CO2E_RAIL_FINAL;

// Time constants (minutes)
const int TIME_CAR_CLEAR;         const int TIME_CAR_RAIN;         const int TIME_CAR_SEVERE;
const int TIME_TAXI_DIRECT_CLEAR; const int TIME_TAXI_DIRECT_RAIN; const int TIME_TAXI_DIRECT_SEVERE;
const int TIME_TAXI_STOP_CLEAR;   const int TIME_TAXI_STOP_RAIN;   const int TIME_TAXI_STOP_SEVERE;
const int TIME_TAXI_FINAL_CLEAR;  const int TIME_TAXI_FINAL_RAIN;  const int TIME_TAXI_FINAL_SEVERE;
const int TIME_TAXI_HOME_CLEAR;   const int TIME_TAXI_HOME_RAIN;   const int TIME_TAXI_HOME_SEVERE;
const int TIME_BUS_STOP_TO_INT;
const int TIME_RAIL_STOP_TO_INT;
const int TIME_FINAL_BUS;
const int TIME_FINAL_RAIL;
const int TIME_FINAL_WALK;
const int TIME_WALK_TO_STOP;
const int TIME_BIKE_DIRECT;
const int TIME_WALK_TO_DEST;

// Fare constants (pence)
const int BUS_FARE_BASE;
const int BUS_FARE_LOW;
const int RAIL_FARE_BASE;
const int RAIL_FARE_LOW;
const int TAXI_DIRECT_FARE_BASE;
const int TAXI_STOP_FARE_BASE;
const int TAXI_FINAL_FARE_BASE;
const int TAXI_HOME_FARE_BASE;
const int ROAD_CHARGE_SURCHARGE;

// Mode availability flags (supplied via preprocessing.py)
const bool HAS_BUS_STOP;
const bool HAS_RAIL_STOP;
const bool HAS_BUS_FINAL;
const bool HAS_RAIL_FINAL;

// -------------------------------------------------------
// Formulas
// -------------------------------------------------------

formula road_congestion = weather=2 ? 2 : (weather=1 ? 1 : 0);

formula bus_fare         = HAS_BUS_PASS ? 0 : (policy=2 ? BUS_FARE_LOW : BUS_FARE_BASE);
formula rail_fare        = policy=2 ? RAIL_FARE_LOW : RAIL_FARE_BASE;
formula taxi_direct_fare = policy=3 ? TAXI_DIRECT_FARE_BASE+ROAD_CHARGE_SURCHARGE : TAXI_DIRECT_FARE_BASE;
formula taxi_stop_fare   = policy=3 ? TAXI_STOP_FARE_BASE+ROAD_CHARGE_SURCHARGE   : TAXI_STOP_FARE_BASE;
formula taxi_final_fare  = policy=3 ? TAXI_FINAL_FARE_BASE+ROAD_CHARGE_SURCHARGE  : TAXI_FINAL_FARE_BASE;
formula taxi_home_fare   = policy=3 ? TAXI_HOME_FARE_BASE+ROAD_CHARGE_SURCHARGE   : TAXI_HOME_FARE_BASE;

// Effective disruption probabilities -- halved under high_freq policy
formula eff_cancel = policy=1 ? CANCEL_PROB * 0.5 : CANCEL_PROB;
formula eff_delay  = policy=1 ? (MINOR_DELAY_PROB + MODERATE_DELAY_PROB + SEVERE_DELAY_PROB) * 0.5
                               : (MINOR_DELAY_PROB + MODERATE_DELAY_PROB + SEVERE_DELAY_PROB);
formula eff_ok     = 1.0 - eff_cancel - eff_delay;

// Average delay duration (minutes) -- weighted by relative probability of each delay tier
// Guard: if all delay probs are 0, eff_delay=0 so wait_at_stop is unreachable anyway
formula avg_wait_time =
    (MINOR_DELAY_PROB + MODERATE_DELAY_PROB + SEVERE_DELAY_PROB) > 0 ?
    (MINOR_DELAY_PROB*5.0 + MODERATE_DELAY_PROB*15.0 + SEVERE_DELAY_PROB*30.0)
      / (MINOR_DELAY_PROB + MODERATE_DELAY_PROB + SEVERE_DELAY_PROB)
    : 0.0;

// Stuck formulas: true when the persona has no action available at a given location
// Used to gate give_up -- persona can only abandon when genuinely trapped

formula stuck_home =
    !CAR_AVAILABLE
    & fare_spent+taxi_direct_fare>FARE_MAX
    & (!HAS_BIKE | weather!=0 | BIKE_TOLERANCE<DIST_HOME_TO_DEST)
    & WALK_TOLERANCE<DIST_HOME_TO_DEST
    & WALK_TOLERANCE<DIST_HOME_TO_STOP;

formula stuck_stop =
    service_status!=1
    & !(service_status=0 & HAS_BUS_STOP & (!NEEDS_STEP_FREE|acc_bus) & (HAS_BUS_PASS|fare_spent+bus_fare<=FARE_MAX))
    & !(service_status=0 & HAS_RAIL_STOP & (!NEEDS_STEP_FREE|lift_ok) & fare_spent+rail_fare<=FARE_MAX)
    & fare_spent+taxi_stop_fare>FARE_MAX
    & (service_status!=2 | WALK_TOLERANCE<DIST_HOME_TO_STOP);

formula stuck_interchange =
    service_status!=1
    & !(service_status=0 & HAS_BUS_FINAL  & (!NEEDS_STEP_FREE|acc_bus) & (HAS_BUS_PASS|fare_spent+bus_fare<=FARE_MAX))
    & !(service_status=0 & HAS_RAIL_FINAL & (!NEEDS_STEP_FREE|lift_ok) & fare_spent+rail_fare<=FARE_MAX)
    & WALK_TOLERANCE<DIST_INTERCHANGE_TO_DEST
    & fare_spent+taxi_final_fare>FARE_MAX
    & (service_status!=2 | fare_spent+taxi_home_fare>FARE_MAX);

// Manager sampling branch probabilities (weather x lift_ok x acc_bus are independent)
formula p_w0   = 1.0 - RAIN_PROB - SEVERE_WEATHER_PROB;
formula p_w1   = RAIN_PROB;
formula p_w2   = SEVERE_WEATHER_PROB;
formula p_lok  = 1.0 - LIFT_BREAK_PROB;
formula p_lnok = LIFT_BREAK_PROB;
formula p_ab   = 1.0 - NO_ACCESSIBLE_BUS_PROB;
formula p_nb   = NO_ACCESSIBLE_BUS_PROB;


// -------------------------------------------------------
// Module m_manager
// Owns: policy, weather, lift_ok, acc_bus
// Reads: phase (global)
// Acts at phase=0; sets phase=1 on every transition
// -------------------------------------------------------
module m_manager

    policy  : [0..4] init 0;
    weather : [0..2] init 0;
    lift_ok : bool   init true;
    acc_bus : bool   init true;

    // set_normal (policy=0): no intervention; all disruption probabilities at baseline
    [set_normal] phase=0 ->
        p_w0*p_lok*p_ab  : (policy'=0)&(weather'=0)&(lift_ok'=true) &(acc_bus'=true) &(phase'=1)
      + p_w0*p_lok*p_nb  : (policy'=0)&(weather'=0)&(lift_ok'=true) &(acc_bus'=false)&(phase'=1)
      + p_w0*p_lnok*p_ab : (policy'=0)&(weather'=0)&(lift_ok'=false)&(acc_bus'=true) &(phase'=1)
      + p_w0*p_lnok*p_nb : (policy'=0)&(weather'=0)&(lift_ok'=false)&(acc_bus'=false)&(phase'=1)
      + p_w1*p_lok*p_ab  : (policy'=0)&(weather'=1)&(lift_ok'=true) &(acc_bus'=true) &(phase'=1)
      + p_w1*p_lok*p_nb  : (policy'=0)&(weather'=1)&(lift_ok'=true) &(acc_bus'=false)&(phase'=1)
      + p_w1*p_lnok*p_ab : (policy'=0)&(weather'=1)&(lift_ok'=false)&(acc_bus'=true) &(phase'=1)
      + p_w1*p_lnok*p_nb : (policy'=0)&(weather'=1)&(lift_ok'=false)&(acc_bus'=false)&(phase'=1)
      + p_w2*p_lok*p_ab  : (policy'=0)&(weather'=2)&(lift_ok'=true) &(acc_bus'=true) &(phase'=1)
      + p_w2*p_lok*p_nb  : (policy'=0)&(weather'=2)&(lift_ok'=true) &(acc_bus'=false)&(phase'=1)
      + p_w2*p_lnok*p_ab : (policy'=0)&(weather'=2)&(lift_ok'=false)&(acc_bus'=true) &(phase'=1)
      + p_w2*p_lnok*p_nb : (policy'=0)&(weather'=2)&(lift_ok'=false)&(acc_bus'=false)&(phase'=1);

    // set_high_freq (policy=1): increases service frequency; halves delay and cancel probabilities
    [set_high_freq] phase=0 ->
        p_w0*p_lok*p_ab  : (policy'=1)&(weather'=0)&(lift_ok'=true) &(acc_bus'=true) &(phase'=1)
      + p_w0*p_lok*p_nb  : (policy'=1)&(weather'=0)&(lift_ok'=true) &(acc_bus'=false)&(phase'=1)
      + p_w0*p_lnok*p_ab : (policy'=1)&(weather'=0)&(lift_ok'=false)&(acc_bus'=true) &(phase'=1)
      + p_w0*p_lnok*p_nb : (policy'=1)&(weather'=0)&(lift_ok'=false)&(acc_bus'=false)&(phase'=1)
      + p_w1*p_lok*p_ab  : (policy'=1)&(weather'=1)&(lift_ok'=true) &(acc_bus'=true) &(phase'=1)
      + p_w1*p_lok*p_nb  : (policy'=1)&(weather'=1)&(lift_ok'=true) &(acc_bus'=false)&(phase'=1)
      + p_w1*p_lnok*p_ab : (policy'=1)&(weather'=1)&(lift_ok'=false)&(acc_bus'=true) &(phase'=1)
      + p_w1*p_lnok*p_nb : (policy'=1)&(weather'=1)&(lift_ok'=false)&(acc_bus'=false)&(phase'=1)
      + p_w2*p_lok*p_ab  : (policy'=1)&(weather'=2)&(lift_ok'=true) &(acc_bus'=true) &(phase'=1)
      + p_w2*p_lok*p_nb  : (policy'=1)&(weather'=2)&(lift_ok'=true) &(acc_bus'=false)&(phase'=1)
      + p_w2*p_lnok*p_ab : (policy'=1)&(weather'=2)&(lift_ok'=false)&(acc_bus'=true) &(phase'=1)
      + p_w2*p_lnok*p_nb : (policy'=1)&(weather'=2)&(lift_ok'=false)&(acc_bus'=false)&(phase'=1);

    // set_low_fare (policy=2): subsidizes bus (100p) and rail (200p) fares
    [set_low_fare] phase=0 ->
        p_w0*p_lok*p_ab  : (policy'=2)&(weather'=0)&(lift_ok'=true) &(acc_bus'=true) &(phase'=1)
      + p_w0*p_lok*p_nb  : (policy'=2)&(weather'=0)&(lift_ok'=true) &(acc_bus'=false)&(phase'=1)
      + p_w0*p_lnok*p_ab : (policy'=2)&(weather'=0)&(lift_ok'=false)&(acc_bus'=true) &(phase'=1)
      + p_w0*p_lnok*p_nb : (policy'=2)&(weather'=0)&(lift_ok'=false)&(acc_bus'=false)&(phase'=1)
      + p_w1*p_lok*p_ab  : (policy'=2)&(weather'=1)&(lift_ok'=true) &(acc_bus'=true) &(phase'=1)
      + p_w1*p_lok*p_nb  : (policy'=2)&(weather'=1)&(lift_ok'=true) &(acc_bus'=false)&(phase'=1)
      + p_w1*p_lnok*p_ab : (policy'=2)&(weather'=1)&(lift_ok'=false)&(acc_bus'=true) &(phase'=1)
      + p_w1*p_lnok*p_nb : (policy'=2)&(weather'=1)&(lift_ok'=false)&(acc_bus'=false)&(phase'=1)
      + p_w2*p_lok*p_ab  : (policy'=2)&(weather'=2)&(lift_ok'=true) &(acc_bus'=true) &(phase'=1)
      + p_w2*p_lok*p_nb  : (policy'=2)&(weather'=2)&(lift_ok'=true) &(acc_bus'=false)&(phase'=1)
      + p_w2*p_lnok*p_ab : (policy'=2)&(weather'=2)&(lift_ok'=false)&(acc_bus'=true) &(phase'=1)
      + p_w2*p_lnok*p_nb : (policy'=2)&(weather'=2)&(lift_ok'=false)&(acc_bus'=false)&(phase'=1);

    // set_road_charge (policy=3): adds 500p surcharge to all taxi fares (discourages private hire)
    [set_road_charge] phase=0 ->
        p_w0*p_lok*p_ab  : (policy'=3)&(weather'=0)&(lift_ok'=true) &(acc_bus'=true) &(phase'=1)
      + p_w0*p_lok*p_nb  : (policy'=3)&(weather'=0)&(lift_ok'=true) &(acc_bus'=false)&(phase'=1)
      + p_w0*p_lnok*p_ab : (policy'=3)&(weather'=0)&(lift_ok'=false)&(acc_bus'=true) &(phase'=1)
      + p_w0*p_lnok*p_nb : (policy'=3)&(weather'=0)&(lift_ok'=false)&(acc_bus'=false)&(phase'=1)
      + p_w1*p_lok*p_ab  : (policy'=3)&(weather'=1)&(lift_ok'=true) &(acc_bus'=true) &(phase'=1)
      + p_w1*p_lok*p_nb  : (policy'=3)&(weather'=1)&(lift_ok'=true) &(acc_bus'=false)&(phase'=1)
      + p_w1*p_lnok*p_ab : (policy'=3)&(weather'=1)&(lift_ok'=false)&(acc_bus'=true) &(phase'=1)
      + p_w1*p_lnok*p_nb : (policy'=3)&(weather'=1)&(lift_ok'=false)&(acc_bus'=false)&(phase'=1)
      + p_w2*p_lok*p_ab  : (policy'=3)&(weather'=2)&(lift_ok'=true) &(acc_bus'=true) &(phase'=1)
      + p_w2*p_lok*p_nb  : (policy'=3)&(weather'=2)&(lift_ok'=true) &(acc_bus'=false)&(phase'=1)
      + p_w2*p_lnok*p_ab : (policy'=3)&(weather'=2)&(lift_ok'=false)&(acc_bus'=true) &(phase'=1)
      + p_w2*p_lnok*p_nb : (policy'=3)&(weather'=2)&(lift_ok'=false)&(acc_bus'=false)&(phase'=1);

    // set_accessible_service (policy=4): guarantees lift_ok=true and acc_bus=true;
    // only weather is sampled (3 branches instead of 12)
    [set_accessible_service] phase=0 ->
        p_w0 : (policy'=4)&(weather'=0)&(lift_ok'=true)&(acc_bus'=true)&(phase'=1)
      + p_w1 : (policy'=4)&(weather'=1)&(lift_ok'=true)&(acc_bus'=true)&(phase'=1)
      + p_w2 : (policy'=4)&(weather'=2)&(lift_ok'=true)&(acc_bus'=true)&(phase'=1);

endmodule


// -------------------------------------------------------
// Module m_persona
// Owns: loc, mode, done, abandon, service_status, disruptions_used, fare_spent
// Reads: phase (global), policy/weather/lift_ok/acc_bus (from m_manager state)
// Acts at phase=1; loops until done=true
//
// service_status: 0=normal  1=delayed (resolved by wait_at_stop)  2=cancelled
// disruptions_used: counts disruptions consumed against DISRUPTION_BUDGET
// fare_spent: tracks cumulative fare actually paid (updated on successful boarding only)
// -------------------------------------------------------
module m_persona

    loc              : [0..3]              init 0;
    mode             : [0..6]              init 0;
    done             : bool                init false;
    abandon          : bool                init false;
    service_status   : [0..2]              init 0;
    disruptions_used : [0..DISRUPTION_BUDGET] init 0;
    fare_spent       : [0..6000]           init 0;

    // -------------------------------------------------------
    // Terminal: journey complete (loc=3) or abandoned (give_up)
    // Self-loop keeps the state absorbing for PRISM F-type properties
    // -------------------------------------------------------
    [done_loop] phase=1 & done -> true;

    // -------------------------------------------------------
    // Give up: only available when no other action is enabled at the current location
    // (stuck_home / stuck_stop / stuck_interchange formulas encode this condition)
    // -------------------------------------------------------
    [give_up] phase=1 & !done
              & ((loc=0 & stuck_home) | (loc=1 & stuck_stop) | (loc=2 & stuck_interchange))
              -> (done'=true) & (abandon'=true);


    // -------------------------------------------------------
    // At home (loc=0)
    // -------------------------------------------------------

    // Car (direct)
    [choose_car] phase=1 & loc=0 & !done & CAR_AVAILABLE
        -> (loc'=3) & (mode'=1) & (done'=true);

    // Taxi direct
    [taxi_direct] phase=1 & loc=0 & !done & fare_spent+taxi_direct_fare<=FARE_MAX
        -> (loc'=3) & (mode'=4) & (fare_spent'=fare_spent+taxi_direct_fare) & (done'=true);

    // Bike direct (clear weather only)
    [bike_direct] phase=1 & loc=0 & !done & HAS_BIKE & BIKE_TOLERANCE>=DIST_HOME_TO_DEST & weather=0
        -> (loc'=3) & (mode'=6) & (done'=true);

    // Walk to destination
    [walk_to_destination] phase=1 & loc=0 & !done & WALK_TOLERANCE>=DIST_HOME_TO_DEST
        -> (loc'=3) & (mode'=2) & (done'=true);

    // Walk to stop
    [walk_to_stop] phase=1 & loc=0 & !done & WALK_TOLERANCE>=DIST_HOME_TO_STOP
        -> (loc'=1) & (mode'=2);


    // -------------------------------------------------------
    // At stop (loc=1)
    // board_bus/board_rail: two variants per service to handle disruption budget cleanly
    //   Variant A (disruptions_used < DISRUPTION_BUDGET): probabilistic outcome
    //   Variant B (disruptions_used >= DISRUPTION_BUDGET): service always runs
    // Guards on the two variants are mutually exclusive -- no nondeterminism between them
    // -------------------------------------------------------

    // Board bus -- variant A (disruption budget remaining)
    [board_bus] phase=1 & loc=1 & !done & service_status=0
                & HAS_BUS_STOP
                & disruptions_used<DISRUPTION_BUDGET
                & (!NEEDS_STEP_FREE | acc_bus)
                & (HAS_BUS_PASS | fare_spent+bus_fare<=FARE_MAX)
        -> eff_ok     : (loc'=2) & (mode'=3) & (fare_spent'=fare_spent+bus_fare)
         + eff_delay  : (service_status'=1) & (disruptions_used'=disruptions_used+1)
         + eff_cancel : (service_status'=2) & (disruptions_used'=disruptions_used+1);

    // Board bus -- variant B (budget exhausted; service guaranteed to run)
    [board_bus] phase=1 & loc=1 & !done & service_status=0
                & HAS_BUS_STOP
                & disruptions_used>=DISRUPTION_BUDGET
                & (!NEEDS_STEP_FREE | acc_bus)
                & (HAS_BUS_PASS | fare_spent+bus_fare<=FARE_MAX)
        -> (loc'=2) & (mode'=3) & (fare_spent'=fare_spent+bus_fare);

    // Board rail -- variant A
    [board_rail] phase=1 & loc=1 & !done & service_status=0
                 & HAS_RAIL_STOP
                 & disruptions_used<DISRUPTION_BUDGET
                 & (!NEEDS_STEP_FREE | lift_ok)
                 & fare_spent+rail_fare<=FARE_MAX
        -> eff_ok     : (loc'=2) & (mode'=5) & (fare_spent'=fare_spent+rail_fare)
         + eff_delay  : (service_status'=1) & (disruptions_used'=disruptions_used+1)
         + eff_cancel : (service_status'=2) & (disruptions_used'=disruptions_used+1);

    // Board rail -- variant B
    [board_rail] phase=1 & loc=1 & !done & service_status=0
                 & HAS_RAIL_STOP
                 & disruptions_used>=DISRUPTION_BUDGET
                 & (!NEEDS_STEP_FREE | lift_ok)
                 & fare_spent+rail_fare<=FARE_MAX
        -> (loc'=2) & (mode'=5) & (fare_spent'=fare_spent+rail_fare);

    // Wait at stop: resolves a delay (service_status=1 -> 0) before retrying
    [wait_at_stop] phase=1 & loc=1 & !done & service_status=1
        -> (service_status'=0);

    // Taxi from stop
    [taxi_from_stop] phase=1 & loc=1 & !done & fare_spent+taxi_stop_fare<=FARE_MAX
        -> (loc'=3) & (mode'=4) & (fare_spent'=fare_spent+taxi_stop_fare) & (done'=true);

    // Walk back home from stop: only when service is cancelled; prevents infinite cycling
    [walk_back_home] phase=1 & loc=1 & !done & service_status=2 & WALK_TOLERANCE>=DIST_HOME_TO_STOP
        -> (loc'=0) & (mode'=2) & (service_status'=0);


    // -------------------------------------------------------
    // At interchange (loc=2)
    // -------------------------------------------------------

    // Final leg bus -- variant A
    [final_leg_bus] phase=1 & loc=2 & !done & service_status=0
                    & HAS_BUS_FINAL
                    & disruptions_used<DISRUPTION_BUDGET
                    & (!NEEDS_STEP_FREE | acc_bus)
                    & (HAS_BUS_PASS | fare_spent+bus_fare<=FARE_MAX)
        -> eff_ok     : (loc'=3) & (mode'=3) & (fare_spent'=fare_spent+bus_fare) & (done'=true)
         + eff_delay  : (service_status'=1) & (disruptions_used'=disruptions_used+1)
         + eff_cancel : (service_status'=2) & (disruptions_used'=disruptions_used+1);

    // Final leg bus -- variant B
    [final_leg_bus] phase=1 & loc=2 & !done & service_status=0
                    & HAS_BUS_FINAL
                    & disruptions_used>=DISRUPTION_BUDGET
                    & (!NEEDS_STEP_FREE | acc_bus)
                    & (HAS_BUS_PASS | fare_spent+bus_fare<=FARE_MAX)
        -> (loc'=3) & (mode'=3) & (fare_spent'=fare_spent+bus_fare) & (done'=true);

    // Final leg rail -- variant A
    [final_leg_rail] phase=1 & loc=2 & !done & service_status=0
                     & HAS_RAIL_FINAL
                     & disruptions_used<DISRUPTION_BUDGET
                     & (!NEEDS_STEP_FREE | lift_ok)
                     & fare_spent+rail_fare<=FARE_MAX
        -> eff_ok     : (loc'=3) & (mode'=5) & (fare_spent'=fare_spent+rail_fare) & (done'=true)
         + eff_delay  : (service_status'=1) & (disruptions_used'=disruptions_used+1)
         + eff_cancel : (service_status'=2) & (disruptions_used'=disruptions_used+1);

    // Final leg rail -- variant B
    [final_leg_rail] phase=1 & loc=2 & !done & service_status=0
                     & HAS_RAIL_FINAL
                     & disruptions_used>=DISRUPTION_BUDGET
                     & (!NEEDS_STEP_FREE | lift_ok)
                     & fare_spent+rail_fare<=FARE_MAX
        -> (loc'=3) & (mode'=5) & (fare_spent'=fare_spent+rail_fare) & (done'=true);

    // Wait at interchange: resolves delay
    [wait_at_stop] phase=1 & loc=2 & !done & service_status=1
        -> (service_status'=0);

    // Final leg walk
    [final_leg_walk] phase=1 & loc=2 & !done & WALK_TOLERANCE>=DIST_INTERCHANGE_TO_DEST
        -> (loc'=3) & (mode'=2) & (done'=true);

    // Final leg taxi
    [final_leg_taxi] phase=1 & loc=2 & !done & fare_spent+taxi_final_fare<=FARE_MAX
        -> (loc'=3) & (mode'=4) & (fare_spent'=fare_spent+taxi_final_fare) & (done'=true);

    // Taxi back home from interchange: used when service is cancelled at loc=2
    // Persona returns to loc=0 to reconsider; service_status reset on arrival
    [taxi_back_home] phase=1 & loc=2 & !done & service_status=2
                     & fare_spent+taxi_home_fare<=FARE_MAX
        -> (loc'=0) & (mode'=4) & (fare_spent'=fare_spent+taxi_home_fare) & (service_status'=0);

endmodule


// -------------------------------------------------------
// Rewards: travel time (minutes)
// All values are parametric constants supplied via params/scenarios/*.json
// -------------------------------------------------------
rewards "time"
    [choose_car]          weather=0 :  TIME_CAR_CLEAR;
    [choose_car]          weather=1 :  TIME_CAR_RAIN;
    [choose_car]          weather=2 :  TIME_CAR_SEVERE;
    [taxi_direct]         weather=0 :  TIME_TAXI_DIRECT_CLEAR;
    [taxi_direct]         weather=1 :  TIME_TAXI_DIRECT_RAIN;
    [taxi_direct]         weather=2 :  TIME_TAXI_DIRECT_SEVERE;
    [taxi_from_stop]      weather=0 :  TIME_TAXI_STOP_CLEAR;
    [taxi_from_stop]      weather=1 :  TIME_TAXI_STOP_RAIN;
    [taxi_from_stop]      weather=2 :  TIME_TAXI_STOP_SEVERE;
    [final_leg_taxi]      weather=0 :  TIME_TAXI_FINAL_CLEAR;
    [final_leg_taxi]      weather=1 :  TIME_TAXI_FINAL_RAIN;
    [final_leg_taxi]      weather=2 :  TIME_TAXI_FINAL_SEVERE;
    [taxi_back_home]      weather=0 :  TIME_TAXI_HOME_CLEAR;
    [taxi_back_home]      weather=1 :  TIME_TAXI_HOME_RAIN;
    [taxi_back_home]      weather=2 :  TIME_TAXI_HOME_SEVERE;
    [bike_direct]         true      :  TIME_BIKE_DIRECT;
    [walk_to_destination] true      :  TIME_WALK_TO_DEST;
    [walk_to_stop]        true      :  TIME_WALK_TO_STOP;
    [walk_back_home]      true      :  TIME_WALK_TO_STOP;
    [board_bus]           true      :  TIME_BUS_STOP_TO_INT;
    [board_rail]          true      :  TIME_RAIL_STOP_TO_INT;
    [final_leg_bus]       true      :  TIME_FINAL_BUS;
    [final_leg_rail]      true      :  TIME_FINAL_RAIL;
    [final_leg_walk]      true      :  TIME_FINAL_WALK;
    [wait_at_stop]        true      :  avg_wait_time;
    [give_up]             true      :  FAIL_PENALTY;
endrewards

// -------------------------------------------------------
// Rewards: carbon emissions (grams CO2e)
// Based on UK DfT 2025 per-pkm factors (scope 3 inclusive):
//   taxi 148.6 g/pkm | bus 125.25 g/pkm | rail 35.46 g/pkm | car ~168 g/vkm | active 0 g/pkm
// Per-leg CO2e constants computed from distances x factors in preprocessing.py
// -------------------------------------------------------
rewards "co2e"
    [choose_car]          true :  CO2E_CAR_DIRECT;
    [taxi_direct]         true :  CO2E_TAXI_DIRECT;
    [taxi_from_stop]      true :  CO2E_TAXI_STOP;
    [final_leg_taxi]      true :  CO2E_TAXI_FINAL;
    [taxi_back_home]      true :  CO2E_TAXI_HOME;
    [board_bus]           true :  CO2E_BUS_STOP_TO_INT;
    [board_rail]          true :  CO2E_RAIL_STOP_TO_INT;
    [final_leg_bus]       true :  CO2E_BUS_FINAL;
    [final_leg_rail]      true :  CO2E_RAIL_FINAL;
    [bike_direct]         true :     0;
    [walk_to_destination] true :     0;
    [walk_to_stop]        true :     0;
    [walk_back_home]      true :     0;
    [final_leg_walk]      true :     0;
endrewards

// -------------------------------------------------------
// Rewards: fare cost (pence)
//
// Policy effects:
//   policy=2 (low_fare):   bus_fare=100p, rail_fare=200p
//   policy=3 (road_charge): taxi fares +500p
//   HAS_BUS_PASS:           bus_fare=0p regardless of policy
//
// Note: charged on every boarding attempt (including failed delay/cancel outcomes).
//   fare_spent state variable tracks only successful boarding payments.
// -------------------------------------------------------
rewards "fare"
    [board_bus]      true : bus_fare;
    [board_rail]     true : rail_fare;
    [taxi_direct]    true : taxi_direct_fare;
    [taxi_from_stop] true : taxi_stop_fare;
    [final_leg_bus]  true : bus_fare;
    [final_leg_rail] true : rail_fare;
    [final_leg_taxi] true : taxi_final_fare;
    [taxi_back_home] true : taxi_home_fare;
endrewards

// -------------------------------------------------------
// Rewards: walking distance (metres)
// -------------------------------------------------------
rewards "walking_distance"
    [walk_to_stop]        true :  DIST_HOME_TO_STOP;
    [walk_back_home]      true :  DIST_HOME_TO_STOP;
    [final_leg_walk]      true :  DIST_INTERCHANGE_TO_DEST;
    [walk_to_destination] true :  DIST_HOME_TO_DEST;
endrewards
