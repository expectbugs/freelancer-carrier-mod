# cmake/LogicLintFiles.cmake: the single definition of "the src/logic files the engine-free rule applies to".
#
# Included by the root CMakeLists.txt (the lint stamp's DEPENDS and the standalone-header check) and by
# cmake/LogicIncludeLint.cmake (what the lint scans), so the build and the lint always see the same set.
#
# Files under any tests/ directory (matched on the path relative to the scanned dir) are NOT part of the set.
# They are host-only doctest code: the root CMakeLists.txt compiles src/**/tests/**/*.cpp into host_tests on Linux
# and never into `logic` or a win32 binary. They legitimately include <doctest/doctest.h> and test helpers, and a
# Windows header there already fails the host compile. Allowing only <doctest/...> under tests/ was the other
# option; it was rejected because test code also needs quoted helpers from tests/host/, which the lint would have
# to special-case too, while the rule protects nothing there (review r2 F1, toolchain/NOTES.md).

set(FLMOD_LOGIC_LINT_EXTS h hpp hh inl ipp c cpp cc)   # what the lint reads
set(FLMOD_LOGIC_HEADER_EXTS h hpp inl)                 # what the standalone-header check compiles

# flmod_logic_lint_files(<out_var> <dir> [HEADERS_ONLY] [CONFIGURE_DEPENDS])
#   Absolute paths of the files under <dir> with the lint (or, with HEADERS_ONLY, the header-check) extensions,
#   minus everything under a tests/ directory, sorted. CONFIGURE_DEPENDS re-globs at build time (configure mode
#   only; script mode (-P) must not pass it).
function(flmod_logic_lint_files out dir)
  cmake_parse_arguments(_a "HEADERS_ONLY;CONFIGURE_DEPENDS" "" "" ${ARGN})
  if(_a_HEADERS_ONLY)
    set(_exts ${FLMOD_LOGIC_HEADER_EXTS})
  else()
    set(_exts ${FLMOD_LOGIC_LINT_EXTS})
  endif()
  set(_globs "")
  foreach(_e IN LISTS _exts)
    list(APPEND _globs "${dir}/*.${_e}")
  endforeach()
  if(_a_CONFIGURE_DEPENDS)
    file(GLOB_RECURSE _rel RELATIVE "${dir}" LIST_DIRECTORIES false CONFIGURE_DEPENDS ${_globs})
  else()
    file(GLOB_RECURSE _rel RELATIVE "${dir}" LIST_DIRECTORIES false ${_globs})
  endif()
  list(FILTER _rel EXCLUDE REGEX "(^|/)tests/")
  list(SORT _rel)
  list(TRANSFORM _rel PREPEND "${dir}/")
  set(${out} "${_rel}" PARENT_SCOPE)
endfunction()
