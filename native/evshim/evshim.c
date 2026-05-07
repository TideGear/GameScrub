/*
 * libevshim.so — guest-side SDL rumble keepalive for BannerHub
 *
 * Adapted from GameNative PR #1214 (TideGear) for BannerHub's GameHub bridge.
 *
 * Why:
 *   Wine games' rumble path is: XInput → winebus.so → SDL_JoystickRumble →
 *   libvfs.so's registered VirtualJoystick.Rumble callback → AF_UNIX IPC →
 *   GameHub host → Android Vibrator. SDL2 internally auto-expires rumble
 *   ~1000 ms after each SDL_JoystickRumble call by invoking the Rumble
 *   callback again with (0, 0). The host treats that as "rumble stopped"
 *   and cancels the motors; the rumble cuts out at exactly 1 second on
 *   what should be sustained vibration.
 *
 * What this shim does:
 *   Interposes SDL_JoystickRumble via LD_PRELOAD. Records the last (low,
 *   high) per joystick. A background thread re-issues those values every
 *   500 ms with a 2000 ms duration so SDL's internal expiry is reset
 *   before it can fire. When (0, 0) arrives (real game-driven stop),
 *   the slot is cleared so keepalive stops re-firing.
 *
 *   Also wraps SDL_JoystickClose to evict slot entries when a game
 *   closes a controller — prevents keepalive from calling a stale
 *   joystick handle.
 *
 * Why this design (vs PR #1214's evshim):
 *   GameHub already has the SDL VirtualJoystick + IPC bridge wired up in
 *   libvfs.so's gamepad_manager — we don't need to register a new
 *   VirtualJoystickDesc.Rumble callback or write to gamepad.mem. We
 *   only need to keep SDL's timer from expiring.
 */

#define _GNU_SOURCE

#include <android/log.h>
#include <dlfcn.h>
#include <elf.h>
#include <errno.h>
#include <link.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

/* Opaque SDL2 type — we never dereference, just pass through. */
typedef struct SDL_Joystick SDL_Joystick;

#define MAX_SLOTS              4
#define KEEPALIVE_INTERVAL_US  (500 * 1000)   /* 500 ms */
#define KEEPALIVE_DURATION_MS  2000           /* must exceed SDL's ~1 s expiry */

/* Log volume note: Try 3 (commit 7f406d6) caused BannerHub's startup
 * watchdog to fire because each Wine subprocess on first polling tick
 * dumped 30-70 dl_iter[N] log lines via __android_log_print. Across ~10
 * Wine subprocesses that's hundreds of lines hitting logd in a few
 * hundred ms — Java's processExited() pipe-drainer hung for 2+ seconds
 * and BannerHub SIGKILL'd the whole Wine tree. This try restricts log
 * output to ~3 lines per process at startup + only-on-event lines later. */
#define LOG(fmt, ...) __android_log_print(ANDROID_LOG_INFO, "evshim", fmt, ##__VA_ARGS__)
#define LOGE(fmt, ...) __android_log_print(ANDROID_LOG_ERROR, "evshim", fmt, ##__VA_ARGS__)

static int  (*real_SDL_JoystickRumble)(SDL_Joystick *, uint16_t, uint16_t, uint32_t) = NULL;
static void (*real_SDL_JoystickClose)(SDL_Joystick *) = NULL;

struct slot {
    SDL_Joystick *js;   /* NULL when free */
    uint16_t      low;
    uint16_t      high;
};

static struct slot g_slots[MAX_SLOTS];
static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_once_t  g_keepalive_once = PTHREAD_ONCE_INIT;
static pthread_t       g_keepalive_tid;

static void resolve_real(void)
{
    if (!real_SDL_JoystickRumble) {
        real_SDL_JoystickRumble = dlsym(RTLD_NEXT, "SDL_JoystickRumble");
    }
    if (!real_SDL_JoystickClose) {
        real_SDL_JoystickClose = dlsym(RTLD_NEXT, "SDL_JoystickClose");
    }
}

/* Caller must hold g_lock. */
static int find_or_alloc_slot(SDL_Joystick *js)
{
    int free_idx = -1;
    for (int i = 0; i < MAX_SLOTS; i++) {
        if (g_slots[i].js == js) return i;
        if (g_slots[i].js == NULL && free_idx < 0) free_idx = i;
    }
    if (free_idx >= 0) {
        g_slots[free_idx].js = js;
        g_slots[free_idx].low = 0;
        g_slots[free_idx].high = 0;
    }
    return free_idx;
}

/* Caller must hold g_lock. */
static void free_slot_for(SDL_Joystick *js)
{
    for (int i = 0; i < MAX_SLOTS; i++) {
        if (g_slots[i].js == js) {
            g_slots[i].js = NULL;
            g_slots[i].low = 0;
            g_slots[i].high = 0;
            return;
        }
    }
}

static void *keepalive_thread(void *arg)
{
    (void)arg;
    LOG("keepalive thread running\n");

    for (;;) {
        usleep(KEEPALIVE_INTERVAL_US);

        /* Snapshot under the lock to keep the real SDL call outside the
         * critical section. Race window with a stop arriving mid-snapshot
         * is bounded to one keepalive tick — host will see one extra
         * (low, high) frame followed by the legitimate (0, 0). */
        struct slot snap[MAX_SLOTS];
        int snap_n = 0;
        pthread_mutex_lock(&g_lock);
        for (int i = 0; i < MAX_SLOTS; i++) {
            if (g_slots[i].js && (g_slots[i].low | g_slots[i].high)) {
                snap[snap_n++] = g_slots[i];
            }
        }
        pthread_mutex_unlock(&g_lock);

        if (!real_SDL_JoystickRumble) continue;

        for (int i = 0; i < snap_n; i++) {
            (void)real_SDL_JoystickRumble(snap[i].js, snap[i].low, snap[i].high,
                                          KEEPALIVE_DURATION_MS);
        }
    }
    return NULL;
}

static void start_keepalive(void)
{
    int rc = pthread_create(&g_keepalive_tid, NULL, keepalive_thread, NULL);
    LOG("pthread_create rc=%d (0=ok)\n", rc);
    if (rc == 0) {
        pthread_detach(g_keepalive_tid);
    } else {
        LOG("pthread_create failed: %s\n", strerror(errno));
    }
}

/* ─── interposed symbols ──────────────────────────────────────────────── */

int SDL_JoystickRumble(SDL_Joystick *js, uint16_t low_freq, uint16_t high_freq,
                       uint32_t duration_ms)
{
    /* Trace the first few calls so we can prove interposition is happening
     * (and via which thread). */
    static int s_diag_count = 0;
    if (s_diag_count < 6) {
        LOG("SDL_JoystickRumble call#%d: js=%p low=%u high=%u dur=%ums\n",
            s_diag_count, (void *)js, low_freq, high_freq, duration_ms);
        s_diag_count++;
    }

    resolve_real();
    if (!real_SDL_JoystickRumble) {
        LOG("real SDL_JoystickRumble not found via dlsym(RTLD_NEXT)\n");
        return -1;
    }

    /* Lazy-start the keepalive thread on the first rumble call so the
     * thread doesn't run in Wine processes that never touch a controller. */
    pthread_once(&g_keepalive_once, start_keepalive);

    pthread_mutex_lock(&g_lock);
    int idx = find_or_alloc_slot(js);
    if (idx >= 0) {
        if (low_freq == 0 && high_freq == 0) {
            /* Real game-driven stop — clear the slot so keepalive doesn't
             * keep firing. (SDL's auto-expiry never reaches us because the
             * keepalive resets SDL's internal timer well before the 1 s
             * mark; only the game's own SDL_JoystickRumble(_,0,0,_) call
             * gets here with zeros.) */
            g_slots[idx].js = NULL;
            g_slots[idx].low = 0;
            g_slots[idx].high = 0;
        } else {
            g_slots[idx].low = low_freq;
            g_slots[idx].high = high_freq;
        }
    }
    pthread_mutex_unlock(&g_lock);

    return real_SDL_JoystickRumble(js, low_freq, high_freq, duration_ms);
}

void SDL_JoystickClose(SDL_Joystick *js)
{
    resolve_real();

    pthread_mutex_lock(&g_lock);
    free_slot_for(js);
    pthread_mutex_unlock(&g_lock);

    if (real_SDL_JoystickClose) {
        real_SDL_JoystickClose(js);
    }
}

/* ─── GOT/PLT patcher for winebus.so — try 5: linker-free ────────────────
 *
 * The previous four iterations all touched the bionic linker in some way
 * (dl_iterate_phdr, dlopen interpose, dlsym during init) and each broke
 * something subtly different — deadlock, launch crash, input pipeline
 * stalling after first poll, etc. The bionic linker's interaction with
 * Wine's unusual loader is fragile.
 *
 * Try 5 avoids the linker entirely:
 *   - Reads /proc/self/maps to find winebus.so's load address (just file
 *     I/O, no locks held).
 *   - Walks the in-memory ELF directly: e_phoff → PT_DYNAMIC → DT_JMPREL,
 *     DT_SYMTAB, DT_STRTAB → PLT relocations → SDL_JoystickRumble GOT slot.
 *   - mprotect the page writable, overwrite the slot, mprotect back.
 *
 * Single one-shot attempt 5 seconds after libevshim's constructor, on a
 * detached thread that exits immediately after attempting. NO periodic
 * activity, NO dl_iterate_phdr, NO dlopen interpose, NO ongoing thread.
 * If 5 s is too soon (winebus.so not loaded yet), the patch silently
 * fails and we fall back to host-side suppression. From earlier traces
 * winebus.so loads ~62 ms after evshim's ctor in winedevice.exe, so 5 s
 * is generous.
 */

static int s_winebus_patched = 0;

/* Find the ELF base address (lowest mapping) of winebus.so in /proc/self/maps.
 * Returns 1 with *out_base set on success, 0 if not found. No locks.
 *
 * Why lowest, not r-xp: the bionic linker mmaps the .so as multiple
 * PT_LOAD segments; the first segment (lowest address) contains the
 * ELF header (file offset 0), typically mapped r--p. The r-xp mapping
 * is the .text segment, which lives at a higher address and starts
 * partway into the file — its first bytes are code, not ELFMAG. The
 * earlier filter on r-xp landed at 0x74f89ca000 which failed the
 * ELFMAG check in patch_winebus_at_base.
 *
 * Diagnostics: log every winebus.so candidate line so we can see (a)
 * whether the lib is loaded at all and (b) which mapping perms appear.
 * Limited to the first few candidates to avoid log spam. */
static int find_winebus_base(uintptr_t *out_base)
{
    FILE *f = fopen("/proc/self/maps", "r");
    if (!f) return 0;
    char line[1024];
    uintptr_t lowest = 0;
    int found = 0;
    int candidates = 0;
    while (fgets(line, sizeof(line), f)) {
        /* Format: "start-end perms offset dev inode pathname" */
        if (!strstr(line, "winebus.so")) continue;
        unsigned long start, end;
        if (sscanf(line, "%lx-%lx", &start, &end) != 2) continue;
        if (candidates < 6) {
            /* Strip trailing newline for cleaner log output. */
            size_t L = strlen(line);
            if (L > 0 && line[L - 1] == '\n') line[L - 1] = '\0';
            LOG("winebus map: %s", line);
            candidates++;
        }
        if (!found || (uintptr_t)start < lowest) {
            lowest = (uintptr_t)start;
            found = 1;
        }
    }
    fclose(f);
    if (found) *out_base = lowest;
    return found;
}

/* Read /proc/self/cmdline and copy the basename of argv[0] into `out` for
 * diagnostic logging. This lets us correlate which Wine PE module each
 * patcher firing corresponds to (services.exe, winedevice.exe, etc.). */
static void read_self_cmdline(char *out, size_t out_size)
{
    out[0] = '\0';
    FILE *f = fopen("/proc/self/cmdline", "r");
    if (!f) return;
    char buf[512];
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    if (n == 0) return;
    buf[n] = '\0';
    /* cmdline uses NUL separators; we just want enough to identify. Replace
     * NULs with spaces for readability, capped at out_size. */
    for (size_t i = 0; i < n && i + 1 < out_size; i++) {
        out[i] = buf[i] ? buf[i] : ' ';
        out[i + 1] = '\0';
    }
}

/* Patch winebus.so so its calls to SDL_JoystickRumble go through our wrapper.
 *
 * winebus.so doesn't link against libSDL2-2.0.so directly (no NEEDED entry,
 * no relocation for SDL_JoystickRumble in either DT_JMPREL or DT_RELA — the
 * previous iteration logged "not in JMPREL (n=34)" and "not in RELA (n=60)").
 * Instead it calls dlopen("libSDL2-2.0.so") in sdl_bus_init, then dlsym's
 * each function name into a static `pSDL_*` table in .bss. The actual call
 * sites do `(*pSDL_JoystickRumble)(...)`. So there's no GOT entry to patch
 * via relocations — we have to patch the function-pointer table after
 * winebus has populated it.
 *
 * Strategy:
 *   1. Walk PT_LOAD program headers in memory; find writable segments.
 *   2. Scan each writable segment 8-byte-aligned for any qword matching
 *      real_SDL_JoystickRumble (libSDL2's exported symbol address — what
 *      winebus's dlsym call returned for the same name).
 *   3. mprotect, overwrite each match with our wrapper, mprotect back.
 *
 * Why scanning is safe: real_SDL_JoystickRumble is a 64-bit address. False
 * positives in random data are ~1/2^64 — effectively impossible. We also
 * confine the scan to winebus.so's own writable segments, so we never
 * touch other libraries' data. */
static int patch_winebus_at_base(uintptr_t base)
{
    const ElfW(Ehdr) *eh = (const ElfW(Ehdr) *)base;
    if (eh->e_ident[EI_MAG0] != ELFMAG0 || eh->e_ident[EI_MAG1] != ELFMAG1 ||
        eh->e_ident[EI_MAG2] != ELFMAG2 || eh->e_ident[EI_MAG3] != ELFMAG3) {
        LOGE("winebus base=%p not ELF", (void *)base);
        return 0;
    }
    if (!real_SDL_JoystickRumble) {
        LOG("winebus: real_SDL_JoystickRumble unresolved — skipping scan");
        return 0;
    }

    const ElfW(Phdr) *ph = (const ElfW(Phdr) *)(base + eh->e_phoff);
    long page_size = sysconf(_SC_PAGESIZE);
    uintptr_t target = (uintptr_t)real_SDL_JoystickRumble;
    uintptr_t replacement = (uintptr_t)&SDL_JoystickRumble;
    int total_segments = 0;
    size_t total_bytes = 0;
    int patched = 0;

    for (int i = 0; i < eh->e_phnum; i++) {
        if (ph[i].p_type != PT_LOAD) continue;
        if (!(ph[i].p_flags & PF_W)) continue;

        uintptr_t seg_start = base + ph[i].p_vaddr;
        size_t    seg_size  = ph[i].p_memsz;
        if (seg_size < sizeof(uintptr_t)) continue;
        total_segments++;
        total_bytes += seg_size;

        /* Scan 8-byte aligned. seg_start is page-aligned by ELF rules so
         * already qword-aligned, but be defensive. */
        uintptr_t scan_start = (seg_start + 7) & ~(uintptr_t)7;
        uintptr_t scan_end   = seg_start + seg_size - sizeof(uintptr_t);

        for (uintptr_t p = scan_start; p <= scan_end; p += sizeof(uintptr_t)) {
            uintptr_t *slot = (uintptr_t *)p;
            if (*slot != target) continue;

            uintptr_t page_addr = p & ~((uintptr_t)page_size - 1);
            if (mprotect((void *)page_addr, (size_t)page_size,
                         PROT_READ | PROT_WRITE) != 0) {
                LOGE("winebus scan: mprotect rw failed at %p: %s",
                     (void *)page_addr, strerror(errno));
                continue;
            }
            uintptr_t old = *slot;
            *slot = replacement;
            mprotect((void *)page_addr, (size_t)page_size, PROT_READ | PROT_WRITE);
            /* Leave .data/.bss writable — winebus may legitimately rewrite
             * its own pSDL table during shutdown. Reverting to PROT_READ
             * would crash it. */

            LOG("got_patch winebus.so: pSDL_JoystickRumble slot=%p old=0x%lx new=0x%lx",
                (void *)slot, (unsigned long)old, (unsigned long)replacement);
            patched++;
        }
    }

    LOG("winebus scan: %d writable segments, %zu bytes, %d slots patched",
        total_segments, total_bytes, patched);
    return patched > 0;
}

/* One-shot patcher thread. Runs exactly once, 5 seconds after spawn,
 * then exits. No polling, no periodic activity. */
static void *one_shot_patcher_thread(void *arg)
{
    (void)arg;
    sleep(5);
    if (s_winebus_patched) return NULL;

    char cmd[256];
    read_self_cmdline(cmd, sizeof(cmd));
    LOG("patcher fire pid=%d cmd=%s", (int)getpid(), cmd);

    uintptr_t base = 0;
    if (!find_winebus_base(&base)) {
        LOG("patcher: winebus.so not loaded in pid=%d", (int)getpid());
        return NULL;
    }
    LOG("patcher: winebus.so base=0x%lx pid=%d", (unsigned long)base, (int)getpid());
    if (patch_winebus_at_base(base)) {
        s_winebus_patched = 1;
    }
    return NULL;
}

/* Force libSDL2-2.0.so into the global linker namespace before libvfs.so
 * gets a chance to dlopen it RTLD_LOCAL. Without this, libvfs.so's later
 * dlopen with default flags creates a private namespace; winebus.so's
 * NEEDED libSDL2 dependency then reuses that private instance and winebus's
 * SDL_JoystickRumble lookups never reach our LD_PRELOAD'd shim.
 *
 * We try the unqualified name first (relying on the linker's search path)
 * then fall back to an absolute path derived from WINEMU_ROOT_FS env var. */
static void preload_sdl_global(void)
{
    void *h = dlopen("libSDL2-2.0.so", RTLD_NOW | RTLD_GLOBAL);
    if (h) {
        LOG("preload: dlopen libSDL2-2.0.so RTLD_GLOBAL ok h=%p\n", h);
        return;
    }
    const char *err1 = dlerror();
    const char *root = getenv("WINEMU_ROOT_FS");
    if (root && *root) {
        char path[512];
        snprintf(path, sizeof(path), "%s/files/usr/lib/libSDL2-2.0.so", root);
        h = dlopen(path, RTLD_NOW | RTLD_GLOBAL);
        if (h) {
            LOG("preload: dlopen %s RTLD_GLOBAL ok h=%p\n", path, h);
            return;
        }
        LOG("preload: both dlopens failed (1) %s (2) %s\n", err1 ? err1 : "?", dlerror());
    } else {
        LOG("preload: dlopen libSDL2-2.0.so failed (%s) and WINEMU_ROOT_FS not set\n",
            err1 ? err1 : "?");
    }
}

__attribute__((constructor))
static void evshim_ctor(void)
{
    LOG("loaded pid=%d", (int)getpid());
    /* Promote libSDL2 to global scope BEFORE resolve_real so dlsym(RTLD_NEXT)
     * has something to find. */
    preload_sdl_global();
    resolve_real();
    LOG("ctor resolved real_SDL_JoystickRumble=%p", (void *)real_SDL_JoystickRumble);

    /* Spawn the one-shot patcher thread. Sleeps 5 s, reads /proc/self/maps
     * to find winebus.so, walks its in-memory ELF, patches the GOT slot.
     * No linker calls. Single attempt. Thread exits after one try.
     *
     * In Wine subprocesses that don't load winebus.so (most of them),
     * find_winebus_base returns 0 and the thread quietly exits. Only
     * winedevice.exe will actually patch.
     */
    pthread_t tid;
    if (pthread_create(&tid, NULL, one_shot_patcher_thread, NULL) == 0) {
        pthread_detach(tid);
    } else {
        LOGE("ctor: pthread_create for patcher failed: %s", strerror(errno));
    }
}
