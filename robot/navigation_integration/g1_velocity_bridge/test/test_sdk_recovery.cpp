#include <g1_velocity_bridge/contract.hpp>
#include <g1_velocity_bridge/sdk_fault.hpp>
#include <cassert>
#include <cmath>
#include <limits>

using g1_bridge::SdkRecovery;
int main() {
  SdkRecovery r;
  assert(r.begin(3104,0.));
  assert(r.record_zero(0,0.));assert(r.record_zero(0,.5));
  assert(r.record_zero(3104,1.));assert(r.successes()==0);
  assert(!r.ready(1.,true,true));
  assert(r.record_zero(0,1.5));assert(r.record_zero(0,2.));assert(r.record_zero(0,2.5));
  assert(!r.ready(2.5,false,true));assert(!r.ready(2.5,true,false));
  assert(r.ready(2.5,true,true));r.complete();assert(!r.active());
  assert(r.begin(3104,3.));
  assert(!r.record_zero(7301,3.1)&&r.failed());
  assert(!r.begin(3104,70.)); // A fatal failure requires explicit re-enable.
  r=SdkRecovery{};
  assert(r.begin(3104,0.));
  for(int i=0;i<20;++i)assert(r.record_zero(3104,i*.5));
  assert(r.expired(10.)&&!r.probe_due(10.));
  assert(!r.record_zero(0,10.)&&r.failed());
  r=SdkRecovery{};
  assert(r.begin(3104,0.));r.complete();
  assert(r.begin(3104,30.));r.complete();
  assert(r.begin(3104,59.));r.complete();
  assert(r.begin(3104,60.));r.complete(); // Sliding window ages out older events.
  assert(!r.begin(3104,60.1));
  r=SdkRecovery{};
  assert(!r.begin(3104,std::numeric_limits<double>::quiet_NaN()));

  // The same active mission survives a recovery, but authorization and sensor
  // freshness are never supplied by the recovery object.
  g1_bridge::Contract c;
  c.arm(true);c.goal_ready=true;c.healthy=true;c.plan_time=c.health_time=10.;
  c.update_command(.1,0.,.1,10.);c.trial_seconds=c.travel_limit=c.turn_limit=0.;
  r=SdkRecovery{};assert(r.begin(3104,10.));
  assert(r.record_zero(3104,10.));
  assert(r.record_zero(0,10.5));assert(r.record_zero(0,11.));assert(r.record_zero(0,11.5));
  assert(!r.ready(11.5,true,c.preparation_allowed(11.5))); // Stale health.
  c.health_time=c.plan_time=11.5;
  assert(r.ready(11.5,true,c.preparation_allowed(11.5)));
  r.complete();c.ready_after=11.5;c.cmd_time=-1e30;
  assert(c.enabled&&c.goal_ready);
  assert(c.sample(11.5,true).reason=="command_timeout");
  c.update_command(.1,0.,.1,11.6);c.health_time=11.6;
  assert(c.sample(11.6,true).reason=="ready");
  c.new_goal();assert(c.sample(11.6,true).reason=="waiting_new_goal_and_plan");
  c.arm(false);assert(c.sample(11.6,true).reason=="disabled");
}
