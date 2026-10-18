// Negative probe (not part of any default build): engine-free code that includes <windows.h> must
// fail to compile on the host. ctest logic_rejects_windows_h_compile builds this and expects failure.
#include <windows.h>

int flmod_negative_probe() { return 0; }
