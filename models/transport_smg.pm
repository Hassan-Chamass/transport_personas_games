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
//   - Manager acts exactly once at phase=0 (6-branch sampling of weather x acc_bus)
//   - set_accessible_service guarantees acc_bus=true and halves LIFT_BREAK_PROB (3 branches: weather only)
//   - Lift failure is an in-journey disruption embedded in attempt_rail/attempt_final_rail probabilities
//   - In-journey disruptions are probabilistic outcomes within persona's boarding actions
//   - disruptions_used tracks budget; once exhausted, all service runs without disruption
//   - done=true is absorbing (success at loc=3 or abandon via give_up)
//   - give_up carries no time penalty: R{"time"} measures actual travel time only.
//     Divide by P(F loc=3) in post-processing to get E[time | success].
//     Abandonment is quantified separately via P [F (done & abandon)].
//
// Boarding is split into attempt_* / ride_* actions: attempt resolves the service
//   outcome, ride (forced when pending>0) performs the leg and carries the rewards,
//   so time/co2e/fare are only charged on legs actually travelled.
//
// "generalized_cost" reward (equivalent pence) combines time, fare and walking
//   with per-persona weights W_TIME / W_FARE / W_WALK -- the persona's true
//   objective for best-response (Stackelberg) analyses.
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
    [attempt_bus], [ride_bus], [attempt_rail], [ride_rail], [wait_at_stop], [taxi_from_stop],
    [attempt_final_bus], [ride_final_bus], [attempt_final_rail], [ride_final_rail],
    [final_leg_walk], [final_leg_taxi]
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

// Generalized-cost weights (per persona; placeholder values pending DfT TAG sourcing)
const double W_TIME;   // pence per minute (value of time)
const double W_FARE;   // multiplier on pence actually paid
const double W_WALK;   // pence per metre walked

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

// -------------------------------------------------------
// Constants -- Run config (supplied via params/run_config.json)
// Set a policy flag to false to disable that policy for the manager.
// At least one ALLOW_* must be true or the model deadlocks at phase=0.
// PT_ONLY=true disables car and taxi for all personas (PT-only experiment).
// -------------------------------------------------------
const bool ALLOW_NORMAL;
const bool ALLOW_HIGH_FREQ;
const bool ALLOW_LOW_FARE;
const bool ALLOW_ROAD_CHARGE;
const bool ALLOW_ACCESSIBLE_SERVICE;
const bool PT_ONLY;

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
const int CO2E_BUS_STOP_TO_INT;
const int CO2E_RAIL_STOP_TO_INT;
const int CO2E_BUS_FINAL;
const int CO2E_RAIL_FINAL;

// Time constants (minutes)
const int TIME_CAR_CLEAR;         const int TIME_CAR_RAIN;         const int TIME_CAR_SEVERE;
const int TIME_TAXI_DIRECT_CLEAR; const int TIME_TAXI_DIRECT_RAIN; const int TIME_TAXI_DIRECT_SEVERE;
const int TIME_TAXI_STOP_CLEAR;   const int TIME_TAXI_STOP_RAIN;   const int TIME_TAXI_STOP_SEVERE;
const int TIME_TAXI_FINAL_CLEAR;  const int TIME_TAXI_FINAL_RAIN;  const int TIME_TAXI_FINAL_SEVERE;
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
const int CAR_COST;
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
formula car_cost         = policy=3 ? CAR_COST+ROAD_CHARGE_SURCHARGE : CAR_COST;
formula taxi_direct_fare = policy=3 ? TAXI_DIRECT_FARE_BASE+ROAD_CHARGE_SURCHARGE : TAXI_DIRECT_FARE_BASE;
formula taxi_stop_fare   = policy=3 ? TAXI_STOP_FARE_BASE+ROAD_CHARGE_SURCHARGE   : TAXI_STOP_FARE_BASE;
formula taxi_final_fare  = policy=3 ? TAXI_FINAL_FARE_BASE+ROAD_CHARGE_SURCHARGE  : TAXI_FINAL_FARE_BASE;

// Effective disruption probabilities -- halved under high_freq policy
formula eff_cancel = policy=1 ? CANCEL_PROB * 0.5 : CANCEL_PROB;
formula eff_delay  = policy=1 ? (MINOR_DELAY_PROB + MODERATE_DELAY_PROB + SEVERE_DELAY_PROB) * 0.5
                               : (MINOR_DELAY_PROB + MODERATE_DELAY_PROB + SEVERE_DELAY_PROB);
formula eff_ok     = 1.0 - eff_cancel - eff_delay;

// Lift failure probability -- in-journey disruption for rail, affects NEEDS_STEP_FREE personas only
formula eff_lift_fail = NEEDS_STEP_FREE ? (policy=4 ? LIFT_BREAK_PROB*0.5 : LIFT_BREAK_PROB) : 0.0;

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
    (!CAR_AVAILABLE | PT_ONLY)
    & (fare_spent+taxi_direct_fare>FARE_MAX | PT_ONLY)
    & (!HAS_BIKE | weather!=0 | BIKE_TOLERANCE<DIST_HOME_TO_DEST)
    & WALK_TOLERANCE<DIST_HOME_TO_DEST
    & WALK_TOLERANCE<DIST_HOME_TO_STOP;

formula stuck_stop =
    service_status!=1
    & !(service_status=0 & HAS_BUS_STOP & (!NEEDS_STEP_FREE|acc_bus) & (HAS_BUS_PASS|fare_spent+bus_fare<=FARE_MAX))
    & !(service_status=0 & HAS_RAIL_STOP & fare_spent+rail_fare<=FARE_MAX)
    & (fare_spent+taxi_stop_fare>FARE_MAX | PT_ONLY);

formula stuck_interchange =
    service_status!=1
    & !(service_status=0 & HAS_BUS_FINAL  & (!NEEDS_STEP_FREE|acc_bus) & (HAS_BUS_PASS|fare_spent+bus_fare<=FARE_MAX))
    & !(service_status=0 & HAS_RAIL_FINAL & fare_spent+rail_fare<=FARE_MAX)
    & WALK_TOLERANCE<DIST_INTERCHANGE_TO_DEST
    & (fare_spent+taxi_final_fare>FARE_MAX | PT_ONLY);

// Manager sampling branch probabilities (weather x acc_bus are independent)
formula p_w0 = 1.0 - RAIN_PROB - SEVERE_WEATHER_PROB;
formula p_w1 = RAIN_PROB;
formula p_w2 = SEVERE_WEATHER_PROB;
formula p_ab = 1.0 - NO_ACCESSIBLE_BUS_PROB;
formula p_nb = NO_ACCESSIBLE_BUS_PROB;


// -------------------------------------------------------
// Module m_manager
// Owns: policy, weather, acc_bus
// Reads: phase (global)
// Acts at phase=0; sets phase=1 on every transition
// lift_ok removed: lift failure is now an in-journey disruption (see eff_lift_fail)
// -------------------------------------------------------
module m_manager

    policy  : [0..4] init 0;
    weather : [0..2] init 0;
    acc_bus : bool   init true;

    // set_normal (policy=0): no intervention; all disruption probabilities at baseline
    [set_normal] phase=0 & ALLOW_NORMAL ->
        p_w0*p_ab : (policy'=0)&(weather'=0)&(acc_bus'=true) &(phase'=1)
      + p_w0*p_nb : (policy'=0)&(weather'=0)&(acc_bus'=false)&(phase'=1)
      + p_w1*p_ab : (policy'=0)&(weather'=1)&(acc_bus'=true) &(phase'=1)
      + p_w1*p_nb : (policy'=0)&(weather'=1)&(acc_bus'=false)&(phase'=1)
      + p_w2*p_ab : (policy'=0)&(weather'=2)&(acc_bus'=true) &(phase'=1)
      + p_w2*p_nb : (policy'=0)&(weather'=2)&(acc_bus'=false)&(phase'=1);

    // set_high_freq (policy=1): increases service frequency; halves delay and cancel probabilities
    [set_high_freq] phase=0 & ALLOW_HIGH_FREQ ->
        p_w0*p_ab : (policy'=1)&(weather'=0)&(acc_bus'=true) &(phase'=1)
      + p_w0*p_nb : (policy'=1)&(weather'=0)&(acc_bus'=false)&(phase'=1)
      + p_w1*p_ab : (policy'=1)&(weather'=1)&(acc_bus'=true) &(phase'=1)
      + p_w1*p_nb : (policy'=1)&(weather'=1)&(acc_bus'=false)&(phase'=1)
      + p_w2*p_ab : (policy'=1)&(weather'=2)&(acc_bus'=true) &(phase'=1)
      + p_w2*p_nb : (policy'=1)&(weather'=2)&(acc_bus'=false)&(phase'=1);

    // set_low_fare (policy=2): subsidizes bus and rail fares
    [set_low_fare] phase=0 & ALLOW_LOW_FARE ->
        p_w0*p_ab : (policy'=2)&(weather'=0)&(acc_bus'=true) &(phase'=1)
      + p_w0*p_nb : (policy'=2)&(weather'=0)&(acc_bus'=false)&(phase'=1)
      + p_w1*p_ab : (policy'=2)&(weather'=1)&(acc_bus'=true) &(phase'=1)
      + p_w1*p_nb : (policy'=2)&(weather'=1)&(acc_bus'=false)&(phase'=1)
      + p_w2*p_ab : (policy'=2)&(weather'=2)&(acc_bus'=true) &(phase'=1)
      + p_w2*p_nb : (policy'=2)&(weather'=2)&(acc_bus'=false)&(phase'=1);

    // set_road_charge (policy=3): adds surcharge to car and taxi journeys (discourages private motor traffic)
    [set_road_charge] phase=0 & ALLOW_ROAD_CHARGE ->
        p_w0*p_ab : (policy'=3)&(weather'=0)&(acc_bus'=true) &(phase'=1)
      + p_w0*p_nb : (policy'=3)&(weather'=0)&(acc_bus'=false)&(phase'=1)
      + p_w1*p_ab : (policy'=3)&(weather'=1)&(acc_bus'=true) &(phase'=1)
      + p_w1*p_nb : (policy'=3)&(weather'=1)&(acc_bus'=false)&(phase'=1)
      + p_w2*p_ab : (policy'=3)&(weather'=2)&(acc_bus'=true) &(phase'=1)
      + p_w2*p_nb : (policy'=3)&(weather'=2)&(acc_bus'=false)&(phase'=1);

    // set_accessible_service (policy=4): guarantees acc_bus=true and halves LIFT_BREAK_PROB;
    // only weather is sampled (3 branches)
    [set_accessible_service] phase=0 & ALLOW_ACCESSIBLE_SERVICE ->
        p_w0 : (policy'=4)&(weather'=0)&(acc_bus'=true)&(phase'=1)
      + p_w1 : (policy'=4)&(weather'=1)&(acc_bus'=true)&(phase'=1)
      + p_w2 : (policy'=4)&(weather'=2)&(acc_bus'=true)&(phase'=1);

endmodule


// -------------------------------------------------------
// Module m_persona
// Owns: loc, mode, done, abandon, service_status, disruptions_used, fare_spent, pending
// Reads: phase (global), policy/weather/acc_bus (from m_manager state)
// Acts at phase=1; loops until done=true
//
// service_status: 0=normal  1=delayed (resolved by wait_at_stop)  2=cancelled
// disruptions_used: counts disruptions consumed against DISRUPTION_BUDGET
// fare_spent: tracks cumulative fare actually paid (updated on successful boarding only)
// pending: service arrived, ride pending (1=bus, 2=rail)
// -------------------------------------------------------
module m_persona

    loc              : [0..3]              init 0;
    mode             : [0..6]              init 0;
    done             : bool                init false;
    abandon          : bool                init false;
    service_status   : [0..2]              init 0;
    disruptions_used : [0..DISRUPTION_BUDGET] init 0;
    fare_spent       : [0..6000]           init 0;
    pending          : [0..2]              init 0;

    // -------------------------------------------------------
    // Terminal: journey complete (loc=3) or abandoned (give_up)
    // Self-loop keeps the state absorbing for PRISM F-type properties
    // -------------------------------------------------------
    [done_loop] phase=1 & done -> true;

    // -------------------------------------------------------
    // Give up: only available when no other action is enabled at the current location
    // (stuck_home / stuck_stop / stuck_interchange formulas encode this condition)
    // -------------------------------------------------------
    [give_up] phase=1 & !done & pending=0
              & ((loc=0 & stuck_home) | (loc=1 & stuck_stop) | (loc=2 & stuck_interchange))
              -> (done'=true) & (abandon'=true);


    // -------------------------------------------------------
    // At home (loc=0)
    // -------------------------------------------------------

    // Car (direct)
    [choose_car] phase=1 & loc=0 & !done & CAR_AVAILABLE & !PT_ONLY
        -> (loc'=3) & (mode'=1) & (done'=true);

    // Taxi direct
    [taxi_direct] phase=1 & loc=0 & !done & !PT_ONLY & fare_spent+taxi_direct_fare<=FARE_MAX
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
    // attempt_* resolves the service outcome; ride_* (only action when pending>0)
    //   performs the leg and carries the rewards.
    // Two attempt variants per service handle the disruption budget:
    //   Variant A (disruptions_used < DISRUPTION_BUDGET): probabilistic outcome
    //   Variant B (disruptions_used >= DISRUPTION_BUDGET): service always runs
    // Guards on the two variants are mutually exclusive -- no nondeterminism between them
    // -------------------------------------------------------

    // Attempt bus -- variant A (disruption budget remaining)
    [attempt_bus] phase=1 & loc=1 & !done & pending=0 & service_status=0
                & HAS_BUS_STOP
                & disruptions_used<DISRUPTION_BUDGET
                & (!NEEDS_STEP_FREE | acc_bus)
                & (HAS_BUS_PASS | fare_spent+bus_fare<=FARE_MAX)
        -> eff_ok     : (pending'=1)
         + eff_delay  : (service_status'=1) & (disruptions_used'=disruptions_used+1)
         + eff_cancel : (service_status'=2) & (disruptions_used'=disruptions_used+1);

    // Attempt bus -- variant B (budget exhausted; service guaranteed to run)
    [attempt_bus] phase=1 & loc=1 & !done & pending=0 & service_status=0
                & HAS_BUS_STOP
                & disruptions_used>=DISRUPTION_BUDGET
                & (!NEEDS_STEP_FREE | acc_bus)
                & (HAS_BUS_PASS | fare_spent+bus_fare<=FARE_MAX)
        -> (pending'=1);

    [ride_bus] phase=1 & loc=1 & pending=1
        -> (loc'=2) & (mode'=3) & (fare_spent'=fare_spent+bus_fare) & (pending'=0);

    // Attempt rail -- variant A
    // Lift failure folded into the cancel outcome, conditioned on the service running
    [attempt_rail] phase=1 & loc=1 & !done & pending=0 & service_status=0
                 & HAS_RAIL_STOP
                 & disruptions_used<DISRUPTION_BUDGET
                 & fare_spent+rail_fare<=FARE_MAX
        -> eff_ok*(1-eff_lift_fail)             : (pending'=2)
         + eff_delay                            : (service_status'=1) & (disruptions_used'=disruptions_used+1)
         + eff_cancel+eff_ok*eff_lift_fail      : (service_status'=2) & (disruptions_used'=disruptions_used+1);

    // Attempt rail -- variant B (budget exhausted; lift failure also suppressed)
    [attempt_rail] phase=1 & loc=1 & !done & pending=0 & service_status=0
                 & HAS_RAIL_STOP
                 & disruptions_used>=DISRUPTION_BUDGET
                 & fare_spent+rail_fare<=FARE_MAX
        -> (pending'=2);

    [ride_rail] phase=1 & loc=1 & pending=2
        -> (loc'=2) & (mode'=5) & (fare_spent'=fare_spent+rail_fare) & (pending'=0);

    // Wait at stop: resolves a delay (service_status=1 -> 0) before retrying
    [wait_at_stop] phase=1 & loc=1 & !done & pending=0 & service_status=1
        -> (service_status'=0);

    // Taxi from stop
    [taxi_from_stop] phase=1 & loc=1 & !done & pending=0 & !PT_ONLY & fare_spent+taxi_stop_fare<=FARE_MAX
        -> (loc'=3) & (mode'=4) & (fare_spent'=fare_spent+taxi_stop_fare) & (done'=true);


    // -------------------------------------------------------
    // At interchange (loc=2)
    // -------------------------------------------------------

    // Attempt final leg bus -- variant A
    [attempt_final_bus] phase=1 & loc=2 & !done & pending=0 & service_status=0
                    & HAS_BUS_FINAL
                    & disruptions_used<DISRUPTION_BUDGET
                    & (!NEEDS_STEP_FREE | acc_bus)
                    & (HAS_BUS_PASS | fare_spent+bus_fare<=FARE_MAX)
        -> eff_ok     : (pending'=1)
         + eff_delay  : (service_status'=1) & (disruptions_used'=disruptions_used+1)
         + eff_cancel : (service_status'=2) & (disruptions_used'=disruptions_used+1);

    // Attempt final leg bus -- variant B
    [attempt_final_bus] phase=1 & loc=2 & !done & pending=0 & service_status=0
                    & HAS_BUS_FINAL
                    & disruptions_used>=DISRUPTION_BUDGET
                    & (!NEEDS_STEP_FREE | acc_bus)
                    & (HAS_BUS_PASS | fare_spent+bus_fare<=FARE_MAX)
        -> (pending'=1);

    [ride_final_bus] phase=1 & loc=2 & pending=1
        -> (loc'=3) & (mode'=3) & (fare_spent'=fare_spent+bus_fare) & (pending'=0) & (done'=true);

    // Attempt final leg rail -- variant A
    [attempt_final_rail] phase=1 & loc=2 & !done & pending=0 & service_status=0
                     & HAS_RAIL_FINAL
                     & disruptions_used<DISRUPTION_BUDGET
                     & fare_spent+rail_fare<=FARE_MAX
        -> eff_ok*(1-eff_lift_fail)             : (pending'=2)
         + eff_delay                            : (service_status'=1) & (disruptions_used'=disruptions_used+1)
         + eff_cancel+eff_ok*eff_lift_fail      : (service_status'=2) & (disruptions_used'=disruptions_used+1);

    // Attempt final leg rail -- variant B (budget exhausted; lift failure also suppressed)
    [attempt_final_rail] phase=1 & loc=2 & !done & pending=0 & service_status=0
                     & HAS_RAIL_FINAL
                     & disruptions_used>=DISRUPTION_BUDGET
                     & fare_spent+rail_fare<=FARE_MAX
        -> (pending'=2);

    [ride_final_rail] phase=1 & loc=2 & pending=2
        -> (loc'=3) & (mode'=5) & (fare_spent'=fare_spent+rail_fare) & (pending'=0) & (done'=true);

    // Wait at interchange: resolves delay
    [wait_at_stop] phase=1 & loc=2 & !done & pending=0 & service_status=1
        -> (service_status'=0);

    // Final leg walk
    [final_leg_walk] phase=1 & loc=2 & !done & pending=0 & WALK_TOLERANCE>=DIST_INTERCHANGE_TO_DEST
        -> (loc'=3) & (mode'=2) & (done'=true);

    // Final leg taxi
    [final_leg_taxi] phase=1 & loc=2 & !done & pending=0 & !PT_ONLY & fare_spent+taxi_final_fare<=FARE_MAX
        -> (loc'=3) & (mode'=4) & (fare_spent'=fare_spent+taxi_final_fare) & (done'=true);

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
    [bike_direct]         true      :  TIME_BIKE_DIRECT;
    [walk_to_destination] true      :  TIME_WALK_TO_DEST;
    [walk_to_stop]        true      :  TIME_WALK_TO_STOP;
    [ride_bus]            true      :  TIME_BUS_STOP_TO_INT;
    [ride_rail]           true      :  TIME_RAIL_STOP_TO_INT;
    [ride_final_bus]      true      :  TIME_FINAL_BUS;
    [ride_final_rail]     true      :  TIME_FINAL_RAIL;
    [final_leg_walk]      true      :  TIME_FINAL_WALK;
    [wait_at_stop]        true      :  avg_wait_time;
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
    [ride_bus]            true :  CO2E_BUS_STOP_TO_INT;
    [ride_rail]           true :  CO2E_RAIL_STOP_TO_INT;
    [ride_final_bus]      true :  CO2E_BUS_FINAL;
    [ride_final_rail]     true :  CO2E_RAIL_FINAL;
    [bike_direct]         true :     0;
    [walk_to_destination] true :     0;
    [walk_to_stop]        true :     0;
    [final_leg_walk]      true :     0;
endrewards

// -------------------------------------------------------
// Rewards: fare cost (pence)
//
// Policy effects:
//   policy=2 (low_fare):   bus_fare=100p, rail_fare=200p
//   policy=3 (road_charge): car and taxi +500p
//   HAS_BUS_PASS:           bus_fare=0p regardless of policy
//
// -------------------------------------------------------
rewards "fare"
    [choose_car]      true : car_cost;
    [ride_bus]        true : bus_fare;
    [ride_rail]       true : rail_fare;
    [taxi_direct]     true : taxi_direct_fare;
    [taxi_from_stop]  true : taxi_stop_fare;
    [ride_final_bus]  true : bus_fare;
    [ride_final_rail] true : rail_fare;
    [final_leg_taxi]  true : taxi_final_fare;
endrewards

// -------------------------------------------------------
// Rewards: walking distance (metres)
// -------------------------------------------------------
rewards "walking_distance"
    [walk_to_stop]        true :  DIST_HOME_TO_STOP;
    [final_leg_walk]      true :  DIST_INTERCHANGE_TO_DEST;
    [walk_to_destination] true :  DIST_HOME_TO_DEST;
endrewards



// -------------------------------------------------------
// Rewards: generalized cost (equivalent pence)
// Per-persona trade-off between time, money and walking:
//   W_TIME (pence/min, value of time) | W_FARE (multiplier on pence paid)
//   W_WALK (pence/metre walked)
// give_up charges nothing, consistent with the "time" reward.
// -------------------------------------------------------
rewards "generalized_cost"
    [choose_car]          weather=0 : W_TIME*TIME_CAR_CLEAR          + W_FARE*car_cost;
    [choose_car]          weather=1 : W_TIME*TIME_CAR_RAIN           + W_FARE*car_cost;
    [choose_car]          weather=2 : W_TIME*TIME_CAR_SEVERE         + W_FARE*car_cost;
    [taxi_direct]         weather=0 : W_TIME*TIME_TAXI_DIRECT_CLEAR  + W_FARE*taxi_direct_fare;
    [taxi_direct]         weather=1 : W_TIME*TIME_TAXI_DIRECT_RAIN   + W_FARE*taxi_direct_fare;
    [taxi_direct]         weather=2 : W_TIME*TIME_TAXI_DIRECT_SEVERE + W_FARE*taxi_direct_fare;
    [taxi_from_stop]      weather=0 : W_TIME*TIME_TAXI_STOP_CLEAR    + W_FARE*taxi_stop_fare;
    [taxi_from_stop]      weather=1 : W_TIME*TIME_TAXI_STOP_RAIN     + W_FARE*taxi_stop_fare;
    [taxi_from_stop]      weather=2 : W_TIME*TIME_TAXI_STOP_SEVERE   + W_FARE*taxi_stop_fare;
    [final_leg_taxi]      weather=0 : W_TIME*TIME_TAXI_FINAL_CLEAR   + W_FARE*taxi_final_fare;
    [final_leg_taxi]      weather=1 : W_TIME*TIME_TAXI_FINAL_RAIN    + W_FARE*taxi_final_fare;
    [final_leg_taxi]      weather=2 : W_TIME*TIME_TAXI_FINAL_SEVERE  + W_FARE*taxi_final_fare;
    [bike_direct]         true      : W_TIME*TIME_BIKE_DIRECT;
    [walk_to_destination] true      : W_TIME*TIME_WALK_TO_DEST       + W_WALK*DIST_HOME_TO_DEST;
    [walk_to_stop]        true      : W_TIME*TIME_WALK_TO_STOP       + W_WALK*DIST_HOME_TO_STOP;
    [ride_bus]            true      : W_TIME*TIME_BUS_STOP_TO_INT    + W_FARE*bus_fare;
    [ride_rail]           true      : W_TIME*TIME_RAIL_STOP_TO_INT   + W_FARE*rail_fare;
    [ride_final_bus]      true      : W_TIME*TIME_FINAL_BUS          + W_FARE*bus_fare;
    [ride_final_rail]     true      : W_TIME*TIME_FINAL_RAIL         + W_FARE*rail_fare;
    [final_leg_walk]      true      : W_TIME*TIME_FINAL_WALK         + W_WALK*DIST_INTERCHANGE_TO_DEST;
    [wait_at_stop]        true      : W_TIME*avg_wait_time;
endrewards
