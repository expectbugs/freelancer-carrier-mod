# cmake/FlmodFunctions.cmake: the target helpers every C++ package uses.
# Usage is documented in toolchain/README.md ("Adding a target").

# --- scope guards (macros, so return() leaves the calling CMakeLists.txt) -------------------------

# flmod_track_only(A|B): skip the rest of this CMakeLists.txt unless this is a win32 build of that track.
macro(flmod_track_only _flmod_track)
  if(FLMOD_HOST OR NOT FLMOD_TRACK STREQUAL "${_flmod_track}")
    return()
  endif()
endmacro()

# flmod_win32_only(): skip the rest of this CMakeLists.txt in host builds.
macro(flmod_win32_only)
  if(FLMOD_HOST)
    return()
  endif()
endmacro()

# flmod_host_only(): skip the rest of this CMakeLists.txt in win32 builds.
macro(flmod_host_only)
  if(NOT FLMOD_HOST)
    return()
  endif()
endmacro()

# --- DLL helpers ---------------------------------------------------------------------------------

function(_flmod_win32_common target)
  set_target_properties(${target} PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${FLMOD_OUT_DIR}"
    LIBRARY_OUTPUT_DIRECTORY "${FLMOD_OUT_DIR}"
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib")
  set_property(GLOBAL APPEND PROPERTY FLMOD_WIN32_BINARIES ${target})
endfunction()

# flmod_fluf_module(<target>): make <target> (an add_library(SHARED) target) a FLUF module DLL.
# Applies the full Track A ABI must-match list (defines, include dirs, FLUF.lib + FreelancerSDK.lib +
# FLSDK import libs + reflectcpp + yaml-cpp + msgpack-c + zstd + dsound/ws2_32/dxguid). The module's
# source must contain SETUP_MODULE(Type, ModuleMajorVersion::Two, ModuleMinorVersion::Zero) exactly
# once; that exports GetMajorVersion, GetMinorVersion and ModuleFactory. Never define FLUF.
function(flmod_fluf_module target)
  if(FLMOD_HOST OR NOT FLMOD_TRACK STREQUAL "A")
    message(FATAL_ERROR "flmod_fluf_module(${target}) needs a win32 Track A build (preset win32-trackA)")
  endif()
  get_target_property(_type ${target} TYPE)
  if(NOT _type STREQUAL "SHARED_LIBRARY")
    message(FATAL_ERROR "flmod_fluf_module(${target}): target must be add_library(${target} SHARED ...)")
  endif()
  target_link_libraries(${target} PRIVATE flmod::fluf)
  _flmod_win32_common(${target})
endfunction()

# flmod_dacom_dll(<target>): a plain DLL for dacom.ini [Libraries] (Track B shape; also fine for
# throwaway tools such as harness self-test DLLs). FLSDK headers + Freelancer import libs, static
# MinHook; static Dear ImGui (dx9 + win32 backends) in Track B builds. No FLUF anything.
function(flmod_dacom_dll target)
  if(FLMOD_HOST)
    message(FATAL_ERROR "flmod_dacom_dll(${target}) needs a win32 build")
  endif()
  get_target_property(_type ${target} TYPE)
  if(NOT _type STREQUAL "SHARED_LIBRARY")
    message(FATAL_ERROR "flmod_dacom_dll(${target}): target must be add_library(${target} SHARED ...)")
  endif()
  target_link_libraries(${target} PRIVATE
    flmod::win32_defs flmod::flsdk_headers flmod::flcore flmod::minhook d3d9 dxguid user32)
  if(TARGET flmod::imgui_static)
    target_link_libraries(${target} PRIVATE flmod::imgui_static)
  endif()
  _flmod_win32_common(${target})
endfunction()

# flmod_win32_dll(<target>): a plain win32 DLL with no Freelancer or hook libraries (tools, probes).
function(flmod_win32_dll target)
  if(FLMOD_HOST)
    message(FATAL_ERROR "flmod_win32_dll(${target}) needs a win32 build")
  endif()
  target_link_libraries(${target} PRIVATE flmod::win32_defs)
  _flmod_win32_common(${target})
endfunction()

# flmod_win32_exe(<target>): a win32 console tool (e.g. loadtest) placed in out/.
function(flmod_win32_exe target)
  target_link_libraries(${target} PRIVATE flmod::win32_defs)
  _flmod_win32_common(${target})
endfunction()

# flmod_rc_includes(<target>): let .rc files in <target> include <windows.h>/<winres.h>.
function(flmod_rc_includes target)
  foreach(_d IN LISTS FLMOD_RC_INCLUDE_DIRS)
    target_compile_options(${target} PRIVATE "$<$<COMPILE_LANGUAGE:RC>:/I${_d}>")
  endforeach()
endfunction()

# --- host tests ----------------------------------------------------------------------------------

# flmod_host_tests(SOURCES <files...> [LIBS <targets...>]): add doctest files (and the libraries they
# test) to the single host_tests executable. Files under tests/host/** and src/**/tests/*.cpp are
# picked up automatically; this is for anything else (e.g. harness/devbridge). Host builds only.
function(flmod_host_tests)
  cmake_parse_arguments(ARG "" "" "SOURCES;LIBS" ${ARGN})
  if(NOT FLMOD_HOST)
    return()
  endif()
  foreach(_s IN LISTS ARG_SOURCES)
    get_filename_component(_abs "${_s}" ABSOLUTE BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
    set_property(GLOBAL APPEND PROPERTY FLMOD_HOST_TEST_SOURCES "${_abs}")
  endforeach()
  set_property(GLOBAL APPEND PROPERTY FLMOD_HOST_TEST_LIBS ${ARG_LIBS})
endfunction()
