#pragma once

namespace g1_bridge {
// 812 was read on this G1 after the operator selected the stock obstacle gait.
// Keep an explicit set: passive, damping and unknown FSMs must not get velocity.
inline bool velocity_fsm(int fsm) {
  return fsm==500 || fsm==501 || fsm==802 || fsm==812;
}

// The optional legacy preparation is only for SDK StandUp (4). It must never
// replace a selected locomotion gait or take over an unknown/custom controller.
inline bool walkrun_preparation_fsm(int fsm, bool fsm_ok, bool mode_ok) {
  return fsm_ok && mode_ok && fsm==4;
}
}
