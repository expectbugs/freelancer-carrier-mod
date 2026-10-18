# tests/host/LogicHeaderCheck.cmake (included by the root CMakeLists.txt in host builds).
#
# Standalone-header test: every src/logic header must compile on its own on Linux with only src/ and
# nlohmann/json on the include path: no <windows.h>, no FLSDK, no FLUF. Each header is included twice
# (include-guard check). Target logic_header_check is part of the default build; ctest
# logic_headers_standalone rebuilds it so the result also shows up in the test report.
#
# Negative probes (not built by default) prove the mechanisms really reject Windows headers:
#   logic_rejects_windows_h_compile  builds tests/host/negative/includes_windows_h.cpp, must FAIL
#   logic_rejects_windows_h_lint     runs LogicIncludeLint over tests/host/negative/lint_fixture, must FAIL

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

add_library(logic_negative_probe OBJECT EXCLUDE_FROM_ALL
  "${PROJECT_SOURCE_DIR}/tests/host/negative/includes_windows_h.cpp")
target_include_directories(logic_negative_probe PRIVATE "${PROJECT_SOURCE_DIR}/src")
target_link_libraries(logic_negative_probe PRIVATE flmod::nlohmann_json)
add_test(NAME logic_rejects_windows_h_compile
  COMMAND "${CMAKE_COMMAND}" --build "${CMAKE_BINARY_DIR}" --target logic_negative_probe)
set_tests_properties(logic_rejects_windows_h_compile PROPERTIES WILL_FAIL TRUE RESOURCE_LOCK flmod_build_dir)

add_test(NAME logic_rejects_windows_h_lint
  COMMAND "${CMAKE_COMMAND}" "-DFLMOD_LINT_DIR=${PROJECT_SOURCE_DIR}/tests/host/negative/lint_fixture"
          -P "${PROJECT_SOURCE_DIR}/cmake/LogicIncludeLint.cmake")
set_tests_properties(logic_rejects_windows_h_lint PROPERTIES WILL_FAIL TRUE)

add_test(NAME logic_include_lint_passes
  COMMAND "${CMAKE_COMMAND}" "-DFLMOD_LINT_DIR=${FLMOD_LOGIC_DIR}"
          -P "${PROJECT_SOURCE_DIR}/cmake/LogicIncludeLint.cmake")
