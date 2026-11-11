#pragma once
// Only included by nav_velocity_bridge_fault_test, never the installed bridge.
// Deliberately supplies no hardware/DDS implementation.
#include <cstdlib>
#include <iostream>
#include <string>
namespace unitree {namespace robot {
class ChannelFactory {
 public:
  static ChannelFactory* Instance() {static ChannelFactory f;return &f;}
  void Init(int,const std::string&) {}
};
namespace g1 {
enum class InternalFsmMode {WALKRUN};
class LocoClient {
 public:
  void Init() {} void SetTimeout(float) {}
  int GetFsmId(int& value) {value=501;return 0;}
  int GetFsmMode(int& value) {value=0;return 0;}
  int SwitchToInternalCtrl(InternalFsmMode) {return 0;}
  int Start() {return 0;}
  int SetVelocity(float vx,float,float wz,float) {
    const char* value=std::getenv("G1_FAKE_SDK_SCENARIO");
    const std::string scenario=value?value:"recover";
    if(vx!=0.f||wz!=0.f) {
      if(++nonzero_==3) {
        triggered_=true;
        std::cerr<<"FAKE_SDK_FAULT "<<scenario<<std::endl;
        return scenario=="reject"?7301:3104;
      }
    } else if(triggered_) {
      ++zeros_;
      if(scenario=="persistent"||zeros_<=2)return 3104;
    }
    return 0;
  }
 private:
  int nonzero_=0,zeros_=0;bool triggered_=false;
};
}}}
