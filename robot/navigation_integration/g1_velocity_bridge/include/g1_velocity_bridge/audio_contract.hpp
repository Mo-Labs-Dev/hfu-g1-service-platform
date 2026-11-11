#pragma once
#include <cstdint>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace g1_velocity_bridge {
struct AudioWave {
  std::vector<uint8_t> pcm;
  double duration() const { return double(pcm.size()) / 32000.; }
};
inline uint16_t u16(const uint8_t* p) { return uint16_t(p[0]) | uint16_t(p[1]) << 8; }
inline uint32_t u32(const uint8_t* p) {
  return uint32_t(p[0]) | uint32_t(p[1]) << 8 | uint32_t(p[2]) << 16 | uint32_t(p[3]) << 24;
}
inline AudioWave read_audio_wave(const std::string& filename) {
  std::ifstream in(filename, std::ios::binary);
  uint8_t head[12];
  if (!in.read(reinterpret_cast<char*>(head), 12) || std::string(reinterpret_cast<char*>(head), 4) != "RIFF" ||
      std::string(reinterpret_cast<char*>(head+8), 4) != "WAVE")
    throw std::runtime_error("Audio must be a complete PCM WAV file");
  bool format = false;
  AudioWave result;
  uint8_t block[8];
  while (in.read(reinterpret_cast<char*>(block), 8)) {
    const auto tag = std::string(reinterpret_cast<char*>(block), 4);
    const auto size = u32(block+4);
    if (size > 50*1024*1024) throw std::runtime_error("Invalid WAV chunk size");
    if (tag == "fmt ") {
      if (size < 16) throw std::runtime_error("Invalid WAV format header");
      uint8_t fmt[16];
      if (!in.read(reinterpret_cast<char*>(fmt), 16)) throw std::runtime_error("Truncated WAV format");
      if (u16(fmt) != 1 || u16(fmt+2) != 1 || u32(fmt+4) != 16000 ||
          u32(fmt+8) != 32000 || u16(fmt+12) != 2 || u16(fmt+14) != 16)
        throw std::runtime_error("Audio requires 16 kHz mono signed 16-bit PCM");
      format = true;
      in.seekg(size-16, std::ios::cur);
    } else if (tag == "data") {
      if (!result.pcm.empty() || size == 0 || size > 32000*600 || size%2)
        throw std::runtime_error("Audio must be non-empty and at most 10 minutes");
      result.pcm.resize(size);
      if (!in.read(reinterpret_cast<char*>(result.pcm.data()), size)) throw std::runtime_error("Truncated audio samples");
    } else {
      in.seekg(size, std::ios::cur);
    }
    if (size%2) in.seekg(1, std::ios::cur);
  }
  if (!format || result.pcm.empty()) throw std::runtime_error("WAV format or samples missing");
  return result;
}
}
