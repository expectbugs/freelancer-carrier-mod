# ehprobe.dll: exception-handling regression probe (toolchain/ehprobe.sh, toolchain/ABI.md §6).
# Built by both win32 presets, with exactly the flags every module gets.
flmod_win32_only()

add_library(ehprobe SHARED ehprobe.cpp)
flmod_win32_dll(ehprobe)
target_link_libraries(ehprobe PRIVATE flmod::nlohmann_json)
