# Freelancer Carrier & Endgame mod: root build.
#
# Presets (CMakePresets.json): host, host-asan (native Linux clang++, src/logic + doctest host tests),
# win32-trackA (FLUF module), win32-trackB (plain dacom DLL). See toolchain/README.md.
#
# Owned by P0-TOOLCHAIN, then ARCH-0 (CONVENTIONS §14). Discovery is by glob, so feature packages
# never edit this file:
#   src/logic/**/*.cpp            -> static library `logic` (host and win32)
#   tests/host/**/*.cpp,
#   src/**/tests/**/*.cpp         -> `host_tests` (doctest, host builds only)
#   src/game/** (outside tests/) is NOT globbed here: the module target that ships it (ARCH-0,
#                                    src/module/<mod>/) globs it and must exclude (^|/)(tests|scenarios)/
#                                    (toolchain/README.md "The src/game rule")
#   The src/logic include lint and header check skip tests/ dirs (cmake/LogicLintFiles.cmake).
#   src/module/*/CMakeLists.txt,
#   spikes/*/CMakeLists.txt,
#   harness/devbridge/CMakeLists.txt  -> add_subdirectory (each guards itself with flmod_track_only /
#                                        flmod_win32_only / flmod_host_only)
cmake_minimum_required(VERSION 3.29)
project(freelancer_carrier_mod LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
# No C++20 named modules here; skip dependency scanning (also avoids clang-scan-deps with clang-cl).
set(CMAKE_CXX_SCAN_FOR_MODULES OFF)

if(CMAKE_SYSTEM_NAME STREQUAL "Windows")
  set(FLMOD_HOST OFF)
else()
  set(FLMOD_HOST ON)
endif()

set(FLMOD_TRACK "" CACHE STRING "Platform track for win32 builds: A (FLUF module) or B (plain dacom DLL)")
set_property(CACHE FLMOD_TRACK PROPERTY STRINGS A B)
option(FLMOD_SANITIZE "Host builds: ASan + UBSan" OFF)

set(FLMOD_OUT_DIR "${CMAKE_BINARY_DIR}/out")
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${FLMOD_OUT_DIR}")
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${FLMOD_OUT_DIR}")
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib")

if(FLMOD_HOST)
  message(STATUS "flmod: host build (${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}), sanitize=${FLMOD_SANITIZE}")
  if(FLMOD_SANITIZE)
    add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=all)
    add_link_options(-fsanitize=address,undefined)
  endif()
else()
  if(NOT FLMOD_TRACK MATCHES "^[AB]$")
    message(FATAL_ERROR "win32 builds need -DFLMOD_TRACK=A or -DFLMOD_TRACK=B (use a win32-track* preset)")
  endif()
  if(NOT CMAKE_SIZEOF_VOID_P EQUAL 4)
    message(FATAL_ERROR "win32 builds must target 32-bit x86 (toolchain/clang-cl-i686.cmake)")
  endif()
  enable_language(RC)
  message(STATUS "flmod: win32 Track ${FLMOD_TRACK} build (${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}, XWIN_ROOT=${XWIN_ROOT})")
endif()

include(cmake/FlmodFunctions.cmake)
include(cmake/FlmodVendor.cmake)

if(FLMOD_HOST)
  enable_testing()
endif()

# ------------------------------------------------------------------------------------- logic
# Engine-free C++: no Windows, Freelancer, FLUF or hook headers (LogicIncludeLint + header check).
set(FLMOD_LOGIC_DIR "${PROJECT_SOURCE_DIR}/src/logic")
# Filters work on paths relative to the glob root, so a checkout under some .../tests/... directory is fine.
file(GLOB_RECURSE _logic_rel RELATIVE "${FLMOD_LOGIC_DIR}" CONFIGURE_DEPENDS "${FLMOD_LOGIC_DIR}/*.cpp")
list(FILTER _logic_rel EXCLUDE REGEX "(^|/)tests/")
list(TRANSFORM _logic_rel PREPEND "${FLMOD_LOGIC_DIR}/" OUTPUT_VARIABLE FLMOD_LOGIC_SOURCES)
if(NOT FLMOD_LOGIC_SOURCES)
  set(_ph "${CMAKE_BINARY_DIR}/generated/logic_placeholder.cpp")
  file(WRITE "${_ph}" "// Placeholder: src/logic has no sources yet.\nnamespace flmod::logic { int placeholder() { return 0; } }\n")
  set(FLMOD_LOGIC_SOURCES "${_ph}")
endif()
add_library(logic STATIC ${FLMOD_LOGIC_SOURCES})
target_include_directories(logic PUBLIC "${PROJECT_SOURCE_DIR}/src")
target_link_libraries(logic PUBLIC flmod::nlohmann_json)

# The lint's file set and the header-check set come from cmake/LogicLintFiles.cmake, the same function the lint
# script uses, so the stamp depends on exactly the files the lint reads (tests/ dirs excluded in both).
include(cmake/LogicLintFiles.cmake)
flmod_logic_lint_files(FLMOD_LOGIC_LINT_FILES "${FLMOD_LOGIC_DIR}" CONFIGURE_DEPENDS)
flmod_logic_lint_files(FLMOD_LOGIC_HEADERS "${FLMOD_LOGIC_DIR}" HEADERS_ONLY CONFIGURE_DEPENDS)
add_custom_command(
  OUTPUT "${CMAKE_BINARY_DIR}/generated/logic_include_lint.stamp"
  COMMAND "${CMAKE_COMMAND}" "-DFLMOD_LINT_DIR=${FLMOD_LOGIC_DIR}" "-DFLMOD_LINT_SRC_ROOT=${PROJECT_SOURCE_DIR}/src"
          "-DFLMOD_LINT_STAMP=${CMAKE_BINARY_DIR}/generated/logic_include_lint.stamp"
          -P "${PROJECT_SOURCE_DIR}/cmake/LogicIncludeLint.cmake"
  DEPENDS ${FLMOD_LOGIC_LINT_FILES} "${PROJECT_SOURCE_DIR}/cmake/LogicIncludeLint.cmake"
          "${PROJECT_SOURCE_DIR}/cmake/LogicLintFiles.cmake"
  COMMENT "Checking src/logic includes are engine-free"
  VERBATIM)
add_custom_target(logic_include_lint DEPENDS "${CMAKE_BINARY_DIR}/generated/logic_include_lint.stamp")
add_dependencies(logic logic_include_lint)

# ------------------------------------------------------------------- host: header check + tests
if(FLMOD_HOST)
  include(tests/host/LogicHeaderCheck.cmake)
endif()

# ---------------------------------------------------------------- discovered subdirectories
file(GLOB FLMOD_SUBDIR_LISTS CONFIGURE_DEPENDS
  "${PROJECT_SOURCE_DIR}/src/module/*/CMakeLists.txt"
  "${PROJECT_SOURCE_DIR}/spikes/*/CMakeLists.txt"
  "${PROJECT_SOURCE_DIR}/harness/devbridge/CMakeLists.txt")
list(SORT FLMOD_SUBDIR_LISTS)
foreach(_cml IN LISTS FLMOD_SUBDIR_LISTS)
  get_filename_component(_dir "${_cml}" DIRECTORY)
  file(RELATIVE_PATH _reldir "${PROJECT_SOURCE_DIR}" "${_dir}")
  add_subdirectory("${_dir}" "${CMAKE_BINARY_DIR}/${_reldir}")
endforeach()

# ------------------------------------------------------------------------------- host_tests
if(FLMOD_HOST)
  # tests/host/**/*.cpp (except negative/) and every .cpp at any depth below a tests/ dir under src/.
  file(GLOB_RECURSE _ht_rel RELATIVE "${PROJECT_SOURCE_DIR}/tests/host" CONFIGURE_DEPENDS
       "${PROJECT_SOURCE_DIR}/tests/host/*.cpp")
  list(FILTER _ht_rel EXCLUDE REGEX "^negative/")
  list(TRANSFORM _ht_rel PREPEND "${PROJECT_SOURCE_DIR}/tests/host/" OUTPUT_VARIABLE _ht_sources)
  file(GLOB_RECURSE _ht_src_rel RELATIVE "${PROJECT_SOURCE_DIR}/src" CONFIGURE_DEPENDS "${PROJECT_SOURCE_DIR}/src/*.cpp")
  list(FILTER _ht_src_rel INCLUDE REGEX "(^|/)tests/")
  list(TRANSFORM _ht_src_rel PREPEND "${PROJECT_SOURCE_DIR}/src/" OUTPUT_VARIABLE _ht_src_tests)
  list(APPEND _ht_sources ${_ht_src_tests})
  get_property(_ht_extra GLOBAL PROPERTY FLMOD_HOST_TEST_SOURCES)
  get_property(_ht_libs GLOBAL PROPERTY FLMOD_HOST_TEST_LIBS)
  add_executable(host_tests ${_ht_sources} ${_ht_extra})
  target_link_libraries(host_tests PRIVATE logic flmod::doctest ${_ht_libs})
  target_include_directories(host_tests PRIVATE "${PROJECT_SOURCE_DIR}/src" "${PROJECT_SOURCE_DIR}/tests/host")
  add_test(NAME host_tests COMMAND host_tests --reporters=console --no-colors=true)
endif()

# ------------------------------------------------------------------ win32 binary manifest
# Every DLL/EXE registered through flmod_fluf_module / flmod_dacom_dll / flmod_win32_dll / flmod_win32_exe,
# one absolute path per line. CI stage 50 (import-check) checks exactly these, never stale files in out/.
if(NOT FLMOD_HOST)
  get_property(_flmod_bins GLOBAL PROPERTY FLMOD_WIN32_BINARIES)
  set(_flmod_bin_lines "")
  foreach(_t IN LISTS _flmod_bins)
    string(APPEND _flmod_bin_lines "$<TARGET_FILE:${_t}>\n")
  endforeach()
  file(GENERATE OUTPUT "${CMAKE_BINARY_DIR}/flmod_binaries.txt" CONTENT "${_flmod_bin_lines}")
endif()
