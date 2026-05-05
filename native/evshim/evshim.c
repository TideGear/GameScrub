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

#define LOG(fmt, ...) do { \
    char _b[256]; \
    int _n = snprintf(_b, sizeof(_b), "[evshim] " fmt, ##__VA_ARGS__); \
    if (_n > 0) { (void)write(STDERR_FILENO, _b, (size_t)_n); } \
} while (0)

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

/* ─── GOT/PLT patcher ─────────────────────────────────────────────────────
 *
 * LD_PRELOAD interposition is not enough on Android: libvfs.so dlopens
 * libSDL2-2.0.so in a private linker namespace, and winebus.so's NEEDED
 * libSDL2 reference reuses that private instance — its SDL_JoystickRumble
 * lookup goes through the private namespace and never finds our globally
 * preloaded wrapper.
 *
 * Instead we walk winebus.so's PLT relocation table at runtime, find the
 * GOT slot for SDL_JoystickRumble, and overwrite it with the address of
 * our wrapper. Subsequent calls from winebus.so go through our wrapper
 * regardless of what libSDL2 instance was bound at load time.
 *
 * winebus.so isn't loaded at our constructor time, so a polling thread
 * watches dl_iterate_phdr until it appears, then patches and exits.
 */

typedef struct {
    const char *target_lib;   /* substring match against dlpi_name */
    const char *target_sym;   /* exact symbol name */
    void       *new_func;     /* address of our wrapper */
    int         patched;      /* output: 1 on success */
} got_patch_ctx_t;

static int got_patch_iter(struct dl_phdr_info *info, size_t size, void *data)
{
    (void)size;
    got_patch_ctx_t *ctx = (got_patch_ctx_t *)data;
    if (ctx->patched) return 1;

    const char *name = info->dlpi_name;
    if (!name || !*name) return 0;
    if (!strstr(name, ctx->target_lib)) return 0;

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
    int              pltrel_type = DT_RELA;  /* aarch64 default */

    /* On Android, bionic resolves DT_SYMTAB/DT_STRTAB/DT_JMPREL d_ptr to
     * absolute runtime addresses. */
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
        LOG("got_patch %s: dyn missing symtab/strtab/jmprel\n", name);
        return 0;
    }

    /* Walk PLT relocations. aarch64 uses RELA. */
    if (pltrel_type != DT_RELA) {
        LOG("got_patch %s: PLT type=%d not RELA\n", name, pltrel_type);
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

        /* Make page writable */
        long page_size = sysconf(_SC_PAGESIZE);
        uintptr_t page_addr = (uintptr_t)slot & ~((uintptr_t)page_size - 1);
        if (mprotect((void *)page_addr, (size_t)page_size,
                     PROT_READ | PROT_WRITE) != 0) {
            LOG("got_patch %s: mprotect RW failed: %s\n", name, strerror(errno));
            return 0;
        }
        *slot = ctx->new_func;
        /* Best-effort restore. Leaving RW is harmless if it fails. */
        mprotect((void *)page_addr, (size_t)page_size, PROT_READ);

        LOG("got_patch %s: %s GOT slot=%p old=%p new=%p\n",
            name, ctx->target_sym, (void *)slot, old, ctx->new_func);
        ctx->patched = 1;
        return 1;
    }

    LOG("got_patch %s: %s not in PLT relocations (n=%zu)\n",
        name, ctx->target_sym, n);
    return 0;
}

static int s_winebus_patched = 0;

static int try_patch_winebus(void)
{
    if (s_winebus_patched) return 1;
    got_patch_ctx_t ctx = {
        .target_lib = "winebus.so",
        .target_sym = "SDL_JoystickRumble",
        .new_func   = (void *)&SDL_JoystickRumble,
        .patched    = 0,
    };
    dl_iterate_phdr(got_patch_iter, &ctx);
    if (ctx.patched) {
        s_winebus_patched = 1;
        return 1;
    }
    return 0;
}

static void *got_patcher_thread(void *arg)
{
    (void)arg;
    LOG("got_patcher: thread running, polling for winebus.so\n");
    /* Poll for up to 60 seconds at 50 ms cadence. winebus.so loads when
     * Wine's HID stack initializes, typically within a few seconds of
     * Wine startup. */
    for (int i = 0; i < 1200; i++) {
        if (try_patch_winebus()) {
            LOG("got_patcher: winebus.so patched (after %d ticks)\n", i);
            return NULL;
        }
        usleep(50 * 1000);
    }
    LOG("got_patcher: gave up after 60 s\n");
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
    LOG("loaded (MAX_SLOTS=%d, interval=%dms, duration=%dms)\n",
        MAX_SLOTS, KEEPALIVE_INTERVAL_US / 1000, KEEPALIVE_DURATION_MS);
    /* Promote libSDL2 to global scope BEFORE resolve_real so dlsym(RTLD_NEXT)
     * has something to find. */
    preload_sdl_global();
    resolve_real();
    LOG("ctor resolved real_SDL_JoystickRumble=%p real_SDL_JoystickClose=%p\n",
        (void *)real_SDL_JoystickRumble, (void *)real_SDL_JoystickClose);

    /* Try patching immediately (covers the case where winebus.so already
     * loaded before libevshim — unlikely but harmless). Then spawn a
     * polling thread to handle the common case where winebus.so loads
     * later when Wine's HID stack initializes. */
    if (!try_patch_winebus()) {
        pthread_t tid;
        if (pthread_create(&tid, NULL, got_patcher_thread, NULL) == 0) {
            pthread_detach(tid);
        } else {
            LOG("ctor: failed to spawn got_patcher thread: %s\n", strerror(errno));
        }
    }
}
