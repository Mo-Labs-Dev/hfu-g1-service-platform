#pragma once
#include <cmath>
#include <deque>

namespace g1_bridge {
// Unitree SDK internal_error.hpp: 3104 = UT_ROBOT_ERR_CLIENT_API_TIMEOUT.
// During recovery only ZERO probes are allowed. Three consecutive acknowledged
// probes over >=1 second, fresh native state and live navigation must agree.
// A new mission cannot reset the channel's burst budget; explicit re-enable can.
class SdkRecovery {
 public:
  bool begin(int result, double now) {
    if (failed_ || active_ || result != 3104 || !std::isfinite(now)) return fail();
    while (!events_.empty() && now-events_.front() >= 60.) events_.pop_front();
    if (events_.size() >= 3) return fail();
    events_.push_back(now);
    active_=true;started_=now;next_probe_=now;successes_=0;first_success_=-1.;
    return true;
  }
  bool active() const {return active_;}
  bool failed() const {return failed_;}
  bool fail() {active_=false;failed_=true;return false;}
  bool expired(double now) const {return active_ && (!std::isfinite(now) || now-started_>=10.);}
  bool probe_due(double now) const {return active_ && !expired(now) && now>=next_probe_;}
  bool record_zero(int result, double now) {
    if (!active_ || expired(now)) return fail();
    next_probe_=now+.5;
    if (result==0) {
      if (!successes_) first_success_=now;
      ++successes_;
    } else if (result==3104) {
      successes_=0;first_success_=-1.;
    } else return fail(); // A real API error is never automatically retried.
    return true;
  }
  bool ready(double now, bool native_ready, bool navigation_ready) const {
    return active_ && !expired(now) && successes_>=3 && now-first_success_>=1.
           && native_ready && navigation_ready;
  }
  void complete() {active_=false;}
  unsigned successes() const {return successes_;}
 private:
  bool active_=false,failed_=false;
  double started_=0.,next_probe_=0.,first_success_=-1.;
  unsigned successes_=0;
  std::deque<double> events_;
};
}
