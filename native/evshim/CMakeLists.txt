cmake_minimum_required(VERSION 3.18)
project(evshim C)

# libevshim.so — guest-side SDL rumble keepalive shim, LD_PRELOAD'd into Wine.
# See evshim.c header for the why.

add_library(evshim SHARED evshim.c)

# Visibility: HIDDEN by default. We don't use the LD_PRELOAD symbol-
# interposition path — winebus.so dlopens libSDL2 and dlsym's each
# pSDL_* function pointer; the patcher rewrites those pointers to our
# wrappers directly (function-pointer cast, not symbol resolution). So
# exporting SDL_JoystickRumble / SDL_JoystickClose from libevshim is
# dead weight, AND it lets any unrelated code in the host process
# (Wine's HID search, Box64's wrapped-lib resolver, game dlopen)
# resolve "SDL_JoystickRumble" against us via the global namespace and
# call our entry points with no real SDL state — empirically this
# triggered Shotgun King's host process to silently exit at launch.
# Hiding the exports lets the patcher still write &SDL_JoystickRumble
# (compile-time address, no symbol-table lookup) while making
# libevshim invisible to any dlsym/RTLD_GLOBAL chain.
target_compile_options(evshim PRIVATE
    -O2 -Wall -Wextra -fPIC
    -fvisibility=hidden
)

# pthread is part of bionic libc on Android — no separate libpthread to link.
# dl is a real lib we need for dlsym/RTLD_NEXT.
# log is needed for __android_log_print (we log to logcat directly because
# Wine subprocess stderr isn't always piped to logcat).
target_link_libraries(evshim PRIVATE dl log)

set_target_properties(evshim PROPERTIES
    LINK_FLAGS "-Wl,--as-needed"
)
