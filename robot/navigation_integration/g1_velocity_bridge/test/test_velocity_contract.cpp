#include <g1_velocity_bridge/contract.hpp>
#include <g1_velocity_bridge/native_mode.hpp>
#include <g1_velocity_bridge/sdk_fault.hpp>
#include <cassert>
#include <limits>
#include <vector>
using g1_bridge::Contract;
struct Stamp {int32_t sec=0;uint32_t nanosec=0;};
struct Header {std::string frame_id;Stamp stamp;};
struct Position {double x=0.,y=0.,z=0.;};
struct Quaternion {double x=0.,y=0.,z=0.,w=1.;};
struct TestPose {Header header;struct {Position position;Quaternion orientation;} pose;};
struct Mission {Header header;std::vector<TestPose> poses;};
static void ready(Contract &c,double t) {
  c.arm(true);c.goal_ready=true;c.plan_time=t-1.;c.healthy=true;c.health_time=t;
  c.update_command(.3,.2,.6,t);
}
int main() {
  Mission mission;mission.header={"map",{10,1}};
  assert(!g1_bridge::valid_mission(mission)); // Empty requests are never tasks.
  mission.poses.resize(3);
  mission.poses[0].pose.position={1.,2.,0.};
  mission.poses[1].pose.position={2.,2.,.1};
  mission.poses[2].pose.position={3.,2.,.1};
  assert(g1_bridge::valid_mission(mission));
  mission.poses[1].pose.orientation.w=std::numeric_limits<double>::quiet_NaN();
  assert(!g1_bridge::valid_mission(mission));
  mission.poses[1].pose.orientation.w=1e-8;assert(!g1_bridge::valid_mission(mission));
  mission.poses[1].pose.orientation.w=0.;assert(g1_bridge::valid_mission(mission)); // unset heading
  mission.poses[1].pose.orientation.w=1.;
  mission.poses[1].pose.position.x=std::numeric_limits<double>::quiet_NaN();
  assert(!g1_bridge::valid_mission(mission)); // Validate every waypoint, not just the final goal.
  mission.poses[1].pose.position.x=2.;
  mission.poses[0].pose.position.z=std::numeric_limits<double>::infinity();
  assert(!g1_bridge::valid_mission(mission));
  mission.poses[0].pose.position.z=0.;
  mission.poses[0].header.frame_id="odom";
  assert(!g1_bridge::valid_mission(mission));
  mission.poses[0].header.frame_id="map";
  mission.header.frame_id="odom";assert(!g1_bridge::valid_mission(mission));
  mission.header.frame_id="map";
  mission.header.stamp={0,0};assert(!g1_bridge::valid_mission(mission));
  mission.header.stamp={-1,1};assert(!g1_bridge::valid_mission(mission));
  mission.header.stamp={1,1000000000u};assert(!g1_bridge::valid_mission(mission));
  mission.header.stamp={0,1};assert(g1_bridge::valid_mission(mission));

  g1_bridge::RequestEpoch epoch;
  assert(!epoch.accept(101,100,false)); // A request never arms motion.
  assert(!epoch.accept(99,100,true));
  assert(!epoch.accept(0,0,true));
  assert(epoch.accept(101,100,true));
  assert(!epoch.accept(101,100,true)); // Latched repeats cannot restart budgets or motion.
  assert(!epoch.accept(100,100,true));
  assert(epoch.accept(102,100,true)); // Goal and mission share one monotonic epoch.
  epoch.retire_through(200); // Cancel also discards requests queued before cancellation.
  assert(!epoch.accept(150,100,true));
  assert(!epoch.accept(200,100,true));
  assert(epoch.accept(201,100,true));
  epoch.retire_through(150); // A backward clock or old cancel cannot roll back the epoch.
  assert(!epoch.accept(201,100,true));
  epoch.retire_through(300); // Re-enable still needs a fresh request.
  assert(!epoch.accept(201,300,true));
  assert(!epoch.accept(300,300,true));
  assert(epoch.accept(301,300,true));
  assert(g1_bridge::current_plan("map",301,301,true));
  assert(!g1_bridge::current_plan("map",300,301,true));
  assert(!g1_bridge::current_plan("map",302,301,true)); // Future/other-task plans are no authorization.
  assert(!g1_bridge::current_plan("odom",301,301,true));
  assert(!g1_bridge::current_plan("map",301,301,false));
  assert(!g1_bridge::current_plan("map",0,0,true));
  assert(g1_bridge::controller_phase("aligning_goal_yaw")==1);
  for(const auto &state:{"following","turning_to_path","correcting_goal_position"})
    assert(g1_bridge::controller_phase(state)==0);
  for(const auto &state:{"waypoint_dwell","braking_goal","settling_goal_yaw","blocked_obstacle","stale_path", "waiting_path","waiting_tf","goal_height_mismatch","goal_reached","cancelled","terminal_turn_unresponsive","unknown"})
    assert(g1_bridge::controller_phase(state)==2);
  g1_bridge::SdkRecovery faults;
  assert(faults.begin(3104,10.));
  assert(faults.record_zero(3104,10.1)); // Even ZERO may initially time out.
  assert(!faults.ready(10.1,true,true));
  assert(!faults.probe_due(10.5)&&faults.probe_due(10.6));
  assert(faults.record_zero(0,10.6));
  assert(faults.record_zero(0,11.1));
  assert(!faults.ready(11.1,true,true));
  assert(faults.record_zero(0,11.6));
  assert(!faults.ready(11.6,false,true)&&!faults.ready(11.6,true,false));
  assert(faults.ready(11.6,true,true));faults.complete();
  assert(!faults.active()&&!faults.failed());
  assert(faults.begin(3104,12.));faults.complete();
  assert(faults.begin(3104,14.));faults.complete();
  assert(!faults.begin(3104,15.)&&faults.failed()); // Fourth event in a minute fails.
  g1_bridge::SdkRecovery fatal;
  assert(!fatal.begin(7301,10.)&&fatal.failed()); // Real rejection never retried.
  Contract recovering;ready(recovering,50.);
  recovering.ready_after=50.1;
  assert(recovering.sample(50.1,false).reason=="native_not_ready");
  assert(recovering.sample(50.1,true).reason=="waiting_fresh_command");
  recovering.update_command(.1,0.,.1,50.2);recovering.health_time=50.2;
  assert(recovering.sample(50.2,true).reason=="ready");
  recovering.healthy=false;
  assert(recovering.sample(50.2,true).reason=="navigation_unhealthy");
  for(int fsm:{500,501,802,812}) {
    assert(g1_bridge::velocity_fsm(fsm));
    assert(!g1_bridge::walkrun_preparation_fsm(fsm,true,true));
    Contract gait;ready(gait,10.);
    assert(gait.sample(10.,g1_bridge::velocity_fsm(fsm)).reason=="ready");
  }
  for(int fsm:{-1,0,1,2,3,4,803,811,813}) {
    assert(!g1_bridge::velocity_fsm(fsm));
    Contract unknown;ready(unknown,10.);
    assert(unknown.sample(10.,g1_bridge::velocity_fsm(fsm)).reason=="native_not_ready");
  }
  assert(g1_bridge::walkrun_preparation_fsm(4,true,true));
  assert(!g1_bridge::walkrun_preparation_fsm(4,false,true));
  assert(!g1_bridge::walkrun_preparation_fsm(4,true,false));
  Contract c;c.update_command(.3,0.,.6,10.);
  assert(c.sample(10.).reason=="disabled");
  c.arm(true);assert(c.sample(10.).reason=="waiting_new_goal_and_plan");
  assert(!c.preparation_allowed(10.)); // Auto-arming alone must not switch FSM.
  ready(c,10.);auto d=c.sample(10.);assert(d.velocity[0]==.1&&d.velocity[1]==0.&&d.velocity[2]==.15);
  assert(c.preparation_allowed(10.));
  assert(!c.preparation_allowed(10.4));
  assert(c.sample(10.,false).reason=="native_not_ready");
  c.health_time=10.4;assert(c.sample(10.4).reason=="command_timeout");
  ready(c,11.);c.healthy=false;assert(c.sample(11.).reason=="navigation_unhealthy");
  ready(c,12.);c.update_command(std::numeric_limits<double>::quiet_NaN(),0.,0.,12.);
  assert(c.sample(12.).reason=="command_timeout");
  ready(c,13.);c.new_goal();assert(c.sample(13.).reason=="waiting_new_goal_and_plan");
  ready(c,14.);c.ready_after=14.5;assert(c.sample(14.).reason=="waiting_fresh_command");
  ready(c,20.);c.travel_limit=.01;c.sample(20.);
  c.health_time=20.2;c.update_command(.1,0.,0.,20.2);c.sample(20.2);
  assert(c.sample(20.2).reason=="trial_limit"&&!c.enabled);
  ready(c,30.);c.arm(false);assert(c.sample(30.).reason=="disabled");
  assert(!c.preparation_allowed(30.));

  // Continuous navigation exceeds all former trial budgets while keeping
  // velocity limits and freshness/disable gates active.
  Contract continuous;
  continuous.trial_seconds=continuous.travel_limit=continuous.turn_limit=0.;
  ready(continuous,0.);
  for(int i=0;i<=300;++i) {
    double t=i*.1;
    continuous.plan_time=continuous.health_time=t;
    continuous.update_command(1.,0.,1.,t);
    auto v=continuous.sample(t);
    assert(v.reason=="ready"&&continuous.enabled);
    assert(v.velocity[0]==.1&&v.velocity[2]==.15);
  }
  assert(continuous.distance>2.9&&continuous.turn>4.4);
  assert(continuous.sample(30.5).reason=="navigation_unhealthy");
  continuous.arm(false);assert(continuous.sample(30.5).reason=="disabled");

  Contract fast;fast.max_vx=1.;fast.max_wz=.8;
  ready(fast,40.);fast.update_command(2.,0.,2.,40.);
  auto capped=fast.sample(40.);
  assert(capped.velocity[0]==1.&&capped.velocity[2]==.8);
  fast.health_time=40.4;
  assert(fast.sample(40.4).reason=="command_timeout");

  Contract terminal;terminal.max_vx=1.;terminal.max_wz=.8;
  terminal.trial_seconds=terminal.travel_limit=terminal.turn_limit=0.;
  ready(terminal,60.);terminal.update_command(.3,0.,.025,60.);
  auto direct=terminal.sample_terminal(60.,true,1,.8,60.,.8);
  assert(direct.reason=="ready"&&direct.velocity[0]==0.&&direct.velocity[2]==.8);
  auto slow_heading=terminal.sample_terminal(60.,true,1,.12,60.,.8);
  assert(slow_heading.velocity[0]==0.&&slow_heading.velocity[2]==.12);
  auto slow_negative=terminal.sample_terminal(60.,true,1,-.13,60.,.8);
  assert(slow_negative.velocity[0]==0.&&slow_negative.velocity[2]==-.13);
  auto following=terminal.sample_terminal(60.,true,0,.8,60.,.8);
  assert(following.velocity[0]==.3&&following.velocity[2]==.025);
  assert(terminal.sample_terminal(60.,true,2,.8,60.,.8).velocity[2]==0.);
  // A station's five-second hold overrides residual nonzero smoother output,
  // preserves the mission authorization, and resumes without a new Goal.
  Contract dwell;dwell.max_vx=1.;dwell.max_wz=.8;
  dwell.trial_seconds=dwell.travel_limit=dwell.turn_limit=0.;
  ready(dwell,100.);
  for(int i=0;i<=50;++i) {
    double t=100.+i*.1;
    dwell.plan_time=dwell.health_time=t;dwell.update_command(.3,0.,.6,t);
    auto hold=dwell.sample_terminal(t,true,g1_bridge::controller_phase("waypoint_dwell"),.8,t,.8);
    assert(hold.velocity[0]==0.&&hold.velocity[2]==0.&&dwell.enabled&&dwell.goal_ready);
  }
  auto resume=dwell.sample_terminal(105.,true,g1_bridge::controller_phase("following"),.8,105.,.8);
  assert(resume.velocity[0]==.3&&resume.velocity[2]==.6);
  assert(terminal.sample_terminal(60.,true,1,-2.,60.,.8).velocity[2]==-.8);
  assert(terminal.sample_terminal(60.,true,1,.8,59.,.8).reason=="terminal_command_timeout");
  assert(terminal.sample_terminal(60.,true,1,.8,59.,.8).velocity[2]==0.);
  assert(terminal.sample_terminal(60.,true,1,std::numeric_limits<double>::quiet_NaN(),60.,.8).velocity[2]==0.);
  assert(terminal.sample_terminal(60.,false,1,.8,60.,.8).reason=="native_not_ready");
  terminal.healthy=false;
  assert(terminal.sample_terminal(60.,true,1,.8,60.,.8).reason=="navigation_unhealthy");
  terminal.healthy=true;terminal.health_time=60.4;
  assert(terminal.sample_terminal(60.4,true,1,.8,60.4,.8).reason=="command_timeout");
  ready(terminal,61.);terminal.arm(false);
  assert(terminal.sample_terminal(61.,true,1,.8,61.,.8).reason=="disabled");
  ready(terminal,62.);terminal.new_goal();
  assert(terminal.sample_terminal(62.,true,1,.8,62.,.8).reason=="waiting_new_goal_and_plan");
  ready(terminal,63.);terminal.turn_limit=.05;
  terminal.sample_terminal(63.,true,1,.8,63.,.8);
  terminal.health_time=63.1;terminal.update_command(0.,0.,.01,63.1);
  terminal.sample_terminal(63.1,true,1,.8,63.1,.8);
  assert(terminal.sample_terminal(63.2,true,1,.8,63.2,.8).reason=="trial_limit");
}
