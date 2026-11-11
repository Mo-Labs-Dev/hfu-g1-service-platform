#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <string>

namespace g1_bridge {
inline int64_t request_stamp_ns(int32_t sec,uint32_t nanosec) {
  if(sec<0||nanosec>=1000000000u)return 0;
  return int64_t(sec)*1000000000+nanosec;
}
inline bool finite_position(double x,double y,double z) {
  return std::isfinite(x)&&std::isfinite(y)&&std::isfinite(z);
}
template<class Path> bool valid_mission(const Path &mission) {
  const auto &header=mission.header;
  if(header.frame_id!="map"||
     request_stamp_ns(header.stamp.sec,header.stamp.nanosec)<=0||mission.poses.empty())return false;
  for(const auto &pose:mission.poses) {
    const auto &p=pose.pose.position;
    if(!finite_position(p.x,p.y,p.z))return false;
    const auto &q=pose.pose.orientation;
    if(!std::isfinite(q.x)||!std::isfinite(q.y)||!std::isfinite(q.z)||!std::isfinite(q.w))return false;
    const double norm=std::sqrt(q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w);
    if(!std::isfinite(norm)||(norm>0.&&norm<1e-6))return false;
    if(!pose.header.frame_id.empty()&&pose.header.frame_id!="map")return false;
  }
  return true;
}
// This epoch survives cancel, completion, and enable/disable. A latched or
// delayed request must never revive a retired task or reuse its authorization.
class RequestEpoch {
public:
  bool allowed(int64_t stamp,int64_t enabled_after,bool enabled) const {
    return enabled&&stamp>0&&stamp>=enabled_after&&stamp>last_stamp_;
  }
  bool accept(int64_t stamp,int64_t enabled_after,bool enabled) {
    if(!allowed(stamp,enabled_after,enabled))return false;
    last_stamp_=stamp;return true;
  }
  void retire_through(int64_t stamp) {last_stamp_=std::max(last_stamp_,stamp);}
private:
  int64_t last_stamp_=0;
};
inline bool current_plan(const std::string &frame,int64_t stamp,int64_t request,bool active) {
  return active&&frame=="map"&&stamp>0&&stamp==request;
}
inline int controller_phase(const std::string &state) {
  if(state=="aligning_goal_yaw")return 1;
  if(state=="following"||state=="turning_to_path"||state=="correcting_goal_position")return 0;
  return 2; // Every waiting, blocked, completed or failed controller state holds ZERO.
}
struct Decision { std::array<double,3> velocity{}; std::string reason; };
class Contract {
public:
  double max_vx=.10,max_wz=.15,timeout=.30,health_timeout=.30,plan_timeout=6.;
  double trial_seconds=20.,travel_limit=.75,turn_limit=.6;
  bool enabled=false,healthy=false,goal_ready=false;
  double cmd_time=-1e30,health_time=-1e30,plan_time=-1e30,first_motion=-1.;
  double last_tick=-1.,distance=0.,turn=0.;
  double ready_after=-1e30;
  std::array<double,3> command{};
  void arm(bool value) {
    enabled=value;goal_ready=false;command={};cmd_time=-1e30;
    first_motion=-1.;distance=turn=0.;last_tick=-1.;ready_after=-1e30;
  }
  void new_goal() { goal_ready=false;first_motion=-1.;distance=turn=0.; }
  bool preparation_allowed(double now) const {
    return enabled&&goal_ready&&healthy&&now-health_time<=health_timeout&&
           now-plan_time<=plan_timeout;
  }
  void update_command(double vx,double vy,double wz,double now) {
    if(!std::isfinite(vx)||!std::isfinite(vy)||!std::isfinite(wz)) {
      command={};cmd_time=-1e30;return;
    }
    command={std::clamp(vx,-max_vx,max_vx),0.,std::clamp(wz,-max_wz,max_wz)};
    cmd_time=now;
  }
  Decision sample(double now,bool native_ready=true) {
    double dt=last_tick<0?0.:std::max(0.,now-last_tick);last_tick=now;
    if(!enabled)return {{},"disabled"};
    if(!goal_ready)return {{},"waiting_new_goal_and_plan"};
    if(!native_ready)return {{},"native_not_ready"};
    if(!healthy||now-health_time>health_timeout)return {{},"navigation_unhealthy"};
    if(now-plan_time>plan_timeout)return {{},"plan_timeout"};
    if(now-cmd_time>timeout)return {{},"command_timeout"};
    if(cmd_time<ready_after)return {{},"waiting_fresh_command"};
    if(first_motion>=0 && ((trial_seconds>0&&now-first_motion>=trial_seconds)||
       (travel_limit>0&&distance>=travel_limit)||(turn_limit>0&&turn>=turn_limit))) {
      enabled=false;goal_ready=false;return {{},"trial_limit"};
    }
    if(command[0]!=0.||command[2]!=0.) {
      if(first_motion<0)first_motion=now;
      distance+=std::abs(command[0])*dt;turn+=std::abs(command[2])*dt;
    }
    return {command,"ready"};
  }
  Decision sample_terminal(double now,bool native_ready,int phase,
                           double raw_wz,double raw_time,double turn_cap) {
    const auto smoothed=command;
    const bool fresh=std::isfinite(raw_wz)&&now>=raw_time&&now-raw_time<=timeout;
    if(phase>0)command={};
    if(phase==1&&fresh)command[2]=std::clamp(raw_wz,-turn_cap,turn_cap);
    // Run the usual authorization/freshness gates and account the actual
    // terminal command in the existing optional distance/turn budgets.
    auto decision=sample(now,native_ready);
    command=smoothed;
    if(phase==1&&!fresh&&decision.reason=="ready")decision.reason="terminal_command_timeout";
    return decision;
  }
};
}
