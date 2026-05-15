cmake_minimum_required(VERSION 3.18)
project(evshim C)

# libevgate.so is LD_PRELOAD'd into Wine. It dlopen()s libevshim.so only in
# winedevice.exe, where evshim patches winebus and keeps SDL rumble alive.

add_library(evshim SHARED evshim.c)
add_library(evgate SHARED evgate.c)

# Default visibility: SDL_JoystickRumble and SDL_JoystickClose must be
# exported so the dynamic linker picks them up via LD_PRELOAD interposition.
# Internal helpers are already `static` so they don't leak.
target_compile_options(evshim PRIVATE -O2 -Wall -Wextra -fPIC)
target_compile_options(evgate PRIVATE -O2 -Wall -Wextra -fPIC -fvisibility=hidden)

# pthread is part of bionic libc on Android — no separate libpthread to link.
# dl is a real lib we need for dlsym/RTLD_NEXT.
# log is needed for __android_log_print (we log to logcat directly because
# Wine subprocess stderr isn't always piped to logcat).
target_link_libraries(evshim PRIVATE dl log)
target_link_libraries(evgate PRIVATE dl log)

set_target_properties(evshim PROPERTIES
    LINK_FLAGS "-Wl,--as-needed"
)
set_target_properties(evgate PROPERTIES
    LINK_FLAGS "-Wl,--as-needed"
)
