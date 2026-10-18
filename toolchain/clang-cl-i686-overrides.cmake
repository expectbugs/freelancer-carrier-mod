# Loaded through CMAKE_USER_MAKE_RULES_OVERRIDE (see clang-cl-i686.cmake), after CMake's Windows-MSVC
# platform module has added its defaults. Replace the default /EHsc with /EHa (asynchronous EH, as FLUF
# builds; needed for __try/__except around faulting instructions in the same function). catch(...) still
# does not reliably catch SEH exceptions: toolchain/ABI.md §6.
string(REGEX REPLACE "/EH[a-z]+" "" CMAKE_CXX_FLAGS_INIT "${CMAKE_CXX_FLAGS_INIT}")
string(APPEND CMAKE_CXX_FLAGS_INIT " /EHa")
