# toolchain/clang-cl-i686.cmake: 32-bit Windows (i686-pc-windows-msvc) cross build on Linux.
#
# clang-cl 22 + lld-link + llvm-rc against the MSVC CRT/STL and Windows SDK splatted by xwin into
# $XWIN_ROOT (/winsysroot layout; see toolchain/setup_xwin.sh and toolchain/PINS.md).
# MSVC ABI only, /MD release CRT, _ITERATOR_DEBUG_LEVEL=0 (FLUF must-match list, toolchain/ABI.md).
#
# Do not use FLUF's profiles/ or module_tools/ instead: they hardcode /usr/bin tool paths and the
# msvc-wine layout (R1 §5.1).

set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86)

set(FLMOD_LLVM_BIN "/usr/lib/llvm/22/bin" CACHE PATH "LLVM 22 bin directory")

if(DEFINED ENV{XWIN_ROOT} AND NOT "$ENV{XWIN_ROOT}" STREQUAL "")
  set(_flmod_xwin_default "$ENV{XWIN_ROOT}")
else()
  set(_flmod_xwin_default "/home/user/opt/xwin")
endif()
set(XWIN_ROOT "${_flmod_xwin_default}" CACHE PATH "MSVC CRT/STL + Windows SDK splat (xwin /winsysroot layout)")

if(NOT EXISTS "${XWIN_ROOT}/VC/Tools/MSVC" OR NOT EXISTS "${XWIN_ROOT}/Windows Kits/10/Include")
  message(FATAL_ERROR
    "XWIN_ROOT=${XWIN_ROOT} is not an xwin /winsysroot splat. Run toolchain/setup_xwin.sh first.")
endif()

set(CMAKE_C_COMPILER   "${FLMOD_LLVM_BIN}/clang-cl")
set(CMAKE_CXX_COMPILER "${FLMOD_LLVM_BIN}/clang-cl")
set(CMAKE_C_COMPILER_TARGET   i686-pc-windows-msvc)
set(CMAKE_CXX_COMPILER_TARGET i686-pc-windows-msvc)
set(CMAKE_LINKER     "${FLMOD_LLVM_BIN}/lld-link" CACHE FILEPATH "" FORCE)
set(CMAKE_RC_COMPILER "${FLMOD_LLVM_BIN}/llvm-rc")
set(CMAKE_AR         "${FLMOD_LLVM_BIN}/llvm-lib" CACHE FILEPATH "" FORCE)
set(CMAKE_MT         "${FLMOD_LLVM_BIN}/llvm-mt"  CACHE FILEPATH "" FORCE)

# /MD, release CRT only. Never /MDd (FLUF.dll and every module use the release CRT).
set(CMAKE_MSVC_RUNTIME_LIBRARY MultiThreadedDLL)
# /Z7 (debug info embedded in the objects, no PDB server), in every configuration. -gdwarf below
# switches the format to DWARF so gdb/lldb under Wine can read it.
set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT Embedded)

# -mstackrealign: forces every function with a frame to realign its stack, so EH functions address their
# frame through EBP/ESI and restore ESP from EBP in the epilogue. That makes an exception that leaves a catch
# block and is caught by a try in the same function safe under Wine's builtin vcruntime140: Wine resumes the
# parent with the catch funclet's ESP (LLVM stores it into the EH registration node), and without this flag
# the ESP-relative epilogue then pops garbage. Pure codegen: no calling-convention, layout or mangling change.
# Evidence: toolchain/NOTES.md "Bug 2"; regression cases c_* / lib_* in src/module/ehprobe (toolchain/ehprobe.sh).
set(_flmod_common_flags
  "/winsysroot \"${XWIN_ROOT}\""
  "-gdwarf"
  "/utf-8"
  "/permissive-"
  "-D_ITERATOR_DEBUG_LEVEL=0"
  "-Wno-microsoft-cast"
  "-Wno-cast-function-type-mismatch"
  "/clang:-mstackrealign"
)
string(JOIN " " _flmod_common_flags ${_flmod_common_flags})
set(CMAKE_C_FLAGS_INIT   "${_flmod_common_flags}")
set(CMAKE_CXX_FLAGS_INIT "${_flmod_common_flags} /EHa")

# CMake's Windows-MSVC platform module appends "/EHsc" to CMAKE_CXX_FLAGS_INIT after this file runs,
# and the last /EH flag wins. The rules-override file runs after the platform module and rewrites
# /EHsc to /EHa. /EHa (clang: -fasync-exceptions) is what FLUF builds with, and it is needed for a
# __try/__except to catch a fault raised by an instruction inside the __try function itself (with /EHsc that
# process dies; VERIFIED, NOTES.md "Bug 2"). It does NOT make catch(...) a reliable SEH catcher: see ABI.md §6.
set(CMAKE_USER_MAKE_RULES_OVERRIDE "${CMAKE_CURRENT_LIST_DIR}/clang-cl-i686-overrides.cmake")

# lld-link: /DEBUG:DWARF keeps the DWARF sections in the image (no PDB). /SAFESEH:NO is required for
# Freelancer's exception handling (module_tools comment; R4 §B9).
set(_flmod_link_flags
  "/winsysroot:\"${XWIN_ROOT}\""
  "/SAFESEH:NO"
  "/INCREMENTAL:NO"
  "/OPT:REF"
  "/OPT:ICF"
  "/DEBUG:DWARF"
)
string(JOIN " " _flmod_link_flags ${_flmod_link_flags})
set(CMAKE_EXE_LINKER_FLAGS_INIT    "${_flmod_link_flags}")
set(CMAKE_SHARED_LINKER_FLAGS_INIT "${_flmod_link_flags}")
set(CMAKE_MODULE_LINKER_FLAGS_INIT "${_flmod_link_flags}")

# llvm-rc does not understand /winsysroot: give it the SDK and CRT include dirs explicitly (for
# <winres.h>/<windows.h> in .rc files). The newest version directory wins, like /winsysroot does.
file(GLOB _flmod_sdk_inc LIST_DIRECTORIES true "${XWIN_ROOT}/Windows Kits/10/Include/10.*")
list(SORT _flmod_sdk_inc COMPARE NATURAL ORDER DESCENDING)
list(GET _flmod_sdk_inc 0 _flmod_sdk_inc)
file(GLOB _flmod_vc_inc LIST_DIRECTORIES true "${XWIN_ROOT}/VC/Tools/MSVC/*")
list(SORT _flmod_vc_inc COMPARE NATURAL ORDER DESCENDING)
list(GET _flmod_vc_inc 0 _flmod_vc_inc)
set(FLMOD_RC_INCLUDE_DIRS
  "${_flmod_sdk_inc}/um" "${_flmod_sdk_inc}/shared" "${_flmod_sdk_inc}/ucrt" "${_flmod_vc_inc}/include"
  CACHE INTERNAL "Include dirs for llvm-rc")

# Never pick up host (Linux) libraries or headers.
set(CMAKE_FIND_ROOT_PATH "${XWIN_ROOT}")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)

# try_compile (compiler checks) must see the same settings.
list(APPEND CMAKE_TRY_COMPILE_PLATFORM_VARIABLES XWIN_ROOT FLMOD_LLVM_BIN)
