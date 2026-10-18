# cmake/FlmodVendor.cmake: imported/vendored third-party targets.
#
# Everything comes from the shared, read-only $FLMOD_VENDOR tree that toolchain/fetch_vendor.sh fills
# (pins in toolchain/PINS.md). Worktrees don't have a vendor/ dir, so the location is always absolute.
#
# Targets defined here (only those that make sense for the current build):
#   all builds   flmod::nlohmann_json
#   host         flmod::doctest
#   win32        flmod::win32_defs, flmod::flsdk_headers, flmod::flcore, flmod::minhook,
#                flmod::imgui_static (Track B), flmod::flsdk_static
#   Track A      flmod::fluf (headers, ABI defines, FLUF.lib + deps, reflectcpp)

if(DEFINED ENV{FLMOD_VENDOR} AND NOT "$ENV{FLMOD_VENDOR}" STREQUAL "")
  set(_flmod_vendor_default "$ENV{FLMOD_VENDOR}")
else()
  set(_flmod_vendor_default "/home/user/freelancer/carrier-mod/vendor")
endif()
set(FLMOD_VENDOR "${_flmod_vendor_default}" CACHE PATH "Shared vendor tree (toolchain/fetch_vendor.sh)")

function(flmod_require_vendor)
  foreach(_name IN LISTS ARGN)
    # Trees carry <dir>/.flmod-pin; single files carry <file>.flmod-pin (fetch_vendor.sh).
    if(NOT EXISTS "${FLMOD_VENDOR}/${_name}/.flmod-pin" AND NOT EXISTS "${FLMOD_VENDOR}/${_name}.flmod-pin")
      message(FATAL_ERROR
        "Vendor input '${_name}' is missing from FLMOD_VENDOR=${FLMOD_VENDOR}.\n"
        "Run toolchain/fetch_vendor.sh (P0-TOOLCHAIN is its only writer).")
    endif()
  endforeach()
endfunction()

flmod_require_vendor(nlohmann_json/include/nlohmann/json.hpp)

# ---------------------------------------------------------------- all builds
add_library(flmod_nlohmann_json INTERFACE)
add_library(flmod::nlohmann_json ALIAS flmod_nlohmann_json)
target_include_directories(flmod_nlohmann_json SYSTEM INTERFACE "${FLMOD_VENDOR}/nlohmann_json/include")

if(FLMOD_HOST)
  # ------------------------------------------------------------ host
  flmod_require_vendor(doctest)
  add_library(flmod_doctest INTERFACE)
  add_library(flmod::doctest ALIAS flmod_doctest)
  target_include_directories(flmod_doctest SYSTEM INTERFACE "${FLMOD_VENDOR}/doctest")
  return()
endif()

# -------------------------------------------------------------------- win32 (both tracks)
flmod_require_vendor(FLSDK minhook)

# Win32 defines shared by both tracks (identical to the FLUF must-match subset, so code behaves the
# same whichever track is chosen).
add_library(flmod_win32_defs INTERFACE)
add_library(flmod::win32_defs ALIAS flmod_win32_defs)
target_compile_definitions(flmod_win32_defs INTERFACE
  WIN32 WIN32_LEAN_AND_MEAN UNICODE _UNICODE NOMINMAX _CRT_SECURE_NO_WARNINGS
  _SILENCE_CXX17_CODECVT_HEADER_DEPRECATION_WARNING WINVER=0x0A00 _WIN32_WINNT=0x0A00)

set(FLMOD_FLSDK "${FLMOD_VENDOR}/FLSDK")
add_library(flmod_flsdk_headers INTERFACE)
add_library(flmod::flsdk_headers ALIAS flmod_flsdk_headers)
target_include_directories(flmod_flsdk_headers SYSTEM INTERFACE "${FLMOD_FLSDK}/include")

# Freelancer's own DLLs, through FLSDK's MSVC import libraries (VC6-era binaries; st6:: rule, ABI.md).
add_library(flmod_flcore INTERFACE)
add_library(flmod::flcore ALIAS flmod_flcore)
target_link_libraries(flmod_flcore INTERFACE
  "${FLMOD_FLSDK}/lib/FLCoreCommon.lib"
  "${FLMOD_FLSDK}/lib/FLCoreServer.lib"
  "${FLMOD_FLSDK}/lib/FLCoreDALib.lib"
  "${FLMOD_FLSDK}/lib/FLCoreDACom.lib"
  "${FLMOD_FLSDK}/lib/FLCoreRemoteClient.lib")

# MinHook (BSD-2), static. Track B detours; harmless elsewhere (only linked when asked for).
set(_mh "${FLMOD_VENDOR}/minhook")
add_library(flmod_minhook STATIC EXCLUDE_FROM_ALL
  "${_mh}/src/buffer.c" "${_mh}/src/hook.c" "${_mh}/src/trampoline.c" "${_mh}/src/hde/hde32.c")
add_library(flmod::minhook ALIAS flmod_minhook)
target_include_directories(flmod_minhook SYSTEM PUBLIC "${_mh}/include")
target_compile_options(flmod_minhook PRIVATE -w)

# FLSDK's own sources (X86Math, Utils, INI_Reader helpers, ...) as a static lib built with our
# compiler. Track A links FLUF's prebuilt FreelancerSDK.lib instead (same sources, FLUF's build).
file(GLOB_RECURSE _flsdk_sources CONFIGURE_DEPENDS "${FLMOD_FLSDK}/source/*.cpp")
add_library(flmod_flsdk_static STATIC EXCLUDE_FROM_ALL ${_flsdk_sources})
add_library(flmod::flsdk_static ALIAS flmod_flsdk_static)
target_link_libraries(flmod_flsdk_static PUBLIC flmod::win32_defs flmod::flsdk_headers flmod::flcore
  dsound ws2_32 dxguid)
target_compile_options(flmod_flsdk_static PRIVATE -w)

if(FLMOD_TRACK STREQUAL "B")
  # ------------------------------------------------------------ Track B: static Dear ImGui
  flmod_require_vendor(imgui)
  set(_ig "${FLMOD_VENDOR}/imgui")
  add_library(flmod_imgui_static STATIC EXCLUDE_FROM_ALL
    "${_ig}/imgui.cpp" "${_ig}/imgui_draw.cpp" "${_ig}/imgui_tables.cpp" "${_ig}/imgui_widgets.cpp"
    "${_ig}/imgui_demo.cpp"
    "${_ig}/backends/imgui_impl_dx9.cpp" "${_ig}/backends/imgui_impl_win32.cpp")
  add_library(flmod::imgui_static ALIAS flmod_imgui_static)
  target_include_directories(flmod_imgui_static SYSTEM PUBLIC "${_ig}" "${_ig}/backends")
  # IMGUI_API stays empty (static). No IME functions: they would import imm32.dll, which is outside
  # the import allowlist (toolchain/check_imports.py) and useless for this mod.
  target_compile_definitions(flmod_imgui_static PUBLIC IMGUI_DISABLE_WIN32_DEFAULT_IME_FUNCTIONS)
  target_link_libraries(flmod_imgui_static PUBLIC flmod::win32_defs d3d9 user32)
  target_compile_options(flmod_imgui_static PRIVATE -w)
  return()
endif()

# ---------------------------------------------------------------------- Track A: FLUF dev package
flmod_require_vendor(FLUF reflect-cpp)
set(FLMOD_FLUF "${FLMOD_VENDOR}/FLUF" CACHE PATH "FLUF release (nightly pin) used for Track A")
set(_fd "${FLMOD_FLUF}/development")
foreach(_lib FLUF.lib FreelancerSDK.lib yaml-cpp.lib msgpack-c.lib zstd_static.lib)
  if(NOT EXISTS "${_fd}/lib/${_lib}")
    message(FATAL_ERROR "FLUF dev package incomplete: ${_fd}/lib/${_lib} is missing")
  endif()
endforeach()

# Shims for reflect-cpp's find_package(yaml-cpp) / find_package(msgpack-c): it skips the lookup when
# these targets already exist. They point at the prebuilt libs in FLUF's dev package (R1 §5.3 step 6).
add_library(yaml-cpp::yaml-cpp STATIC IMPORTED GLOBAL)
set_target_properties(yaml-cpp::yaml-cpp PROPERTIES
  IMPORTED_LOCATION "${_fd}/lib/yaml-cpp.lib"
  INTERFACE_INCLUDE_DIRECTORIES "${_fd}/include/yaml-cpp"
  INTERFACE_COMPILE_DEFINITIONS "YAML_CPP_STATIC_DEFINE")
add_library(msgpack-c STATIC IMPORTED GLOBAL)
set_target_properties(msgpack-c PROPERTIES
  IMPORTED_LOCATION "${_fd}/lib/msgpack-c.lib"
  INTERFACE_INCLUDE_DIRECTORIES "${_fd}/include/msgpack-c")

# reflect-cpp at FLUF's exact submodule commit, static, same compiler and flags (R1 §5.3 step 6).
set(REFLECTCPP_YAML ON CACHE BOOL "" FORCE)
set(REFLECTCPP_MSGPACK ON CACHE BOOL "" FORCE)
set(REFLECTCPP_BUILD_SHARED OFF CACHE BOOL "" FORCE)
set(REFLECTCPP_USE_STD_EXPECTED ON CACHE BOOL "" FORCE)
set(REFLECTCPP_USE_VCPKG OFF CACHE BOOL "" FORCE)
set(REFLECTCPP_USE_BUNDLED_DEPENDENCIES ON CACHE BOOL "" FORCE)
set(REFLECTCPP_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(REFLECTCPP_INSTALL OFF CACHE BOOL "" FORCE)
add_subdirectory("${FLMOD_VENDOR}/reflect-cpp" "${CMAKE_BINARY_DIR}/_vendor/reflect-cpp" EXCLUDE_FROM_ALL SYSTEM)
target_compile_options(reflectcpp PRIVATE -w)

# FLUF ABI must-match list (R1 §5.3 step 4, §5.4; FLUF cmake/Utils.cmake:76-97). Never define FLUF.
add_library(flmod_fluf INTERFACE)
add_library(flmod::fluf ALIAS flmod_fluf)
target_compile_definitions(flmod_fluf INTERFACE
  WIN32 WIN32_LEAN_AND_MEAN UNICODE _UNICODE NOMINMAX _CRT_SECURE_NO_WARNINGS
  _SILENCE_CXX17_CODECVT_HEADER_DEPRECATION_WARNING WINVER=0x0A00 _WIN32_WINNT=0x0A00
  FLUF_SDK YAML_CPP_STATIC_DEFINE
  IMGUI_DEFINE_MATH_OPERATORS IMGUI_ENABLE_FREETYPE IMGUI_USE_STB_SPRINTF IMGUI_USE_WCHAR32
  "IMGUI_API=__declspec(dllimport)" "IMPLOT_API=__declspec(dllimport)" "STBIDEF=__declspec(dllimport)")
target_include_directories(flmod_fluf SYSTEM INTERFACE
  "${_fd}/include"
  "${_fd}/include/FLUF"
  "${_fd}/include/imgui"
  "${_fd}/include/imcp"
  "${_fd}/include/yaml-cpp"
  "${_fd}/include/msgpack-c"
  "${_fd}/include/zstd"
  "${FLMOD_FLSDK}/include"
  "${FLMOD_VENDOR}/reflect-cpp/include"
  "${FLMOD_VENDOR}/reflect-cpp/include/rfl/thirdparty")
target_link_libraries(flmod_fluf INTERFACE
  "${_fd}/lib/FLUF.lib"
  "${_fd}/lib/FreelancerSDK.lib"
  flmod::flcore
  reflectcpp
  yaml-cpp::yaml-cpp
  msgpack-c
  "${_fd}/lib/zstd_static.lib"
  dsound ws2_32 dxguid)
