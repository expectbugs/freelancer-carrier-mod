# hello_b.dll: Track B shape (plain dacom DLL). Built by the win32-trackB preset only.
flmod_track_only(B)

add_library(hello_b SHARED hello_b.cpp hello_b.rc)
flmod_dacom_dll(hello_b)
flmod_rc_includes(hello_b)
