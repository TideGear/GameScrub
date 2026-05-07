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

/* Walk the in-memory ELF at `base`, find the SDL_JoystickRumble GOT slot,
 * and patch it to point at our wrapper. Pure pointer arithmetic + mprotect;
 * no linker calls. Returns 1 on success. */
static int patch_winebus_at_base(uintptr_t base)
{
    const ElfW(Ehdr) *eh = (const ElfW(Ehdr) *)base;
    if (eh->e_ident[EI_MAG0] != ELFMAG0 || eh->e_ident[EI_MAG1] != ELFMAG1 ||
        eh->e_ident[EI_MAG2] != ELFMAG2 || eh->e_ident[EI_MAG3] != ELFMAG3) {
        LOGE("winebus base=%p not ELF", (void *)base);
        return 0;
    }

    const ElfW(Phdr) *ph = (const ElfW(Phdr) *)(base + eh->e_phoff);
    const ElfW(Phdr) *dynp = NULL;
    for (int i = 0; i < eh->e_phnum; i++) {
        if (ph[i].p_type == PT_DYNAMIC) {
            dynp = &ph[i];
            break;
        }
    }
    if (!dynp) {
        LOG("winebus: no PT_DYNAMIC");
        return 0;
    }

    ElfW(Dyn) *dyn = (ElfW(Dyn) *)(base + dynp->p_vaddr);

    /* Bionic's linker does NOT rewrite the in-memory dynamic table — it
     * reads d_un.d_ptr as a load-bias-relative offset and adds load_bias
     * at the consumer site (see soinfo::prelink_image in AOSP linker.cpp).
     * So we must add `base` ourselves. The earlier version of this code
     * treated d_ptr as already-absolute, which dereferenced tiny offsets
     * like 0x1000 as pointers and SIGSEGV'd winedevice.exe — taking out
     * the HID stack and breaking all controller input. */
    const ElfW(Sym) *symtab = NULL;
    const char      *strtab = NULL;
    const uint8_t   *jmprel = NULL;
    size_t           jmprelsz = 0;
    int              pltrel_type = DT_RELA;
    /* DT_RELA holds the regular dynamic relocation table — needed for
     * non-PLT GOT references (R_AARCH64_GLOB_DAT). When the compiler
     * emits a function call as an indirect GOT load instead of a PLT
     * jump (e.g. -fno-plt, or weak refs, or some Wine PE-bridge code),
     * the relocation is in DT_RELA, not DT_JMPREL. The previous
     * iteration only walked DT_JMPREL and missed it — winebus.so
     * logged "n=34" PLT relocs but no SDL_JoystickRumble entry. */
    const uint8_t   *rela = NULL;
    size_t           relasz = 0;
    size_t           relaent = sizeof(ElfW(Rela));

    for (ElfW(Dyn) *d = dyn; d->d_tag != DT_NULL; d++) {
        switch (d->d_tag) {
            case DT_SYMTAB:   symtab = (const ElfW(Sym) *)(base + d->d_un.d_ptr); break;
            case DT_STRTAB:   strtab = (const char *)(base + d->d_un.d_ptr); break;
            case DT_JMPREL:   jmprel = (const uint8_t *)(base + d->d_un.d_ptr); break;
            case DT_PLTRELSZ: jmprelsz = d->d_un.d_val; break;
            case DT_PLTREL:   pltrel_type = (int)d->d_un.d_val; break;
            case DT_RELA:     rela = (const uint8_t *)(base + d->d_un.d_ptr); break;
            case DT_RELASZ:   relasz = d->d_un.d_val; break;
            case DT_RELAENT:  relaent = d->d_un.d_val; break;
            default: break;
        }
    }
    if (!symtab || !strtab) {
        LOG("winebus: dyn missing symtab/strtab");
        return 0;
    }

    long page_size = sysconf(_SC_PAGESIZE);
    int patched = 0;

    /* Walk DT_JMPREL (PLT relocations) and DT_RELA (regular dynamic
     * relocations). PLT covers normal function calls; regular RELA
     * covers non-PLT GOT references like R_AARCH64_GLOB_DAT, which
     * winebus.so apparently uses for SDL_JoystickRumble (the previous
     * JMPREL-only walk found 34 entries but no SDL_JoystickRumble).
     * Two passes: same matching logic, different table pointers. */
    const uint8_t *tables[2]   = { jmprel, rela };
    size_t         tablesz[2]  = { jmprelsz, relasz };
    size_t         entsize[2]  = { sizeof(ElfW(Rela)), relaent };
    const char    *which[2]    = { "JMPREL", "RELA" };
    int            do_table[2] = { (pltrel_type == DT_RELA) ? 1 : 0, 1 };

    if (pltrel_type != DT_RELA) {
        LOG("winebus: PLT type=%d not RELA — skipping JMPREL scan", pltrel_type);
    }

    for (int t = 0; t < 2; t++) {
        if (!do_table[t] || !tables[t] || tablesz[t] == 0) continue;
        size_t n = tablesz[t] / entsize[t];
        int found_in_table = 0;
        for (size_t i = 0; i < n; i++) {
            const ElfW(Rela) *r = (const ElfW(Rela) *)(tables[t] + i * entsize[t]);
            size_t sym_idx = ELF64_R_SYM(r->r_info);
            if (sym_idx == 0) continue;
            const char *sym_name = strtab + symtab[sym_idx].st_name;
            if (strcmp(sym_name, "SDL_JoystickRumble") != 0) continue;

            void **slot = (void **)(base + r->r_offset);
            void  *old  = *slot;
            uintptr_t page_addr = (uintptr_t)slot & ~((uintptr_t)page_size - 1);
            if (mprotect((void *)page_addr, (size_t)page_size,
                         PROT_READ | PROT_WRITE) != 0) {
                LOGE("got_patch winebus: mprotect failed: %s", strerror(errno));
                continue;
            }
            *slot = (void *)&SDL_JoystickRumble;
            mprotect((void *)page_addr, (size_t)page_size, PROT_READ);

            LOG("got_patch winebus.so (%s): SDL_JoystickRumble slot=%p old=%p new=%p",
                which[t], (void *)slot, old, (void *)&SDL_JoystickRumble);
            patched = 1;
            found_in_table = 1;
        }
        if (!found_in_table) {
            LOG("winebus: SDL_JoystickRumble not in %s (n=%zu)", which[t], n);
        }
    }
    return patched;
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
