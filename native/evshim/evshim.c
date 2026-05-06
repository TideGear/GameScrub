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

/* Use Android log instead of stderr. Wine subprocess stderr is not always
 * piped to logcat (e.g., winedevice.exe — exactly the process where
 * winebus.so loads — was silent in our previous diagnostic build). Direct
 * logcat via __android_log_print guarantees we see every event. */
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

/* ─── GOT/PLT patcher for winebus.so ─────────────────────────────────────
 *
 * LD_PRELOAD interposition is not enough on this Wine fork: libvfs.so's
 * dlopen of libSDL2 puts its symbols in a private linker namespace that
 * winebus.so's NEEDED libSDL2 reuses, so winebus's SDL_JoystickRumble
 * lookups never reach our globally preloaded wrapper.
 *
 * Workaround: at runtime, walk winebus.so's PLT relocation table via
 * dl_iterate_phdr, find the GOT slot for SDL_JoystickRumble, mprotect
 * the page writable, atomically overwrite the slot with the address of
 * our wrapper, restore protections. Subsequent winebus.so calls go
 * through our wrapper regardless of which libSDL2 instance was bound at
 * load time.
 *
 * Two trigger paths to catch winebus.so's load:
 *   1) dlopen interposition — primary. Catches winebus.so the moment it
 *      loads, regardless of which Wine subprocess does the loading.
 *   2) Slow polling (every 2 s, permanent) — fallback in case Wine's
 *      loader uses an internal mechanism that bypasses standard dlopen.
 */

typedef struct {
    const char *target_lib;
    const char *target_sym;
    void       *new_func;
    int         patched;
    int         enumerate;
    int         enum_count;
} got_patch_ctx_t;

static int s_winebus_patched = 0;

static int got_patch_iter(struct dl_phdr_info *info, size_t size, void *data)
{
    (void)size;
    got_patch_ctx_t *ctx = (got_patch_ctx_t *)data;
    if (ctx->patched) return 1;

    const char *name = info->dlpi_name;
    if (ctx->enumerate) {
        LOG("dl_iter[%d]: name=%s base=%p",
            ctx->enum_count++, name ? name : "(null)", (void *)info->dlpi_addr);
    }
    if (!name || !*name) return 0;
    if (!strstr(name, ctx->target_lib)) return 0;
    LOG("dl_iter MATCH: %s base=%p", name, (void *)info->dlpi_addr);

    /* Find PT_DYNAMIC */
    const ElfW(Phdr) *dynp = NULL;
    for (int i = 0; i < info->dlpi_phnum; i++) {
        if (info->dlpi_phdr[i].p_type == PT_DYNAMIC) {
            dynp = &info->dlpi_phdr[i];
            break;
        }
    }
    if (!dynp) return 0;

    ElfW(Dyn) *dyn = (ElfW(Dyn) *)((uintptr_t)info->dlpi_addr + dynp->p_vaddr);

    const ElfW(Sym) *symtab = NULL;
    const char      *strtab = NULL;
    const uint8_t   *jmprel = NULL;
    size_t           jmprelsz = 0;
    int              pltrel_type = DT_RELA;

    for (ElfW(Dyn) *d = dyn; d->d_tag != DT_NULL; d++) {
        switch (d->d_tag) {
            case DT_SYMTAB:   symtab = (const ElfW(Sym) *)d->d_un.d_ptr; break;
            case DT_STRTAB:   strtab = (const char *)d->d_un.d_ptr; break;
            case DT_JMPREL:   jmprel = (const uint8_t *)d->d_un.d_ptr; break;
            case DT_PLTRELSZ: jmprelsz = d->d_un.d_val; break;
            case DT_PLTREL:   pltrel_type = (int)d->d_un.d_val; break;
            default: break;
        }
    }
    if (!symtab || !strtab || !jmprel || jmprelsz == 0) {
        LOG("got_patch %s: dyn missing symtab/strtab/jmprel", name);
        return 0;
    }
    if (pltrel_type != DT_RELA) {
        LOG("got_patch %s: PLT type=%d not RELA", name, pltrel_type);
        return 0;
    }

    size_t entsize = sizeof(ElfW(Rela));
    size_t n = jmprelsz / entsize;
    for (size_t i = 0; i < n; i++) {
        const ElfW(Rela) *r = (const ElfW(Rela) *)(jmprel + i * entsize);
        size_t sym_idx = ELF64_R_SYM(r->r_info);
        const char *sym_name = strtab + symtab[sym_idx].st_name;
        if (strcmp(sym_name, ctx->target_sym) != 0) continue;

        void **slot = (void **)((uintptr_t)info->dlpi_addr + r->r_offset);
        void  *old  = *slot;

        long page_size = sysconf(_SC_PAGESIZE);
        uintptr_t page_addr = (uintptr_t)slot & ~((uintptr_t)page_size - 1);
        if (mprotect((void *)page_addr, (size_t)page_size,
                     PROT_READ | PROT_WRITE) != 0) {
            LOGE("got_patch %s: mprotect RW failed: %s", name, strerror(errno));
            return 0;
        }
        *slot = ctx->new_func;
        mprotect((void *)page_addr, (size_t)page_size, PROT_READ);

        LOG("got_patch %s: %s GOT slot=%p old=%p new=%p",
            name, ctx->target_sym, (void *)slot, old, ctx->new_func);
        ctx->patched = 1;
        return 1;
    }

    LOG("got_patch %s: %s not in PLT relocations (n=%zu)",
        name, ctx->target_sym, n);
    return 0;
}

static int try_patch_winebus(int enumerate)
{
    if (s_winebus_patched) return 1;
    got_patch_ctx_t ctx = {
        .target_lib = "winebus.so",
        .target_sym = "SDL_JoystickRumble",
        .new_func   = (void *)&SDL_JoystickRumble,
        .patched    = 0,
        .enumerate  = enumerate,
        .enum_count = 0,
    };
    dl_iterate_phdr(got_patch_iter, &ctx);
    if (ctx.enumerate) {
        LOG("dl_iter: enumerated %d libraries (winebus.so %s)",
            ctx.enum_count, ctx.patched ? "PATCHED" : "not found");
    }
    if (ctx.patched) {
        s_winebus_patched = 1;
        return 1;
    }
    return 0;
}

/* Slow permanent polling fallback. 2 s cadence is light enough to avoid
 * the linker-lock contention that bricked controller detection in our
 * earlier 50 ms / 60 s attempt. */
static void *got_patcher_thread(void *arg)
{
    (void)arg;
    LOG("got_patcher: thread started, polling for winebus.so every 2s until patched");
    int attempt = 0;
    while (!s_winebus_patched) {
        sleep(2);
        attempt++;
        /* Enumerate every library on the first attempt and again every
         * 30 attempts (~1 minute) so we can see what the dynamic loader
         * is actually showing us. Cheap silent attempts in between. */
        int enumerate = (attempt == 1 || (attempt % 30 == 0));
        try_patch_winebus(enumerate);
    }
    LOG("got_patcher: thread exiting (patched after %d attempts)", attempt);
    return NULL;
}

/* ─── dlopen interposition ────────────────────────────────────────────────
 *
 * Primary trigger: catches winebus.so the moment any code dlopens it,
 * regardless of which Wine subprocess. Removes the polling-window timing
 * race entirely — by the time Wine's HID stack tries to call
 * SDL_JoystickRumble through winebus.so's PLT, the GOT slot is already
 * patched.
 */

static void *(*real_dlopen)(const char *, int) = NULL;
static __thread int t_in_dlopen = 0;

void *dlopen(const char *filename, int flag)
{
    if (!real_dlopen) {
        real_dlopen = dlsym(RTLD_NEXT, "dlopen");
        if (!real_dlopen) {
            LOGE("real dlopen lookup failed");
            return NULL;
        }
    }

    void *h = real_dlopen(filename, flag);

    if (h && filename && !s_winebus_patched && !t_in_dlopen) {
        if (strstr(filename, "winebus.so")) {
            t_in_dlopen = 1;
            LOG("dlopen interposed: winebus.so loaded (%s)", filename);
            try_patch_winebus(/*enumerate=*/0);
            t_in_dlopen = 0;
        }
    }
    return h;
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
    LOG("loaded (MAX_SLOTS=%d, interval=%dms, duration=%dms) pid=%d",
        MAX_SLOTS, KEEPALIVE_INTERVAL_US / 1000, KEEPALIVE_DURATION_MS, (int)getpid());
    /* Promote libSDL2 to global scope BEFORE resolve_real so dlsym(RTLD_NEXT)
     * has something to find. */
    preload_sdl_global();
    resolve_real();
    LOG("ctor resolved real_SDL_JoystickRumble=%p real_SDL_JoystickClose=%p",
        (void *)real_SDL_JoystickRumble, (void *)real_SDL_JoystickClose);

    /* Try patching immediately (handles the unlikely case that winebus.so
     * is already loaded — e.g., this constructor runs after the HID stack
     * spawned). Then start the polling fallback. The dlopen interpose
     * registered above is the primary trigger. */
    if (!try_patch_winebus(/*enumerate=*/0)) {
        pthread_t tid;
        if (pthread_create(&tid, NULL, got_patcher_thread, NULL) == 0) {
            pthread_detach(tid);
        } else {
            LOGE("ctor: pthread_create for got_patcher failed: %s", strerror(errno));
        }
    }
}
