# cmake/LogicIncludeLint.cmake: fail the build if engine-free code includes Windows, Freelancer, FLUF
# or hook-library headers. Run as a script:
#   cmake -DFLMOD_LINT_DIR=<dir> [-DFLMOD_LINT_STAMP=<file>] -P cmake/LogicIncludeLint.cmake
# The host header check (logic_header_check) catches the same thing by compilation; this lint also
# runs in win32 builds, where <windows.h> would otherwise compile fine.

if(NOT FLMOD_LINT_DIR)
  message(FATAL_ERROR "LogicIncludeLint: pass -DFLMOD_LINT_DIR=<dir>")
endif()

set(_bad_system_header "^(windows|winsock|winsock2|winuser|windef|winbase|winnt|winreg|wingdi|ws2tcpip|ws2def|mmsystem|psapi|tlhelp32|dbghelp|shlobj|objbase|combaseapi|dsound|ddraw|dxgi|d3d[0-9a-z_]*|d3dx[0-9a-z_]*|minhook)\\.h$")
set(_bad_prefix "^(flcore|fluf|flsdk|imgui|imcp|minhook|freelancersdk)(/|\\.h|\\.hpp|$)")
set(_bad_fluf "^(common|client|server)/fluf")
set(_bad_exact "^(fluf\\.hpp|importfluf\\.hpp|st6\\.h|flcoredefs\\.hpp|flcoreserver\\.h|flcorecommon\\.h)$")

file(GLOB_RECURSE _files LIST_DIRECTORIES false
  "${FLMOD_LINT_DIR}/*.h" "${FLMOD_LINT_DIR}/*.hpp" "${FLMOD_LINT_DIR}/*.hh" "${FLMOD_LINT_DIR}/*.inl"
  "${FLMOD_LINT_DIR}/*.ipp" "${FLMOD_LINT_DIR}/*.c" "${FLMOD_LINT_DIR}/*.cpp" "${FLMOD_LINT_DIR}/*.cc")

set(_violations "")
foreach(_f IN LISTS _files)
  file(STRINGS "${_f}" _lines REGEX "^[ \t]*#[ \t]*include")
  foreach(_line IN LISTS _lines)
    if(NOT _line MATCHES "^[ \t]*#[ \t]*include[ \t]*[<\"]([^>\"]+)[>\"]")
      continue()
    endif()
    string(TOLOWER "${CMAKE_MATCH_1}" _inc)
    string(REPLACE "\\" "/" _inc "${_inc}")
    get_filename_component(_leaf "${_inc}" NAME)
    if(_leaf MATCHES "${_bad_system_header}" OR _inc MATCHES "${_bad_prefix}" OR _inc MATCHES "${_bad_fluf}"
       OR _leaf MATCHES "${_bad_exact}")
      file(RELATIVE_PATH _rel "${FLMOD_LINT_DIR}" "${_f}")
      string(APPEND _violations "  ${_rel}: ${_line}\n")
    endif()
  endforeach()
endforeach()

if(_violations)
  message(FATAL_ERROR
    "src/logic must stay engine-free (no Windows, Freelancer, FLUF or hook headers; toolchain/README.md).\n"
    "Forbidden includes found under ${FLMOD_LINT_DIR}:\n${_violations}")
endif()

list(LENGTH _files _n)
message(STATUS "LogicIncludeLint: ${_n} files under ${FLMOD_LINT_DIR} are engine-free")
if(FLMOD_LINT_STAMP)
  file(WRITE "${FLMOD_LINT_STAMP}" "ok ${_n}\n")
endif()
