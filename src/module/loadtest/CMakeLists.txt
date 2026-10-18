# loadtest.exe: LoadLibrary/GetProcAddress/call proof tool. Built by both win32 presets.
flmod_win32_only()

add_executable(loadtest loadtest.cpp)
flmod_win32_exe(loadtest)
