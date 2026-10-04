// Actual metadata function with simulated signed tell failure (not real 32-bit).
#include <cstdio>
#include <cstdint>
static long long failed_tell(std::FILE*) { return -1; }
#define _ftelli64 failed_tell
#include <usearch/index_dense.hpp>
#undef _ftelli64
#include <iostream>
int main(int argc,char**argv) {
 if(argc!=2)return 2;
 auto r=unum::usearch::index_dense_metadata_from_path(argv[1]);
 if(r)return 3;
 std::string message=r.error.what();r.error.release();
 if(message!="Can't infer file size")return 4;
 std::cout<<"SIMULATED_METADATA_TELL_NEGATIVE_REJECT=PASS\n";
 return 0;
}
