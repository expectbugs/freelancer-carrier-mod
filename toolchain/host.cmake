# toolchain/host.cmake: native Linux build of the engine-free code (src/logic) and host tests.
# clang++ 22, C++23. Sanitizers are switched on by FLMOD_SANITIZE (the host-asan preset).

set(FLMOD_LLVM_BIN "/usr/lib/llvm/22/bin" CACHE PATH "LLVM 22 bin directory")

set(CMAKE_C_COMPILER   "${FLMOD_LLVM_BIN}/clang")
set(CMAKE_CXX_COMPILER "${FLMOD_LLVM_BIN}/clang++")
set(CMAKE_AR     "${FLMOD_LLVM_BIN}/llvm-ar"     CACHE FILEPATH "" FORCE)
set(CMAKE_RANLIB "${FLMOD_LLVM_BIN}/llvm-ranlib" CACHE FILEPATH "" FORCE)

set(CMAKE_C_FLAGS_INIT   "-Wall -Wextra -Werror=return-type")
set(CMAKE_CXX_FLAGS_INIT "-Wall -Wextra -Werror=return-type")
