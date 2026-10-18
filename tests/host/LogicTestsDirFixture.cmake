# tests/host/LogicTestsDirFixture.cmake: ctest `logic_tests_dir_doctest` (host builds; review r2 F1).
#
# Proves that a doctest file under a src/logic/<area>/tests/ dir, plus a test-only helper header there that itself
# includes <doctest/doctest.h>, passes the include lint and the standalone-header check, is compiled into
# host_tests, and runs. Two phases on a scratch copy of the tree (the real tree is never modified):
#   1. incremental: configure + build the copy, then add the files and run `cmake --build` again (no manual
#      reconfigure), as a developer would;
#   2. fresh: delete the copy's build dir, configure + build with the files present, as CI does.
# Each phase then runs `host_tests --test-case=zz_fixture*` (must report 1 passed) and the copy's ctest
# logic_include_lint_passes + logic_headers_standalone.
#
#   cmake -DFLMOD_SRC=<source dir> -DFLMOD_WORK=<scratch dir> -DFLMOD_VENDOR=<vendor dir>
#         -DFLMOD_GENERATOR=<generator> -DFLMOD_MAKE=<make program> -P tests/host/LogicTestsDirFixture.cmake
foreach(_v FLMOD_SRC FLMOD_WORK FLMOD_VENDOR FLMOD_GENERATOR FLMOD_MAKE)
  if(NOT DEFINED ${_v} OR "${${_v}}" STREQUAL "")
    message(FATAL_ERROR "LogicTestsDirFixture: pass -D${_v}=...")
  endif()
endforeach()

set(_tree "${FLMOD_WORK}/tree")
set(_bin "${FLMOD_WORK}/build")
set(_area "${_tree}/src/logic/zz_fixture/tests")

function(_step name)
  execute_process(COMMAND ${ARGN} RESULT_VARIABLE _rc OUTPUT_VARIABLE _out ERROR_VARIABLE _err)
  set(_step_out "${_out}\n${_err}" PARENT_SCOPE)
  if(NOT _rc EQUAL 0)
    message(FATAL_ERROR "LogicTestsDirFixture: step '${name}' failed (exit ${_rc}):\n  ${ARGN}\n${_out}\n${_err}")
  endif()
  message(STATUS "LogicTestsDirFixture: ${name}: ok")
endfunction()

function(_configure_and_build phase)
  _step("${phase}: configure" "${CMAKE_COMMAND}" -S "${_tree}" -B "${_bin}" -G "${FLMOD_GENERATOR}"
        "-DCMAKE_MAKE_PROGRAM=${FLMOD_MAKE}" "-DCMAKE_TOOLCHAIN_FILE=${_tree}/toolchain/host.cmake"
        -DCMAKE_BUILD_TYPE=RelWithDebInfo -DFLMOD_SANITIZE=OFF "-DFLMOD_VENDOR=${FLMOD_VENDOR}"
        -DFLMOD_SELFTEST_FIXTURES=OFF)
  _step("${phase}: build" "${CMAKE_COMMAND}" --build "${_bin}")
endfunction()

function(_add_fixture_files)
  file(MAKE_DIRECTORY "${_area}")
  file(WRITE "${_area}/zz_fixture_helper.hpp"
    "#pragma once\n"
    "// Test-only helper next to the tests: includes doctest, so the lint and the header check must skip it.\n"
    "#include <doctest/doctest.h>\n\n"
    "inline int zz_fixture_answer() { return 42; }\n")
  file(WRITE "${_area}/test_zz_fixture.cpp"
    "// A host test living in src/logic/<area>/tests/ (BUILD_PLAN §6 layout).\n"
    "#include <doctest/doctest.h>\n\n"
    "#include \"logic/core/flhash.hpp\"\n"
    "#include \"zz_fixture_helper.hpp\"\n\n"
    "TEST_CASE(\"zz_fixture: doctest file under src/logic/<area>/tests\")\n{\n"
    "    CHECK(zz_fixture_answer() == 42);\n"
    "    CHECK(flmod::logic::create_id(\"li02\") == 2745692751u);\n}\n")
endfunction()

function(_run_checks phase)
  _step("${phase}: run host_tests zz_fixture" "${_bin}/out/host_tests" "--test-case=zz_fixture*" --no-colors=true)
  if(NOT _step_out MATCHES "test cases: *1 \\| *1 passed \\| *0 failed")
    message(FATAL_ERROR "LogicTestsDirFixture: ${phase}: the fixture test case did not run exactly once:\n${_step_out}")
  endif()
  _step("${phase}: ctest lint + header check" "${CMAKE_CTEST_COMMAND}" --test-dir "${_bin}" --output-on-failure
        -R "^(logic_include_lint_passes|logic_headers_standalone)$")
  if(NOT _step_out MATCHES "100% tests passed, 0 tests failed out of 2")
    message(FATAL_ERROR "LogicTestsDirFixture: ${phase}: expected 2 passing ctest checks:\n${_step_out}")
  endif()
  file(GLOB _hc "${_bin}/generated/logic_header_check/*zz_fixture*")
  if(_hc)
    message(FATAL_ERROR "LogicTestsDirFixture: ${phase}: the header check compiles tests/ files: ${_hc}")
  endif()
endfunction()

# Scratch copy: only what a host build reads.
file(REMOVE_RECURSE "${FLMOD_WORK}")
file(MAKE_DIRECTORY "${_tree}/toolchain" "${_tree}/tests")
file(COPY "${FLMOD_SRC}/CMakeLists.txt" "${FLMOD_SRC}/cmake" "${FLMOD_SRC}/src" DESTINATION "${_tree}")
file(COPY "${FLMOD_SRC}/toolchain/host.cmake" DESTINATION "${_tree}/toolchain")
file(COPY "${FLMOD_SRC}/tests/host" DESTINATION "${_tree}/tests")
if(EXISTS "${_tree}/src/logic/zz_fixture")
  message(FATAL_ERROR "LogicTestsDirFixture: src/logic/zz_fixture already exists in the source tree")
endif()

# Phase 1: incremental (files added after the first build; `cmake --build` must pick them up and pass).
_configure_and_build("incremental, before")
_add_fixture_files()
_step("incremental, after: build" "${CMAKE_COMMAND}" --build "${_bin}")
_run_checks("incremental")

# Phase 2: fresh configure + build with the files present.
file(REMOVE_RECURSE "${_bin}")
_configure_and_build("fresh")
_run_checks("fresh")

file(REMOVE_RECURSE "${FLMOD_WORK}")
message(STATUS "LogicTestsDirFixture: PASS (incremental and fresh)")
