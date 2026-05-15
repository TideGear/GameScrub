/*
 * libevgate.so - LD_PRELOAD gate for GameHub Vibration Fix.
 *
 * GameHub's env builder applies LD_PRELOAD to the whole Wine process tree.
 * Some games, notably Shotgun King, exit when libevshim.so itself is mapped
 * into the game process. Only winedevice.exe needs the SDL rumble hook, so
 * this tiny library is what the env builder preloads. It checks /proc cmdline
 * and dlopen()s libevshim.so only for winedevice.exe.
 */

#define _GNU_SOURCE

#include <android/log.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#define LOG(fmt, ...) __android_log_print(ANDROID_LOG_INFO, "evgate", fmt, ##__VA_ARGS__)
#define LOGE(fmt, ...) __android_log_print(ANDROID_LOG_ERROR, "evgate", fmt, ##__VA_ARGS__)

static int ascii_tolower(int c)
{
    return (c >= 'A' && c <= 'Z') ? (c + 32) : c;
}

static int contains_case_insensitive(const char *haystack, size_t haystack_len, const char *needle)
{
    size_t needle_len = strlen(needle);
    if (needle_len == 0 || haystack_len < needle_len) return 0;

    for (size_t i = 0; i <= haystack_len - needle_len; i++) {
        size_t j = 0;
        while (j < needle_len &&
               ascii_tolower((unsigned char)haystack[i + j]) ==
               ascii_tolower((unsigned char)needle[j])) {
            j++;
        }
        if (j == needle_len) return 1;
    }
    return 0;
}

static ssize_t read_cmdline(char *buf, size_t cap)
{
    if (cap == 0) return -1;
    int fd = open("/proc/self/cmdline", O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;

    ssize_t n = read(fd, buf, cap - 1);
    close(fd);
    if (n < 0) return -1;
    buf[n] = '\0';
    return n;
}

static void make_printable_cmdline(char *buf, ssize_t n)
{
    for (ssize_t i = 0; i < n; i++) {
        if (buf[i] == '\0') buf[i] = ' ';
    }
    buf[n] = '\0';
}

static int sibling_path(char *out, size_t out_cap, const char *soname)
{
    Dl_info info;
    if (!dladdr((void *)&sibling_path, &info) || !info.dli_fname || !info.dli_fname[0]) {
        return 0;
    }

    const char *slash = strrchr(info.dli_fname, '/');
    if (!slash) return 0;
    size_t dir_len = (size_t)(slash - info.dli_fname);
    int n = snprintf(out, out_cap, "%.*s/%s", (int)dir_len, info.dli_fname, soname);
    return n > 0 && (size_t)n < out_cap;
}

__attribute__((constructor))
static void evgate_ctor(void)
{
    char cmd[4096];
    ssize_t n = read_cmdline(cmd, sizeof(cmd));
    if (n <= 0) {
        LOGE("loaded pid=%d cmdline unavailable: %s", (int)getpid(), strerror(errno));
        return;
    }

    int is_winedevice = contains_case_insensitive(cmd, (size_t)n, "winedevice.exe");
    if (!is_winedevice) {
        return;
    }

    make_printable_cmdline(cmd, n);
    LOG("winedevice target pid=%d cmd=%s", (int)getpid(), cmd);

    char path[PATH_MAX];
    void *handle = NULL;
    if (sibling_path(path, sizeof(path), "libevshim.so")) {
        handle = dlopen(path, RTLD_NOW | RTLD_GLOBAL);
        if (handle) {
            LOG("dlopen %s ok h=%p", path, handle);
            return;
        }
        LOGE("dlopen %s failed: %s", path, dlerror());
    }

    handle = dlopen("libevshim.so", RTLD_NOW | RTLD_GLOBAL);
    if (handle) {
        LOG("dlopen libevshim.so ok h=%p", handle);
        return;
    }
    LOGE("dlopen libevshim.so failed: %s", dlerror());
}
