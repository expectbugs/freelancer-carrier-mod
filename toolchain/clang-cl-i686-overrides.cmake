# Loaded through CMAKE_USER_MAKE_RULES_OVERRIDE (see clang-cl-i686.cmake), after CMake's Windows-MSVC
# platform module has added its defaults. Replace the default /EHsc with /EHa (asynchronous EH, as
# FLUF builds; required to catch SEH and Freelancer's exceptions).
string(REGEX REPLACE "/EH[a-z]+" "" CMAKE_CXX_FLAGS_INIT "${CMAKE_CXX_FLAGS_INIT}")
string(APPEND CMAKE_CXX_FLAGS_INIT " /EHa")
