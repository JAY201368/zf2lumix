// Experimental RawFormat 8 encoder, limited to lossless delta coding and
// identity linearization. Format interpretation informed by LibRaw's
// src/decoders/pana8.cpp and src/metadata/tiff.cpp (Alex Tutubalin/LibRaw).
// This independently written encoder preserves the template's Huffman table.
#include <array>
#include <cstdint>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <vector>

struct Bits {
  std::vector<uint8_t> bytes;
  uint64_t count = 0;
  void put(uint32_t value, unsigned n) {
    for (unsigned k = n; k > 0; --k) {
      if ((count & 7) == 0) bytes.push_back(0);
      bytes.back() |= ((value >> (k - 1)) & 1) << (count & 7);
      ++count;
    }
  }
};

#ifdef _WIN32
int wmain(int argc, wchar_t** argv) {
#else
int main(int argc, char** argv) {
#endif
  try {
    if (argc != 9) throw std::runtime_error("usage: encode mosaic.u16 width height left stripe_width huff.txt output.bin output.bits");
    int w = std::stoi(argv[2]), h = std::stoi(argv[3]);
    int left = std::stoi(argv[4]), sw = std::stoi(argv[5]);
    if (w<=0 || h<=0 || h%2 || sw<=0 || sw%2 || left<0 || left+sw>w)
      throw std::runtime_error("invalid geometry");
    std::vector<uint16_t> raw(size_t(w)*h);
    std::ifstream input(std::filesystem::path(argv[1]), std::ios::binary);
    input.read(reinterpret_cast<char*>(raw.data()), raw.size()*2);
    if (!input || input.peek()!=EOF) throw std::runtime_error("mosaic size mismatch");
    std::array<unsigned,17> lengths{}, codes{};
    std::ifstream tables{std::filesystem::path(argv[6])};
    for (int k=0;k<=16;++k) {
      tables>>lengths[k]>>codes[k];
      if (!tables || lengths[k]<1 || lengths[k]>16 || codes[k]>=(1u<<lengths[k]))
        throw std::runtime_error("invalid Huffman table");
    }
    Bits out;
    std::array<int,4> row_start{}; // source sample has four zero initial values
    std::array<uint64_t,17> counts{};
    for (int y=0;y<h;y+=2) {
      auto pred=row_start;
      for (int x=left;x<left+sw;x+=2) {
        // Encoded order is TL, BL, TR, BR; each lane predicts horizontally.
        std::array<int,4> values{raw[size_t(y)*w+x],raw[size_t(y+1)*w+x],
                                 raw[size_t(y)*w+x+1],raw[size_t(y+1)*w+x+1]};
        for (int c=0;c<4;++c) {
          int delta=values[c]-pred[c];
          unsigned absd=unsigned(delta<0 ? -delta:delta), category=0;
          for(unsigned n=absd;n;n>>=1)++category;
          out.put(codes[category],lengths[category]);
          if(category)out.put(delta<0 ? unsigned(delta+int((1u<<category)-1)):unsigned(delta),category);
          ++counts[category];
        }
        pred=values;
        if (x==left)row_start=values;
      }
    }
    // Payload is byte-LSB-first. The bit count excludes storage padding.
    // Keep a full zero lookahead word for readers that fetch 64-bit windows.
    while(out.bytes.size()%8)out.bytes.push_back(0);
    out.bytes.resize(out.bytes.size()+8,0);
    std::ofstream file(std::filesystem::path(argv[7]),std::ios::binary);
    file.write(reinterpret_cast<char*>(out.bytes.data()),out.bytes.size());
    if(!file)throw std::runtime_error("output write failed");
    std::ofstream(std::filesystem::path(argv[8]))<<out.count<<'\n';
    std::cout<<"encoded_samples="<<uint64_t(sw)*h<<" bits="<<out.count<<" bytes="<<out.bytes.size()<<'\n';
  }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
