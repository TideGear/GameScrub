/*
 * libsdlpreload.so — minimal SDL2 RTLD_GLOBAL helper for GameHub 5.3.5.
 *
 * Stock 5.3.5's Wine setup leaves libSDL2-2.0.so reachable only from
 * libvfs.so's private dlopen namespace (RTLD_LOCAL). SteamAgent2's Wine PE
 * then can't resolve SDL symbols cleanly and reports init_failed=1004 to
 * GameHub's Java-side SteamAgentServer, blocking the Steam-button launch
 * path. 6.0.x fixed this natively; 5.3.5 didn't.
 *
 * BannerHub's libevshim.so worked around it as a side effect of its
 * preload_sdl_global() call; once we removed libevshim entirely in the
 * preload-free refactor, the side effect disappeared and the regression
 * surfaced on 5.3.5.
 *
 * This tiny library is shipped on 5.3.5 builds only. Its constructor does
 * exactly one thing:
 *     dlopen("libSDL2-2.0.so", RTLD_NOW | RTLD_GLOBAL)
 * for Wine subprocesses that plausibly need SDL2 (winedevice.exe, the
 * game's own .exe, SteamAgent2 PE). No SDL interposition, no keepalive
 * thread, no winebus GOT patcher — sustained rumble + dual-motor dispatch
 * are already handled by the on-disk winebus duration patch and
 * BhVibrationController's smali dispatch hooks, both architecture-agnostic.
 *
 * 6.0.x builds do NOT ship this library and do NOT add it to LD_PRELOAD —
 * those builds stay strictly preload-free so games like Shotgun King that
 * silently exit on any extra .so mapping in their Wine address space keep
 * working there.
 *
 * Process skip list mirrors BannerHub's libevshim: wineserver, services.exe,
 * plugplay.exe, svchost.exe, explorer.exe, rpcss.exe, tabtip.exe, jwm —
 * none of those need SDL2 in their address space. Skipping them avoids
 * loading libSDL2 + transitives (libpulse, libasound, libdbus, etc.) into
 * processes that will never use it.
 */

#define _GNU_SOURCE

#include <android/log.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define LOG(fmt, ...)  __android_log_print(ANDROID_LOG_INFO,  "sdlpreload", fmt, ##__VA_ARGS__)
#define LOGE(fmt, ...) __android_log_print(ANDROID_LOG_ERROR, "sdlpreload", fmt, ##__VA_ARGS__)

static void read_self_cmdline(char *out, size_t out_size)
{
    if (out_size == 0) return;
    out[0] = '\0';
    int fd = open("/proc/self/cmdline", O_RDONLY | O_CLOEXEC);
    if (fd < 0) return;
    ssize_t n = read(fd, out, out_size - 1);
    close(fd);
    if (n <= 0) return;
    out[n] = '\0';
    /* cmdline uses NUL separators; convert to spaces for substring match. */
    for (ssize_t i = 0; i < n; i++) {
        if (out[i] == '\0') out[i] = ' ';
    }
}

static int proc_needs_sdl(void)
{
    char cmd[256];
    read_self_cmdline(cmd, sizeof(cmd));
    static const char * const skip_markers[] = {
        "wineserver",
        "services.exe",
        "plugplay.exe",
        "svchost.exe",
        "explorer.exe",
        "rpcss.exe",
        "tabtip.exe",
        "/jwm ",
        "/jwm",
        NULL,
    };
    for (int i = 0; skip_markers[i] != NULL; i++) {
        if (strstr(cmd, skip_markers[i]) != NULL) {
            return 0;
        }
    }
    return 1;
}

__attribute__((constructor))
static void sdlpreload_ctor(void)
{
    if (!proc_needs_sdl()) return;

    void *h = dlopen("libSDL2-2.0.so", RTLD_NOW | RTLD_GLOBAL);
    if (h != NULL) {
        LOG("dlopen libSDL2-2.0.so RTLD_GLOBAL ok h=%p", h);
        return;
    }
    const char *err1 = dlerror();

    const char *root = getenv("WINEMU_ROOT_FS");
    if (root != NULL && root[0] != '\0') {
        char path[512];
        snprintf(path, sizeof(path), "%s/files/usr/lib/libSDL2-2.0.so", root);
        h = dlopen(path, RTLD_NOW | RTLD_GLOBAL);
        if (h != NULL) {
            LOG("dlopen %s RTLD_GLOBAL ok h=%p", path, h);
            return;
        }
        LOGE("both dlopens failed (1) %s (2) %s",
             err1 != NULL ? err1 : "?",
             dlerror());
    } else {
        LOGE("dlopen libSDL2-2.0.so failed (%s) and WINEMU_ROOT_FS unset",
             err1 != NULL ? err1 : "?");
    }
}
