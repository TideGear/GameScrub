cmake_minimum_required(VERSION 3.20)
project(sdlpreload C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

add_library(sdlpreload SHARED sdlpreload.c)

target_link_libraries(sdlpreload PRIVATE log dl)

set_target_properties(sdlpreload PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    LINK_FLAGS "-Wl,--no-undefined -Wl,-z,now -Wl,-z,relro -Wl,-z,noexecstack"
)

target_compile_options(sdlpreload PRIVATE
    -Wall
    -Werror
    -fvisibility=hidden
    -Os
)
