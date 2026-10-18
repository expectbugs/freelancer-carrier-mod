// Lint fixture (review r3 N1): engine-free code must not include a header from a tests/ dir, which the lint
// skips; this one would pull <windows.h> into the win32 logic library.
#pragma once
#include "tests/leak_helper.hpp"
