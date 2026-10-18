# tests/host/ExpectFailure.cmake: run a command that must FAIL for a specific reason.
#   cmake -DFLMOD_CMD="<arg;arg;...>" -DFLMOD_EXPECT="<regex;regex;...>" -P tests/host/ExpectFailure.cmake
# Passes only if the command exits non-zero AND its combined output matches every regex. A command that
# succeeds, or fails for another reason (broken toolchain, missing target), makes the test fail.
if(NOT DEFINED FLMOD_CMD OR NOT DEFINED FLMOD_EXPECT OR FLMOD_CMD STREQUAL "" OR FLMOD_EXPECT STREQUAL "")
  message(FATAL_ERROR "ExpectFailure: pass -DFLMOD_CMD=... and -DFLMOD_EXPECT=...")
endif()
execute_process(COMMAND ${FLMOD_CMD} RESULT_VARIABLE _rc OUTPUT_VARIABLE _out ERROR_VARIABLE _err)
set(_all "${_out}\n${_err}")
if(_rc EQUAL 0)
  message(FATAL_ERROR "ExpectFailure: the command succeeded but must fail:\n  ${FLMOD_CMD}\n${_all}")
endif()
foreach(_re IN LISTS FLMOD_EXPECT)
  if(NOT _all MATCHES "${_re}")
    message(FATAL_ERROR "ExpectFailure: the command failed (exit ${_rc}) but its output lacks /${_re}/:\n${_all}")
  endif()
endforeach()
message(STATUS "ExpectFailure: failed as expected (exit ${_rc}); matched: ${FLMOD_EXPECT}")
