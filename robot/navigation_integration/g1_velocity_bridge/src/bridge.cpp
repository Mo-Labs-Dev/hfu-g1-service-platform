#include <g1_velocity_bridge/contract.hpp>
#include <g1_velocity_bridge/native_mode.hpp>
#include <g1_velocity_bridge/sdk_fault.hpp>
#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <geometry_msgs/msg/pose_stamped.hpp>
#include <nav_msgs/msg/path.hpp>
#include <std_msgs/msg/bool.hpp>
#include <std_msgs/msg/empty.hpp>
#include <std_msgs/msg/string.hpp>
#include <std_srvs/srv/set_bool.hpp>
#include <tf2_ros/buffer.h>
#include <tf2_ros/transform_listener.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>
#ifdef G1_BRIDGE_FAULT_TEST
#include "fake_loco.hpp" // Test-only target: no Unitree SDK or robot DDS linked.
#else
#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/g1/loco/g1_loco_client.hpp>
#endif
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <mutex>
#include <thread>

using namespace std::chrono_literals;
using Pose=geometry_msgs::msg::PoseStamped;
using Twist=geometry_msgs::msg::Twist;
static double now_s() {
  return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
static int64_t stamp_ns(const builtin_interfaces::msg::Time &s) {
  return g1_bridge::request_stamp_ns(s.sec,s.nanosec);
}
class Bridge : public rclcpp::Node {
public:
  Bridge():Node("nav_velocity_bridge"),buffer_(get_clock()),listener_(buffer_) {
    dry_=declare_parameter("dry_run",true);
    prepare_=declare_parameter("prepare_walkrun_on_enable",false);
    const bool auto_enable=declare_parameter("auto_enable_motion",false);
    std::string network=declare_parameter("network_interface",std::string("eth0"));
    input_=declare_parameter("input_topic",std::string("/cmd_vel_preview"));
    contract_.max_vx=declare_parameter("max_vx",.10);
    contract_.max_wz=declare_parameter("max_wz",.15);
    terminal_max_wz_=declare_parameter("terminal_max_wz",.30);
    contract_.timeout=declare_parameter("command_timeout",.30);
    contract_.health_timeout=declare_parameter("health_timeout",.30);
    contract_.trial_seconds=declare_parameter("trial_seconds",20.);
    contract_.travel_limit=declare_parameter("travel_limit",.75);
    contract_.turn_limit=declare_parameter("turn_limit",.60);
    yaw_sign_=declare_parameter("yaw_sign",1.);
    duration_=declare_parameter("sdk_command_duration",.25);
    for(double x:{contract_.max_vx,contract_.max_wz,contract_.timeout,
                  contract_.health_timeout,duration_})
      if(!std::isfinite(x)||x<=0.)throw std::runtime_error("Invalid velocity limit/timeout");
    if(!std::isfinite(terminal_max_wz_)||terminal_max_wz_<=0.)
      throw std::runtime_error("Invalid terminal angular limit");
    if(duration_>.5)throw std::runtime_error("SDK command duration must be <=0.5s");
    if(!std::isfinite(yaw_sign_)||std::abs(yaw_sign_)!=1.)
      throw std::runtime_error("yaw_sign must be +1 or -1");
    command_pub_=create_publisher<Twist>("/nav/hardware_cmd_vel",1);
    status_pub_=create_publisher<std_msgs::msg::String>("/nav/bridge_status",rclcpp::QoS(1).transient_local());
    // These are continuously refreshed latest-state streams. Do not wait for
    // reliable retransmission of an obsolete velocity/health sample.
    const auto live_qos=rclcpp::QoS(1).best_effort();
    command_sub_=create_subscription<Twist>(input_,live_qos,[this](const Twist::SharedPtr m) {
      std::lock_guard<std::mutex> lock(mutex_);
      contract_.update_command(m->linear.x,m->linear.y,m->angular.z,now_s());
    });
    terminal_command_sub_=create_subscription<Twist>("/nav/cmd_vel_raw",live_qos,[this](const Twist::SharedPtr m) {
      std::lock_guard<std::mutex> lock(mutex_);
      const bool valid=std::isfinite(m->linear.x)&&std::isfinite(m->linear.y)&&std::isfinite(m->angular.z);
      terminal_raw_wz_=valid?m->angular.z:0.;terminal_raw_time_=valid?now_s():-1e30;
    });
    health_sub_=create_subscription<std_msgs::msg::Bool>("/nav/healthy",live_qos,[this](const std_msgs::msg::Bool::SharedPtr m) {
      std::lock_guard<std::mutex> lock(mutex_);
      contract_.healthy=m->data;contract_.health_time=now_s();
    });
    goal_sub_=create_subscription<Pose>("/goal_pose",1,[this](const Pose::SharedPtr m) {
      const auto stamp=stamp_ns(m->header.stamp);
      const auto &p=m->pose.position;
      if(!g1_bridge::finite_position(p.x,p.y,p.z))return;
      {
        std::lock_guard<std::mutex> lock(mutex_);
        if(!request_epoch_.allowed(stamp,enable_ros_stamp_,contract_.enabled))return;
      }
      try {
        auto requested=buffer_.transform(*m,"map",tf2::durationFromSec(.1));
        const auto &q=requested.pose.position;
        if(!g1_bridge::finite_position(q.x,q.y,q.z))return;
        std::lock_guard<std::mutex> lock(mutex_);
        if(!request_epoch_.accept(stamp,enable_ros_stamp_,contract_.enabled))return;
        accept_request(requested,stamp);
        RCLCPP_INFO(get_logger(),"New Goal received; waiting for its confirmed path");
      } catch(const tf2::TransformException &e) {
        RCLCPP_ERROR(get_logger(),"Goal transform failed: %s",e.what());
      }
    });
    mission_sub_=create_subscription<nav_msgs::msg::Path>("/nav3d/mission",1,
      [this](const nav_msgs::msg::Path::SharedPtr m) {
        // Validate the entire ordered request before touching authorization.
        // Intermediate waypoint updates never become independent SDK goals.
        if(!g1_bridge::valid_mission(*m))return;
        const auto stamp=stamp_ns(m->header.stamp);
        Pose requested=m->poses.back();requested.header=m->header;
        std::lock_guard<std::mutex> lock(mutex_);
        if(!request_epoch_.accept(stamp,enable_ros_stamp_,contract_.enabled))return;
        accept_request(requested,stamp);
        RCLCPP_INFO(get_logger(),"New mission received (%zu waypoints); waiting for its confirmed path",m->poses.size());
      });
    target_sub_=create_subscription<Pose>("/nav3d/goal",rclcpp::QoS(1).transient_local(),
      [this](const Pose::SharedPtr m) {
        std::lock_guard<std::mutex> lock(mutex_);
        if(!matches_request(*m))return;
        confirmed_stamp_=stamp_ns(m->header.stamp);check_plan();
      });
    plan_sub_=create_subscription<nav_msgs::msg::Path>("/nav3d/plan",1,[this](const nav_msgs::msg::Path::SharedPtr m) {
      std::lock_guard<std::mutex> lock(mutex_);
      if(!g1_bridge::current_plan(m->header.frame_id,stamp_ns(m->header.stamp),request_stamp_,has_request_))return;
      if(m->poses.empty()) {contract_.goal_ready=false;plan_stamp_=0;return;}
      plan_stamp_=stamp_ns(m->header.stamp);plan_receipt_=now_s();check_plan();
    });
    controller_state_sub_=create_subscription<std_msgs::msg::String>("/nav3d/controller_status",10,
      [this](const std_msgs::msg::String::SharedPtr m) {
        std::lock_guard<std::mutex> lock(mutex_);
        terminal_phase_=g1_bridge::controller_phase(m->data);
      });
    reached_sub_=create_subscription<Pose>("/nav3d/goal_reached",10,
      [this](const Pose::SharedPtr m) {
        std::lock_guard<std::mutex> lock(mutex_);
        if(matches_request(*m)) {
          contract_.new_goal();has_request_=false;confirmed_stamp_=plan_stamp_=0;
        }
      });
    cancel_sub_=create_subscription<std_msgs::msg::Empty>("/nav3d/cancel",10,
      [this](const std_msgs::msg::Empty::SharedPtr) {
        std::lock_guard<std::mutex> lock(mutex_);
        request_epoch_.retire_through(get_clock()->now().nanoseconds());
        contract_.new_goal();has_request_=false;confirmed_stamp_=plan_stamp_=0;
      });
    enable_=create_service<std_srvs::srv::SetBool>("/nav/enable_motion",
      [this](const std::shared_ptr<std_srvs::srv::SetBool::Request> req,
             std::shared_ptr<std_srvs::srv::SetBool::Response> response) {
        std::lock_guard<std::mutex> lock(mutex_);
        contract_.arm(req->data);has_request_=false;confirmed_stamp_=plan_stamp_=0;
        ++enable_generation_; // Explicit enable/disable retires pending recovery.
        enable_ros_stamp_=get_clock()->now().nanoseconds();
        request_epoch_.retire_through(enable_ros_stamp_);
        prepare_requested_=false; // Preparation requires a fresh confirmed Goal.
        response->success=true;
        response->message=req->data?"Enabled: set a NEW Goal; native API checks still apply":"Disabled: stop requested";
      });
    if(!dry_) {
      unitree::robot::ChannelFactory::Instance()->Init(0,network);
      loco_=std::make_unique<unitree::robot::g1::LocoClient>();loco_->Init();loco_->SetTimeout(.2f);
    }
    if(auto_enable) {
      contract_.arm(true);
      enable_ros_stamp_=get_clock()->now().nanoseconds();
    }
    worker_=std::thread([this]{run();});
    RCLCPP_INFO(get_logger(),"%s bridge %s -> G1 SDK; %s",
                dry_?"DRY RUN":"LIVE",input_.c_str(),
                auto_enable?"armed, waiting for a NEW Goal and valid path":"disabled until /nav/enable_motion");
  }
  ~Bridge() override {running_=false;if(worker_.joinable())worker_.join();}
private:
  void accept_request(const Pose &requested,int64_t stamp) {
    requested_=requested;has_request_=true;request_stamp_=stamp;
    contract_.new_goal();terminal_phase_=0;confirmed_stamp_=plan_stamp_=0;
    terminal_raw_time_=-1e30;prepare_requested_=false;
  }
  bool matches_request(const Pose &pose) const {
    if(!g1_bridge::current_plan(pose.header.frame_id,stamp_ns(pose.header.stamp),request_stamp_,has_request_))return false;
    const auto &a=pose.pose.position,&b=requested_.pose.position;
    return g1_bridge::finite_position(a.x,a.y,a.z)&&
      std::hypot(a.x-b.x,a.y-b.y)<=.02&&std::abs(a.z-b.z)<=.02;
  }
  void check_plan() {
    if(has_request_&&confirmed_stamp_==request_stamp_&&plan_stamp_==request_stamp_) {
      if(!contract_.goal_ready) {
        contract_.ready_after=plan_receipt_+.5;
        prepare_requested_=prepare_&&!dry_;
      }
      contract_.goal_ready=true;contract_.plan_time=plan_receipt_;
    }
  }
  bool custom_controller_running() {
    for(auto &p:std::filesystem::directory_iterator("/proc")) {
      if(!p.is_directory())continue;
      std::ifstream f(p.path()/"cmdline",std::ios::binary);
      std::string s((std::istreambuf_iterator<char>(f)),{});
      if(s.find("/g1_ctrl")!=std::string::npos)return true;
    }
    return false;
  }
  void run() {
    bool owned=false,native_ready=dry_;int fsm=-1,mode=-1,last_ret=0;
    g1_bridge::SdkRecovery recovery;
    bool recovery_failed_reported=false;
    uint64_t recovery_generation=0;
    bool query_fsm=true,fsm_ok=false,mode_ok=false;
    double next_query=0.,next_status=0.;std::string last_reason;
    while(running_&&rclcpp::ok()) {
      auto start=std::chrono::steady_clock::now();double now=now_s();
      bool preparation;
      {std::lock_guard<std::mutex> lock(mutex_);
       if(recovery_generation!=enable_generation_) {
         recovery=g1_bridge::SdkRecovery{};recovery_generation=enable_generation_;
         recovery_failed_reported=false;
         fsm_ok=mode_ok=native_ready=false;next_query=0.;
       }
       preparation=prepare_requested_&&!recovery.active()&&!recovery.failed();prepare_requested_=false;}
      bool conflict=!dry_&&(now>=next_query||preparation)&&custom_controller_running();
      if(conflict) {
        std::lock_guard<std::mutex> lock(mutex_);contract_.arm(false);
        RCLCPP_ERROR(get_logger(),"Custom g1_ctrl active: refusing native motion");
      }
      if(!dry_&&now>=next_query) {
        // One bounded state RPC per cycle keeps velocity refreshes timely.
        if(query_fsm)fsm_ok=loco_->GetFsmId(fsm)==0;
        else mode_ok=loco_->GetFsmMode(mode)==0;
        query_fsm=!query_fsm;
        native_ready=!conflict&&fsm_ok&&mode_ok&&g1_bridge::velocity_fsm(fsm);
        next_query=now_s()+.5;
      }
      if(preparation&&!conflict&&!native_ready&&
         g1_bridge::walkrun_preparation_fsm(fsm,fsm_ok,mode_ok)) {
        // Only a newly accepted goal with a confirmed route and live navigation
        // may switch the native FSM. Starting the launcher itself cannot move G1.
        bool authorized;int64_t generation;
        {std::lock_guard<std::mutex> lock(mutex_);
         authorized=contract_.preparation_allowed(now_s());generation=request_stamp_;}
        if(!authorized) {
          std::lock_guard<std::mutex> lock(mutex_);
          if(contract_.enabled&&contract_.goal_ready)prepare_requested_=true;
        } else {
        last_ret=loco_->SwitchToInternalCtrl(unitree::robot::g1::InternalFsmMode::WALKRUN);
        {std::lock_guard<std::mutex> lock(mutex_);
         authorized=contract_.preparation_allowed(now_s())&&request_stamp_==generation;}
        if(last_ret==0&&authorized)last_ret=loco_->Start();
        if(last_ret!=0) {std::lock_guard<std::mutex> lock(mutex_);contract_.arm(false);}
        RCLCPP_INFO(get_logger(),"Native WALKRUN preparation result=%d",last_ret);
        fsm_ok=mode_ok=false;native_ready=false;next_query=0.;
        }
      }
      g1_bridge::Decision decision;
      double command_age,health_age;
      {std::lock_guard<std::mutex> lock(mutex_);
        decision=contract_.sample_terminal(now_s(),native_ready&&!recovery.active()&&!recovery.failed(),terminal_phase_,
          terminal_raw_wz_,terminal_raw_time_,std::min(contract_.max_wz,terminal_max_wz_));
        command_age=std::min(999.,now_s()-contract_.cmd_time);
        health_age=std::min(999.,now_s()-contract_.health_time);
      }
      auto v=decision.velocity;v[2]*=yaw_sign_;
      bool nonzero=v[0]!=0.||v[2]!=0.;
      if(!dry_&&recovery.active()) {
        // Never replay a nonzero command to test connectivity.
        v={};owned=false;
        decision.reason="sdk_timeout_recovering";
        if(recovery.expired(now_s()))recovery.fail();
        else if(recovery.probe_due(now_s())) {
          last_ret=loco_->SetVelocity(0.f,0.f,0.f,float(duration_));
          recovery.record_zero(last_ret,now_s());
        }
        bool navigation_ready;
        {std::lock_guard<std::mutex> lock(mutex_);
         const bool idle=contract_.enabled&&!has_request_&&!contract_.goal_ready;
         const bool live_health=contract_.healthy&&now_s()-contract_.health_time<=contract_.health_timeout;
         // A cancelled/completed mission may recover the channel to idle, but
         // can never gain goal authorization from successful ZERO probes.
         navigation_ready=(contract_.preparation_allowed(now_s())||(idle&&live_health))&&
           now_s()-contract_.cmd_time<=contract_.timeout&&
           recovery_generation==enable_generation_&&!conflict;}
        if(recovery.ready(now_s(),native_ready,navigation_ready)) {
          recovery.complete();
          {std::lock_guard<std::mutex> lock(mutex_);
           // Require a newly sampled command after successful recovery. The
           // turn bypass also needs a new raw angular sample.
           contract_.ready_after=now_s();contract_.cmd_time=-1e30;
           terminal_raw_time_=-1e30;}
          decision.reason="sdk_timeout_recovered";
          RCLCPP_INFO(get_logger(),"SDK timeout recovered: 3 ZERO acknowledgements, native state and navigation valid; waiting for fresh command");
        }
      } else if(!dry_&&!recovery.failed()&&(nonzero||owned)) {
        last_ret=loco_->SetVelocity(float(v[0]),0.f,float(v[2]),float(duration_));
        owned=nonzero;
        if(last_ret!=0) {
          // The finite SDK duration also stops a command if the response/link is lost.
          const bool recovering=recovery.begin(last_ret,now_s());
          const int zero_ret=loco_->SetVelocity(0.f,0.f,0.f,float(duration_));owned=false;
          v={};
          if(recovering&&recovery.record_zero(zero_ret,now_s())) {
            fsm_ok=mode_ok=native_ready=false;next_query=0.;
            {std::lock_guard<std::mutex> lock(mutex_);contract_.ready_after=now_s();}
            decision.reason="sdk_timeout_recovering";
            RCLCPP_WARN(get_logger(),"SDK response timeout (%d), ZERO result=%d; holding ZERO and retrying for at most 10s",last_ret,zero_ret);
          } else {
            std::lock_guard<std::mutex> lock(mutex_);contract_.arm(false);
            decision.reason="sdk_error";
            RCLCPP_ERROR(get_logger(),"SDK velocity call failed: %d, ZERO result=%d; motion disabled",last_ret,zero_ret);
          }
        }
      }
      if(recovery.failed()) {
        std::lock_guard<std::mutex> lock(mutex_);contract_.arm(false);v={};
        if(!recovery_failed_reported)
          RCLCPP_ERROR(get_logger(),"SDK recovery failed or timeout burst limit reached; motion disabled");
        recovery_failed_reported=true;
        decision.reason="sdk_error";
      }
      Twist cmd;cmd.linear.x=v[0];cmd.angular.z=v[2];
      if(!rclcpp::ok())break;
      try {command_pub_->publish(cmd);} catch(const rclcpp::exceptions::RCLError &) {break;}
      if(now_s()>=next_status||decision.reason!=last_reason) {
        std_msgs::msg::String s;
        s.data=(dry_?"dry_run":"live")+std::string(" ")+decision.reason+
          " fsm="+std::to_string(fsm)+" mode="+std::to_string(mode)+" sdk_ret="+std::to_string(last_ret);
        s.data+=" cmd_age="+std::to_string(command_age)+" health_age="+std::to_string(health_age);
        try {status_pub_->publish(s);} catch(const rclcpp::exceptions::RCLError &) {break;}
        last_reason=decision.reason;next_status=now_s()+1.;
      }
      std::this_thread::sleep_until(start+100ms);
    }
    if(loco_&&owned) {loco_->SetVelocity(0.f,0.f,0.f,float(duration_));}
  }
  rclcpp::Subscription<std_msgs::msg::Empty>::SharedPtr cancel_sub_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr controller_state_sub_;
  rclcpp::Subscription<Twist>::SharedPtr terminal_command_sub_;
  int terminal_phase_=0;
  double terminal_raw_wz_=0.,terminal_raw_time_=-1e30;
  std::mutex mutex_;g1_bridge::Contract contract_;bool dry_,prepare_;double duration_,yaw_sign_,terminal_max_wz_;
  std::string input_;bool has_request_=false,prepare_requested_=false;
  g1_bridge::RequestEpoch request_epoch_;
  uint64_t enable_generation_=0;
  Pose requested_;int64_t request_stamp_=0,confirmed_stamp_=0,plan_stamp_=0,enable_ros_stamp_=0;
  double plan_receipt_=0.;
  std::atomic<bool> running_{true};std::thread worker_;
  std::unique_ptr<unitree::robot::g1::LocoClient> loco_;
  tf2_ros::Buffer buffer_;tf2_ros::TransformListener listener_;
  rclcpp::Publisher<Twist>::SharedPtr command_pub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr status_pub_;
  rclcpp::Subscription<Twist>::SharedPtr command_sub_;
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr health_sub_;
  rclcpp::Subscription<Pose>::SharedPtr goal_sub_,target_sub_,reached_sub_;
  rclcpp::Subscription<nav_msgs::msg::Path>::SharedPtr plan_sub_,mission_sub_;
  rclcpp::Service<std_srvs::srv::SetBool>::SharedPtr enable_;
};
int main(int argc,char **argv) {
#ifdef G1_BRIDGE_FAULT_TEST
  const char *domain=std::getenv("ROS_DOMAIN_ID"),*local=std::getenv("ROS_LOCALHOST_ONLY");
  if(!domain||std::atoi(domain)<1||std::atoi(domain)>232||!local||std::string(local)!="1") {
    std::cerr<<"Fake SDK test requires an isolated localhost ROS domain"<<std::endl;return 2;
  }
  std::cerr<<"SIMULATED SDK FAULT TEST: no robot SDK or hardware transport"<<std::endl;
#endif
  const char *rmw=std::getenv("RMW_IMPLEMENTATION");
  if(rmw&&std::string(rmw)!="rmw_fastrtps_cpp") {
    std::cerr<<"This SDK bridge requires rmw_fastrtps_cpp to isolate the SDK DDS ABI"<<std::endl;
    return 2;
  }
  rclcpp::init(argc,argv);
  try {auto node=std::make_shared<Bridge>();rclcpp::spin(node);node.reset();}
  catch(const std::exception &e) {std::cerr<<e.what()<<std::endl;rclcpp::shutdown();return 1;}
  rclcpp::shutdown();return 0;
}
