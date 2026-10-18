// Lint fixture: a Windows-only header hidden behind #ifdef must still be rejected.
#pragma once
#ifdef _WIN32
#include <synchapi.h>
#endif
