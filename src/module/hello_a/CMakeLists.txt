# hello_a.dll: Track A shape (FLUF combined module). Built by the win32-trackA preset only.
flmod_track_only(A)

add_library(hello_a SHARED hello_a.cpp)
flmod_fluf_module(hello_a)
