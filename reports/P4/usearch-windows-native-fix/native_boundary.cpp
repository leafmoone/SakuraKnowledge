// Actual upstream native methods; sparse metadata fixtures are NOT valid ANN packs.
#include <usearch/index_dense.hpp>
#include <iostream>
int main(int argc,char**argv) {
 if(argc!=3)return 2;
 if(std::string(argv[1])=="metadata") {
  auto r=unum::usearch::index_dense_metadata_from_path(argv[2]);
  if(!r){std::cout<<"FAIL "<<r.error.what()<<"\n";r.error.release();return 1;}
  std::cout<<"PASS dims="<<std::size_t(r.head.dimensions)<<" u64="<<r.config.use_64_bit_dimensions<<"\n";
  return 0;
 }
 unum::usearch::memory_mapped_file_t f(argv[2]);
 auto r=f.open_if_not();
 if(!r){std::cout<<"FAIL "<<r.error.what()<<"\n";r.error.release();return 1;}
 std::cout<<"PASS length="<<f.size();
 if(f.size())std::cout<<" first="<<int((unsigned char)f.data()[0])<<" last="<<int((unsigned char)f.data()[f.size()-1]);
 std::cout<<"\n";
 return 0;
}
