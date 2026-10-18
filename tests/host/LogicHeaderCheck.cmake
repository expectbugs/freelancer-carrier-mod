# tests/host/LogicHeaderCheck.cmake (included by the root CMakeLists.txt in host builds).
#
# Standalone-header test: every src/logic header (outside tests/ dirs, cmake/LogicLintFiles.cmake) must compile on
# its own on Linux with only src/ and nlohmann/json on the include path: no <windows.h>, no FLSDK, no FLUF. Each
# header is included twice
# (include-guard check). Target logic_header_check is part of the default build; ctest
# logic_headers_standalone rebuilds it so the result also shows up in the test report.
#
# Negative probes (not built by default) prove the mechanisms really reject Windows headers:
#   logic_rejects_windows_h_compile  builds tests/host/negative/includes_windows_h.cpp, must FAIL
#   logic_rejects_forbidden_includes_lint  runs LogicIncludeLint over tests/host/negative/lint_fixture; must FAIL
#                                    naming every bad include (Windows.h, synchapi.h behind #ifdef, io.h, tchar.h,
#                                    an unresolved quoted include, a quoted include into a tests/ dir)

set(_hc_dir "${CMAKE_BINARY_DIR}/generated/logic_header_check")
set(_hc_sources "")
foreach(_h IN LISTS FLMOD_LOGIC_HEADERS)
  file(RELATIVE_PATH _rel "${PROJECT_SOURCE_DIR}/src" "${_h}")
  string(MAKE_C_IDENTIFIER "${_rel}" _id)
  set(_tu "${_hc_dir}/${_id}.cpp")
  set(_content "#include \"${_rel}\"\n#include \"${_rel}\"\nint flmod_header_check_${_id}() { return 0; }\n")
  set(_old "")
  if(EXISTS "${_tu}")
    file(READ "${_tu}" _old)
  endif()
  if(NOT _old STREQUAL _content)
    file(WRITE "${_tu}" "${_content}")
  endif()
  list(APPEND _hc_sources "${_tu}")
endforeach()

if(_hc_sources)
  add_library(logic_header_check OBJECT ${_hc_sources})
  target_include_directories(logic_header_check PRIVATE "${PROJECT_SOURCE_DIR}/src")
  target_link_libraries(logic_header_check PRIVATE flmod::nlohmann_json)
  add_dependencies(logic_header_check logic_include_lint)
  add_test(NAME logic_headers_standalone
    COMMAND "${CMAKE_COMMAND}" --build "${CMAKE_BINARY_DIR}" --target logic_header_check)
  # Tests that drive the build tool must not run concurrently in the same build dir.
  set_tests_properties(logic_headers_standalone PROPERTIES RESOURCE_LOCK flmod_build_dir)
endif()

# Negative probes. tests/host/ExpectFailure.cmake requires a non-zero exit AND the specific error text, so a
# broken toolchain or a missing target cannot make them pass.
add_library(logic_negative_probe OBJECT EXCLUDE_FROM_ALL
  "${PROJECT_SOURCE_DIR}/tests/host/negative/includes_windows_h.cpp")
target_include_directories(logic_negative_probe PRIVATE "${PROJECT_SOURCE_DIR}/src")
target_link_libraries(logic_negative_probe PRIVATE flmod::nlohmann_json)
add_test(NAME logic_rejects_windows_h_compile
  COMMAND "${CMAKE_COMMAND}"
          "-DFLMOD_CMD=${CMAKE_COMMAND};--build;${CMAKE_BINARY_DIR};--target;logic_negative_probe"
          "-DFLMOD_EXPECT='windows.h' file not found;includes_windows_h.cpp"
          -P "${PROJECT_SOURCE_DIR}/tests/host/ExpectFailure.cmake")
set_tests_properties(logic_rejects_windows_h_compile PROPERTIES RESOURCE_LOCK flmod_build_dir)

add_test(NAME logic_rejects_forbidden_includes_lint
  COMMAND "${CMAKE_COMMAND}"
          "-DFLMOD_CMD=${CMAKE_COMMAND};-DFLMOD_LINT_DIR=${PROJECT_SOURCE_DIR}/tests/host/negative/lint_fixture;-DFLMOD_LINT_SRC_ROOT=${PROJECT_SOURCE_DIR}/src;-P;${PROJECT_SOURCE_DIR}/cmake/LogicIncludeLint.cmake"
          "-DFLMOD_EXPECT=Forbidden includes;bad_header.hpp: #include <Windows.h>;bad_ifdef.hpp: #include <synchapi.h>;bad_crt.hpp: #include <io.h>;bad_crt.hpp: #include <tchar.h>;bad_quoted.hpp: #include .game/fl_adapter.hpp.;bad_tests_include.hpp: #include .tests/leak_helper.hpp. +.resolves into a tests/ dir"
          -P "${PROJECT_SOURCE_DIR}/tests/host/ExpectFailure.cmake")

add_test(NAME logic_include_lint_passes
  COMMAND "${CMAKE_COMMAND}" "-DFLMOD_LINT_DIR=${FLMOD_LOGIC_DIR}" "-DFLMOD_LINT_SRC_ROOT=${PROJECT_SOURCE_DIR}/src"
          -P "${PROJECT_SOURCE_DIR}/cmake/LogicIncludeLint.cmake")

# Positive fixture: a doctest file (and a doctest-including helper header) under src/logic/<area>/tests/ must
# pass the lint and the header check and run in host_tests, on an incremental and on a fresh build of a scratch
# copy of the tree (tests/host/LogicTestsDirFixture.cmake). The copy is configured with this option OFF, so the
# fixture does not recurse.
option(FLMOD_SELFTEST_FIXTURES "Host builds: register ctest fixtures that build scratch copies of the tree" ON)
if(FLMOD_SELFTEST_FIXTURES)
  add_test(NAME logic_tests_dir_doctest
    COMMAND "${CMAKE_COMMAND}" "-DFLMOD_SRC=${PROJECT_SOURCE_DIR}"
            "-DFLMOD_WORK=${CMAKE_BINARY_DIR}/fixtures/logic_tests_dir" "-DFLMOD_VENDOR=${FLMOD_VENDOR}"
            "-DFLMOD_GENERATOR=${CMAKE_GENERATOR}" "-DFLMOD_MAKE=${CMAKE_MAKE_PROGRAM}"
            -P "${PROJECT_SOURCE_DIR}/tests/host/LogicTestsDirFixture.cmake")
  set_tests_properties(logic_tests_dir_doctest PROPERTIES TIMEOUT 600)
endif()
