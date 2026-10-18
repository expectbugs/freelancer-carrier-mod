# cmake/LogicIncludeLint.cmake: fail the build unless every #include in engine-free code is allowed.
# Run as a script:
#   cmake -DFLMOD_LINT_DIR=<dir> [-DFLMOD_LINT_SRC_ROOT=<src dir>] [-DFLMOD_LINT_STAMP=<file>] -P cmake/LogicIncludeLint.cmake
#
# Allowlist (anything else is rejected, including Windows-only headers behind #ifdef _WIN32):
#   <...>  C++23 standard library headers, the C compatibility headers (<cstdio>, <stdio.h>, ...),
#          and <nlohmann/...> (the project's JSON library)
#   "..."  a file that exists relative to the including file or to FLMOD_LINT_SRC_ROOT, and lies under
#          src/logic/ or src/contracts/
# Files under any tests/ directory are not linted (host-only doctest code; see cmake/LogicLintFiles.cmake).
# The host header check (tests/host/LogicHeaderCheck.cmake) catches the same class of problem by compilation;
# this lint also runs in win32 builds, where <windows.h> would otherwise compile fine.

if(NOT FLMOD_LINT_DIR)
  message(FATAL_ERROR "LogicIncludeLint: pass -DFLMOD_LINT_DIR=<dir>")
endif()
if(NOT FLMOD_LINT_SRC_ROOT)
  get_filename_component(FLMOD_LINT_SRC_ROOT "${FLMOD_LINT_DIR}/.." ABSOLUTE)
endif()

set(_std_headers
  # C++ library (C++23)
  algorithm any array atomic barrier bit bitset charconv chrono codecvt compare complex concepts
  condition_variable coroutine deque exception execution expected filesystem flat_map flat_set format
  forward_list fstream functional future generator initializer_list iomanip ios iosfwd iostream istream
  iterator latch limits list locale map mdspan memory memory_resource mutex new numbers numeric optional
  ostream print queue random ranges ratio regex scoped_allocator semaphore set shared_mutex
  source_location span spanstream sstream stack stacktrace stdexcept stdfloat stop_token streambuf string
  string_view syncstream system_error thread tuple type_traits typeindex typeinfo unordered_map
  unordered_set utility valarray variant vector version
  # C compatibility headers
  cassert cctype cerrno cfenv cfloat cinttypes climits clocale cmath csetjmp csignal cstdarg cstddef
  cstdint cstdio cstdlib cstring ctime cuchar cwchar cwctype
  assert.h ctype.h errno.h fenv.h float.h inttypes.h limits.h locale.h math.h setjmp.h signal.h stdarg.h
  stddef.h stdint.h stdio.h stdlib.h string.h time.h uchar.h wchar.h wctype.h stdatomic.h)

# The file set (extensions, tests/ excluded) is shared with the root CMakeLists.txt: cmake/LogicLintFiles.cmake.
include("${CMAKE_CURRENT_LIST_DIR}/LogicLintFiles.cmake")
flmod_logic_lint_files(_files "${FLMOD_LINT_DIR}")

set(_violations "")
foreach(_f IN LISTS _files)
  get_filename_component(_fdir "${_f}" DIRECTORY)
  file(RELATIVE_PATH _rel "${FLMOD_LINT_DIR}" "${_f}")
  file(STRINGS "${_f}" _lines REGEX "^[ \t]*#[ \t]*include")
  foreach(_line IN LISTS _lines)
    if(_line MATCHES "^[ \t]*#[ \t]*include[ \t]*<([^>]+)>")
      set(_inc "${CMAKE_MATCH_1}")
      if(_inc IN_LIST _std_headers OR _inc MATCHES "^nlohmann/")
        continue()
      endif()
      string(APPEND _violations "  ${_rel}: ${_line}   (<${_inc}> is not a standard or allowed header)\n")
    elseif(_line MATCHES "^[ \t]*#[ \t]*include[ \t]*\"([^\"]+)\"")
      set(_inc "${CMAKE_MATCH_1}")
      set(_resolved "")
      foreach(_base IN ITEMS "${_fdir}" "${FLMOD_LINT_SRC_ROOT}")
        if(NOT _resolved AND EXISTS "${_base}/${_inc}" AND NOT IS_DIRECTORY "${_base}/${_inc}")
          get_filename_component(_resolved "${_base}/${_inc}" REALPATH)
        endif()
      endforeach()
      set(_ok FALSE)
      if(_resolved)
        get_filename_component(_src_real "${FLMOD_LINT_SRC_ROOT}" REALPATH)
        get_filename_component(_lint_real "${FLMOD_LINT_DIR}" REALPATH)
        foreach(_allowed IN ITEMS "${_src_real}/logic" "${_src_real}/contracts" "${_lint_real}")
          cmake_path(IS_PREFIX _allowed "${_resolved}" NORMALIZE _is_under)
          if(_is_under)
            set(_ok TRUE)
          endif()
        endforeach()
      endif()
      if(_ok)
        continue()
      endif()
      if(_resolved)
        string(APPEND _violations "  ${_rel}: ${_line}   (resolves outside src/logic and src/contracts)\n")
      else()
        string(APPEND _violations "  ${_rel}: ${_line}   (not found next to the file or under ${FLMOD_LINT_SRC_ROOT})\n")
      endif()
    else()
      string(APPEND _violations "  ${_rel}: ${_line}   (unrecognised #include form)\n")
    endif()
  endforeach()
endforeach()

if(_violations)
  message(FATAL_ERROR
    "src/logic must stay engine-free: only standard headers, <nlohmann/...> and project headers under "
    "src/logic or src/contracts (toolchain/README.md).\n"
    "Forbidden includes found under ${FLMOD_LINT_DIR}:\n${_violations}")
endif()

list(LENGTH _files _n)
message(STATUS "LogicIncludeLint: ${_n} files under ${FLMOD_LINT_DIR} are engine-free")
if(FLMOD_LINT_STAMP)
  file(WRITE "${FLMOD_LINT_STAMP}" "ok ${_n}\n")
endif()
