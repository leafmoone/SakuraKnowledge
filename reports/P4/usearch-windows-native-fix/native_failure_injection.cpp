// Failure injection into actual header method: simulated API failures, not 32-bit execution.
#include <windows.h>
#include <cstdio>
#include <cstdint>
static int mode=0, closed=0, maps=0, views=0;
BOOL mock_size(HANDLE,LARGE_INTEGER* value) {
 if(mode==1)return FALSE;
 value->QuadPart=mode==2?-1:127; return TRUE;
}
HANDLE mock_mapping(HANDLE,LPSECURITY_ATTRIBUTES,DWORD,DWORD,DWORD,LPCSTR) {
 ++maps; return mode==3?nullptr:reinterpret_cast<HANDLE>(2);
}
LPVOID mock_view(HANDLE,DWORD,DWORD,DWORD,SIZE_T) {++views; return nullptr;}
BOOL mock_close(HANDLE) {++closed;return TRUE;}
#define GetFileSizeEx mock_size
#define CreateFileMappingA mock_mapping
#define MapViewOfFile mock_view
#define CloseHandle mock_close
#include <usearch/index.hpp>
#undef GetFileSizeEx
#undef CreateFileMappingA
#undef MapViewOfFile
#undef CloseHandle
int main(int argc,char**argv) {
 if(argc!=2)return 2;
 for(mode=1;mode<=4;++mode) {
  closed=maps=views=0;
  unum::usearch::memory_mapped_file_t file(argv[1]);
  auto r=file.open_if_not();
  if(r)return 3;
  r.error.release();
  int expected=mode==4?2:1;
  if(closed!=expected || maps!=(mode<3?0:1) || views!=(mode==4?1:0))return 4;
 }
 std::puts("SIMULATED_GETSIZE_FAIL_NEGATIVE_MAPPING_FAIL_VIEW_FAIL_CLOSE_ORDER=PASS");
 return 0;
}
