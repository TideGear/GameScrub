cmake_minimum_required(VERSION 3.18)
project(evshim C)

# libevshim.so — guest-side SDL rumble keepalive shim, LD_PRELOAD'd into Wine.
# See evshim.c header for the why.

add_library(evshim SHARED evshim.c)

# Default visibility: SDL_JoystickRumble and SDL_JoystickClose must be
# exported so the dynamic linker picks them up via LD_PRELOAD interposition.
# Internal helpers are already `static` so they don't leak.
target_compile_options(evshim PRIVATE -O2 -Wall -Wextra -fPIC)

target_link_libraries(evshim PRIVATE dl pthread)

set_target_properties(evshim PROPERTIES
    LINK_FLAGS "-Wl,--as-needed"
)
