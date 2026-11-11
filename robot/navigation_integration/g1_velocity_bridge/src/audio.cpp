// Audio uses its own SDK client. No locomotion API is instantiated here.
#include <g1_velocity_bridge/audio_contract.hpp>
#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/string.hpp>
#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/g1/audio/g1_audio_client.hpp>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <memory>
#include <iostream>
#include <mutex>
#include <optional>
#include <thread>

using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;
using namespace std::chrono_literals;
class AudioBridge : public rclcpp::Node {
  struct Job { std::string id, file; int64_t token; uint64_t generation; };
 public:
  AudioBridge() : Node("nav_waypoint_audio") {
    dry_ = declare_parameter("dry_run", true);
    network_ = declare_parameter("network_interface", std::string("eth0"));
    publisher_ = create_publisher<std_msgs::msg::String>("/nav3d/audio/status", rclcpp::QoS(10).transient_local());
    reference_ = create_publisher<std_msgs::msg::String>("/nav3d/audio/reference", 30);
    subscriber_ = create_subscription<std_msgs::msg::String>("/nav3d/audio/request", 10,
      [this](const std_msgs::msg::String::SharedPtr msg) { request(msg->data); });
    timer_ = create_wall_timer(500ms, [this] { emit("ready", "", 0); });
    worker_ = std::thread([this] { run(); });
    emit("ready", "", 0);
    RCLCPP_INFO(get_logger(), "%s waypoint audio -> G1 speaker; idle until a play request", dry_ ? "DRY RUN" : "LIVE");
  }
  ~AudioBridge() override {
    { std::lock_guard<std::mutex> lock(mutex_); alive_ = false; ++generation_; }
    cv_.notify_all();
    if (worker_.joinable()) worker_.join();
  }
 private:
  void emit(const std::string& event, const std::string& id, int64_t token,
            const std::string& message = "", double duration = 0.) {
    if (!rclcpp::ok()) return;
    std_msgs::msg::String msg;
    msg.data = Json{{"event", event}, {"request_id", id}, {"token", token},
      {"message", message}, {"duration", duration}, {"dry_run", dry_}}.dump();
    try { publisher_->publish(msg); } catch (const std::exception&) {}
  }
  void request(const std::string& data) {
    std::string id; int64_t token = 0;
    try {
      const auto req = Json::parse(data);
      id = req.value("request_id", std::string()); token = req.value("token", int64_t(0));
      const auto action = req.at("action").get<std::string>();
      if (action == "stop") {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!busy_ || (!id.empty() && id != active_id_)) return;
        ++generation_;
        if (pending_) { emit("stopped", pending_->id, pending_->token); pending_.reset(); busy_ = false; active_id_.clear(); }
        cv_.notify_all(); return;
      }
      if (action != "play" || id.empty() || id.size() > 128 || token < 0)
        throw std::runtime_error("Invalid audio request");
      const auto file = req.at("file").get<std::string>();
      if (file.empty() || file.size() > 4096 || file.find('\0') != std::string::npos)
        throw std::runtime_error("Invalid audio filename");
      std::lock_guard<std::mutex> lock(mutex_);
      if (busy_) { emit("error", id, token, "Audio player is busy"); return; }
      busy_ = true; active_id_ = id;
      pending_ = Job{id, file, token, generation_}; cv_.notify_all();
    } catch (const std::exception& exc) { emit("error", id, token, exc.what()); }
  }
  bool cancelled(const Job& job) {
    std::lock_guard<std::mutex> lock(mutex_);
    return !alive_ || generation_ != job.generation;
  }
  bool wait_until(const Job& job, Clock::time_point deadline) {
    std::unique_lock<std::mutex> lock(mutex_);
    cv_.wait_until(lock, deadline, [&] { return !alive_ || generation_ != job.generation; });
    return alive_ && generation_ == job.generation;
  }
  void stop_speaker() {
    if (client_) { try { client_->PlayStop("g1_nav_waypoints"); } catch (...) {} }
  }
  void reference(const Job& job, size_t offset, size_t count, Clock::time_point start) {
    std_msgs::msg::String msg;
    msg.data = Json{{"request_id", job.id}, {"file", job.file},
      {"sample_offset", offset/2}, {"sample_count", count/2},
      {"start_ns", std::chrono::duration_cast<std::chrono::nanoseconds>(start.time_since_epoch()).count()}}.dump();
    reference_->publish(msg);
  }
  void play(const Job& job) {
    const auto wav = g1_velocity_bridge::read_audio_wave(job.file);
    if (cancelled(job)) { emit("stopped", job.id, job.token); return; }
    if (!dry_ && !client_) {
      unitree::robot::ChannelFactory::Instance()->Init(0, network_);
      client_ = std::make_unique<unitree::robot::g1::AudioClient>();
      client_->Init(); client_->SetTimeout(.5f);
    }
    if (!dry_) {
      uint8_t volume = 0;
      const auto ret = client_->GetVolume(volume);
      if (ret != 0) throw std::runtime_error("G1 audio service returned " + std::to_string(ret));
      if (volume == 0) throw std::runtime_error("G1 speaker volume is zero; raise robot volume before playback");
    }
    emit("playing", job.id, job.token, "", wav.duration());
    auto end = Clock::now();
    if (dry_) {
      reference(job, 0, wav.pcm.size(), end);
      end += std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(wav.duration()));
    } else {
      // Keep a bounded PCM buffer; an API return only acknowledges
      // receipt. Completion waits for all sample durations and a drain margin.
      for (size_t offset = 0; offset < wav.pcm.size();) {
        if (cancelled(job)) break;
        const auto count = std::min<size_t>(64000, wav.pcm.size()-offset);
        std::vector<uint8_t> chunk(wav.pcm.begin()+offset, wav.pcm.begin()+offset+count);
        const auto start = std::max(end, Clock::now());
        // Send reference before the RPC so microphone frames cannot overtake it.
        reference(job, offset, count, start);
        const auto ret = client_->PlayStream("g1_nav_waypoints", job.id, chunk);
        if (ret != 0) throw std::runtime_error("G1 audio SDK returned " + std::to_string(ret));
        end = start + std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(double(count)/32000.));
        offset += count;
        if (offset < wav.pcm.size() && !wait_until(job, end-1s)) break;
      }
    }
    if (!wait_until(job, end+500ms)) {
      stop_speaker(); emit("stopped", job.id, job.token); return;
    }
    stop_speaker(); emit("finished", job.id, job.token);
  }
  void run() {
    for (;;) {
      std::optional<Job> job;
      { std::unique_lock<std::mutex> lock(mutex_);
        cv_.wait(lock, [&] { return !alive_ || pending_.has_value(); });
        if (!alive_) break;
        job = pending_; pending_.reset();
      }
      try { play(*job); }
      catch (const std::exception& exc) { stop_speaker(); emit("error", job->id, job->token, exc.what()); }
      { std::lock_guard<std::mutex> lock(mutex_); busy_ = false; active_id_.clear(); }
    }
    stop_speaker();
  }
  bool dry_, alive_ = true, busy_ = false;
  uint64_t generation_ = 0;
  std::string network_, active_id_;
  std::mutex mutex_; std::condition_variable cv_; std::optional<Job> pending_;
  std::thread worker_;
  std::unique_ptr<unitree::robot::g1::AudioClient> client_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr publisher_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr reference_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr subscriber_;
  rclcpp::TimerBase::SharedPtr timer_;
};
int main(int argc, char** argv) {
  // Keep ROS middleware separate from the SDK's Cyclone DDS ABI.
  setenv("RMW_IMPLEMENTATION", "rmw_fastrtps_cpp", 1);
  rclcpp::init(argc, argv);
  try { auto node = std::make_shared<AudioBridge>(); rclcpp::spin(node); node.reset(); }
  catch (const std::exception& exc) { std::cerr << exc.what() << std::endl; rclcpp::shutdown(); return 1; }
  rclcpp::shutdown(); return 0;
}
