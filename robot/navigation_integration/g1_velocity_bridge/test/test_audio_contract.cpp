#include <g1_velocity_bridge/audio_contract.hpp>
#include <cassert>
#include <filesystem>
#include <iostream>
#include <unistd.h>

static void put16(std::ofstream& f, uint16_t n) { char b[] = {char(n), char(n>>8)}; f.write(b,2); }
static void put32(std::ofstream& f, uint32_t n) { char b[] = {char(n),char(n>>8),char(n>>16),char(n>>24)}; f.write(b,4); }
static void fixture(const std::string& p, int channels=1, int rate=16000, bool truncate=false, bool metadata=false) {
  std::ofstream f(p,std::ios::binary);
  f.write("RIFF",4);put32(f,36+3200+(metadata?12:0));f.write("WAVEfmt ",8);put32(f,16);
  put16(f,1);put16(f,channels);put32(f,rate);put32(f,rate*channels*2);put16(f,channels*2);put16(f,16);
  if(metadata) { f.write("JUNK",4);put32(f,3);f.write("abc\0",4); }
  f.write("data",4);put32(f,3200);
  std::vector<char> pcm(truncate?3198:3200,0);f.write(pcm.data(),pcm.size());
}
int main() {
  const auto p=(std::filesystem::temp_directory_path()/std::filesystem::path("g1_audio_contract_"+std::to_string(getpid())+".wav")).string();
  fixture(p);assert(g1_velocity_bridge::read_audio_wave(p).duration()==.1);
  fixture(p,1,16000,false,true);assert(g1_velocity_bridge::read_audio_wave(p).pcm.size()==3200);
  for(int variant=0;variant<3;++variant) {
    fixture(p,variant==0?2:1,variant==1?44100:16000,variant==2);
    bool rejected=false;try {g1_velocity_bridge::read_audio_wave(p);}catch(const std::runtime_error&) {rejected=true;}
    assert(rejected);
  }
  std::filesystem::remove(p);
  bool rejected=false;try {g1_velocity_bridge::read_audio_wave(p);}catch(const std::runtime_error&) {rejected=true;}
  assert(rejected);
  std::cout<<"Audio WAV validation contracts passed\n";
}
