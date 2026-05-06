package com.xj.winemu.vibration;

import android.content.Context;
import android.content.SharedPreferences;
import android.media.AudioAttributes;
import android.os.Build;
import android.os.CombinedVibration;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.SystemClock;
import android.os.VibrationAttributes;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.os.VibratorManager;
import android.util.Log;
import android.view.InputDevice;

import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.Map;

/**
 * BhVibrationController — PC-accurate XInput rumble dispatcher.
 *
 * Ported from GameNative PR #1214 (Fix-Vibration, TideGear).
 *
 * Pipeline entry points (called from smali patches):
 *   - onRumble(slot, low, high): rumble callback from the native gamepad server,
 *     invoked by GamepadServerManager$onRumble(III)V.
 *   - dispatchToController(deviceId, low, high): per-device dispatch, invoked at
 *     the head of GamepadDevice$Physical.h(II)V. Returns true to short-circuit
 *     the stock dispatch (which lacks amplitude-control checks, VibrationAttributes,
 *     and CombinedVibration.startParallel).
 *
 * Modes:
 *   0 = Off         — no rumble anywhere
 *   1 = Controller  — dispatch to controller vibrator only (stock GameHub behaviour+)
 *   2 = Device      — dispatch aggregated rumble to phone's built-in vibrator
 *   3 = Both        — dispatch to both controller and device
 */
public final class BhVibrationController {

    private static final String TAG = "BhVibration";

    public static final int MODE_OFF = 0;
    public static final int MODE_CONTROLLER = 1;
    public static final int MODE_DEVICE = 2;
    public static final int MODE_BOTH = 3;

    public static final String PREFS_FILE = "bh_vibration_prefs";
    public static final String KEY_MODE_PREFIX = "mode_";
    public static final String KEY_INTENSITY_PREFIX = "intensity_";
    public static final String KEY_MODE_GLOBAL = "mode";
    public static final String KEY_INTENSITY_GLOBAL = "intensity";

    // Stock behaviour: controller-on, full intensity. User can disable per container.
    private static final int DEFAULT_MODE = MODE_CONTROLLER;
    private static final int DEFAULT_INTENSITY = 100;

    // XInput slots count (matches GamepadServerManager's slot range 0..3)
    private static final int MAX_SLOTS = 4;

    // Duration constants (ms). Controller effects are long enough that keepalive
    // refresh doesn't produce audible seams; device effects are shorter so the
    // phone's haptic feedback stays crisp.
    private static final long CONTROLLER_RUMBLE_MS = 2000L;
    private static final long DEVICE_RUMBLE_MS = 180L;
    private static final long DEVICE_RUMBLE_REFRESH_MS = 140L; // < DEVICE_RUMBLE_MS
    private static final long RUMBLE_KEEPALIVE_MS = 1500L;     // refresh controller before 2s expiry

    private static volatile BhVibrationController INSTANCE;

    public static BhVibrationController getInstance() {
        BhVibrationController local = INSTANCE;
        if (local == null) {
            synchronized (BhVibrationController.class) {
                local = INSTANCE;
                if (local == null) {
                    local = new BhVibrationController();
                    INSTANCE = local;
                }
            }
        }
        return local;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // State
    // ─────────────────────────────────────────────────────────────────────────

    private volatile Context appContext;
    private volatile int containerId = -1;
    private volatile int cachedMode = DEFAULT_MODE;
    private volatile int cachedIntensity = DEFAULT_INTENSITY;

    private final HandlerThread workerThread;
    private final Handler worker;

    // Device-side (phone) aggregation: per-slot last rumble amplitudes.
    private final int[] slotLow = new int[MAX_SLOTS];
    private final int[] slotHigh = new int[MAX_SLOTS];
    private final long[] slotStamp = new long[MAX_SLOTS];

    // Diagnostic-only state: tracks the LAST guest frame regardless of mode so
    // the auto-expiry trace works in any mode and isn't perturbed by MODE_OFF
    // skipping the dispatch-state update. See logGuestTransition.
    private final int[] diagPrevLow = new int[MAX_SLOTS];
    private final int[] diagPrevHigh = new int[MAX_SLOTS];
    private final long[] diagPrevWhen = new long[MAX_SLOTS];

    // Controller keepalive state: per deviceId, last dispatched (low, high, when).
    private final Map<Integer, long[]> controllerKeepalive = new HashMap<>();

    // SDL-phantom suppression. When stock g() fires within ~1 s of the last
    // non-zero rumble, treat it as SDL's internal auto-expiry and skip stock
    // g() — leaves the motor's VibrationEffect running and lets the keepalive
    // runnable refresh it. suppressionStart[deviceId] = SystemClock.uptimeMillis()
    // at the moment of suppression. Cleared on any non-zero arrival or by the
    // timeout enforcer in keepaliveRunnable (see MAX_SUSTAINED_RUMBLE_MS).
    private final Map<Integer, Long> suppressionStart = new HashMap<>();

    // SDL phantom signature: every traced auto-expiry sits at gap=1000-1001 ms
    // exactly; real game-driven stops cluster at <300 ms. ±50 ms window splits
    // them cleanly.
    private static final long SDL_PHANTOM_MIN_MS = 950L;
    private static final long SDL_PHANTOM_MAX_MS = 1050L;

    // Hard cap on suppression. After this, force-stop the motor regardless —
    // bounds worst-case "false rumble after release" because Wine doesn't
    // re-issue a (0,0) once SDL is in its stopped state. 5 s feels generous
    // for sustained rumble (engine, environmental) without lingering too long
    // after a real release.
    private static final long MAX_SUSTAINED_RUMBLE_MS = 5000L;

    // Last device-effect time so we don't overwhelm phone vibrator.
    private volatile long lastDeviceDispatch = 0L;
    private volatile boolean deviceActive = false;

    private final Runnable keepaliveRunnable = new Runnable() {
        @Override
        public void run() {
            try {
                long now = SystemClock.uptimeMillis();

                // SDL-phantom suppression timeout enforcer: any deviceId whose
                // suppression has been active for longer than MAX_SUSTAINED_RUMBLE_MS
                // gets force-stopped here. This is the bound that keeps a stuck
                // controller from running forever when Wine never re-emits a (0,0)
                // (because SDL is in its stopped state from its perspective).
                if (!suppressionStart.isEmpty()) {
                    java.util.List<Integer> timedOut = null;
                    synchronized (suppressionStart) {
                        for (Map.Entry<Integer, Long> e : suppressionStart.entrySet()) {
                            if (now - e.getValue() > MAX_SUSTAINED_RUMBLE_MS) {
                                if (timedOut == null) timedOut = new java.util.ArrayList<>(2);
                                timedOut.add(e.getKey());
                            }
                        }
                        if (timedOut != null) {
                            for (Integer dev : timedOut) suppressionStart.remove(dev);
                        }
                    }
                    if (timedOut != null) {
                        for (Integer deviceId : timedOut) {
                            Log.i(TAG, "suppression timeout dev=" + deviceId
                                    + " (" + MAX_SUSTAINED_RUMBLE_MS + "ms) — force stop");
                            stopController(deviceId);
                            recordKeepalive(deviceId, 0, 0);
                        }
                    }
                }

                // Controller side: refresh any active controller whose last dispatch
                // is older than KEEPALIVE threshold and whose amplitude is non-zero.
                synchronized (controllerKeepalive) {
                    for (Map.Entry<Integer, long[]> e : controllerKeepalive.entrySet()) {
                        long[] st = e.getValue();
                        int low = (int) st[0];
                        int high = (int) st[1];
                        long when = st[2];
                        if ((low > 0 || high > 0) && (now - when) >= RUMBLE_KEEPALIVE_MS) {
                            InputDevice dev = InputDevice.getDevice(e.getKey());
                            if (dev != null) {
                                dispatchControllerInternal(dev, low, high, /*log*/ false);
                                st[2] = now;
                            }
                        }
                    }
                }
                // Device side: if any slot has amplitude and refresh interval elapsed, re-arm.
                if (deviceActive && (now - lastDeviceDispatch) >= DEVICE_RUMBLE_REFRESH_MS) {
                    refreshDeviceRumble(now);
                }
            } catch (Throwable t) {
                Log.w(TAG, "keepalive tick failed", t);
            } finally {
                worker.postDelayed(this, 60L);
            }
        }
    };

    private BhVibrationController() {
        workerThread = new HandlerThread("BhVibWorker");
        workerThread.start();
        worker = new Handler(workerThread.getLooper());
        worker.post(keepaliveRunnable);
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Public API
    // ─────────────────────────────────────────────────────────────────────────

    public void init(Context ctx) {
        if (ctx != null && this.appContext == null) {
            this.appContext = ctx.getApplicationContext();
        }
        reloadSettings();
    }

    /** Invoked by the container-launch smali patch once it knows the active gameId. */
    public void setContainer(int gameId) {
        this.containerId = gameId;
        reloadSettings();
        Log.i(TAG, "container=" + gameId + " mode=" + cachedMode + " intensity=" + cachedIntensity);
    }

    /**
     * Walks the live-activity table for any running WineActivity and extracts
     * its "gameId" Intent extra. Lets us scope prefs per-container without
     * requiring a smali patch to WineActivity.onCreate.
     *
     * Called opportunistically from handleRumble — if nothing resolves yet, we
     * stay on global settings until the user enters a Wine session.
     */
    private void maybeResolveContainerFromActivityStack() {
        if (containerId >= 0) return;
        try {
            Class<?> atCls = Class.forName("android.app.ActivityThread");
            Method cur = atCls.getMethod("currentActivityThread");
            Object at = cur.invoke(null);
            if (at == null) return;
            java.lang.reflect.Field fActs = atCls.getDeclaredField("mActivities");
            fActs.setAccessible(true);
            Object acts = fActs.get(at);
            if (!(acts instanceof Map)) return;
            for (Object recordObj : ((Map<?, ?>) acts).values()) {
                if (recordObj == null) continue;
                java.lang.reflect.Field fAct = recordObj.getClass().getDeclaredField("activity");
                fAct.setAccessible(true);
                Object activity = fAct.get(recordObj);
                if (!(activity instanceof android.app.Activity)) continue;
                String clsName = activity.getClass().getName();
                if (!clsName.endsWith(".WineActivity")) continue;
                android.content.Intent it = ((android.app.Activity) activity).getIntent();
                if (it == null) continue;
                String gid = it.getStringExtra("gameId");
                if (gid == null || gid.isEmpty()) continue;
                int parsed;
                try { parsed = Integer.parseInt(gid); } catch (NumberFormatException e) { parsed = gid.hashCode(); }
                setContainer(parsed);
                return;
            }
        } catch (Throwable ignored) { }
    }

    /** Invoked from the settings UI when the user adjusts mode (0..3). */
    public void setMode(int mode) {
        if (mode < 0 || mode > 3) return;
        this.cachedMode = mode;
        writeInt(KEY_MODE_PREFIX + containerId, mode);
        writeInt(KEY_MODE_GLOBAL, mode);
    }

    /** Invoked from the settings UI when the user adjusts intensity (0..100). */
    public void setIntensity(int pct) {
        if (pct < 0) pct = 0;
        if (pct > 100) pct = 100;
        this.cachedIntensity = pct;
        writeInt(KEY_INTENSITY_PREFIX + containerId, pct);
        writeInt(KEY_INTENSITY_GLOBAL, pct);
    }

    public int getMode() { return cachedMode; }
    public int getIntensity() { return cachedIntensity; }

    /**
     * Entry point invoked from the sidebar settings button (contentType=0x65).
     * Kept as a single static so the smali click handler can stay tiny.
     */
    public static void launchSettings(Context ctx) {
        if (ctx == null) return;
        try {
            android.content.Intent it = new android.content.Intent(ctx, BhVibrationSettingsActivity.class);
            it.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK);
            ctx.startActivity(it);
        } catch (Throwable t) {
            Log.w(TAG, "launchSettings failed", t);
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Smali entry 1: GamepadServerManager.onRumble(slot, low, high)
    //   Return true  → caller short-circuits (device-only or off).
    //   Return false → caller falls through to stock controller dispatch.
    // ─────────────────────────────────────────────────────────────────────────
    public static boolean onRumble(int slot, int low, int high) {
        try {
            return getInstance().handleRumble(slot, low, high);
        } catch (Throwable t) {
            Log.w(TAG, "onRumble failed", t);
            return false;
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Smali entry 2: GamepadDevice$Physical.h(lowRaw, highRaw)
    //   Return true  → caller short-circuits (controller handled, or mode excludes it).
    //   Return false → caller falls through to stock per-vibrator dispatch.
    // ─────────────────────────────────────────────────────────────────────────
    public static boolean dispatchToController(int deviceId, int lowRaw, int highRaw) {
        try {
            return getInstance().handleControllerDispatch(deviceId, lowRaw, highRaw);
        } catch (Throwable t) {
            Log.w(TAG, "dispatchToController failed", t);
            return false;
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Smali entry 3: GamepadDevice$Physical.g(). Stock GameHub's
    // GamepadDevice.f(II)V routes (0,0) -> g() (stop) and non-zero -> h(II)V
    // (dispatch). Our Patch 2 hooks h(II)V only, so without Patch 7 the (0,0)
    // would bypass our handler and our keepalive map would never clear.
    //
    // Patch 7 hooks g()V to call onStop(deviceId).
    //   Return true  → suppress (SDL auto-expiry phantom). Skip stock g();
    //                  the motor's existing VibrationEffect keeps running and
    //                  the keepalive runnable refreshes it every 1.5 s, up to
    //                  MAX_SUSTAINED_RUMBLE_MS at which point it force-stops.
    //   Return false → real game-driven stop. Let stock g() iterate the
    //                  vibrator list and cancel each.
    // ─────────────────────────────────────────────────────────────────────────
    public static boolean onStop(int deviceId) {
        try {
            return getInstance().handleStop(deviceId);
        } catch (Throwable t) {
            Log.w(TAG, "onStop failed", t);
            return false;
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Core logic
    // ─────────────────────────────────────────────────────────────────────────

    private boolean handleRumble(int slot, int low, int high) {
        if (slot < 0 || slot >= MAX_SLOTS) return false;
        ensureContext();
        maybeResolveContainerFromActivityStack();

        // Diagnostic: log every state change from the guest with a timestamp delta.
        // Flags non-zero -> (0,0) arrivals around 1 s as suspected SDL auto-expiry,
        // which is the bug GameNative PR #1214's evshim keepalive fixes. Read prev
        // state BEFORE the OFF early-return so the trace stays accurate across modes.
        logGuestTransition(slot, low & 0xFFFF, high & 0xFFFF);

        int mode = cachedMode;
        if (mode == MODE_OFF) return true; // swallow everything

        // Store per-slot raw values for device aggregation.
        slotLow[slot] = low & 0xFFFF;
        slotHigh[slot] = high & 0xFFFF;
        slotStamp[slot] = SystemClock.uptimeMillis();

        if (mode == MODE_DEVICE || mode == MODE_BOTH) {
            worker.post(new Runnable() {
                @Override public void run() { dispatchDevice(); }
            });
        }

        // If mode is Device or Off, skip the stock controller dispatch entirely.
        return mode == MODE_DEVICE;
    }

    private boolean handleControllerDispatch(int deviceId, int lowRaw, int highRaw) {
        int mode = cachedMode;
        int low = lowRaw & 0xFFFF;
        int high = highRaw & 0xFFFF;
        Log.i(TAG, "DISPATCH dev=" + deviceId + " mode=" + mode
                + " low=" + low + " high=" + high);

        if (mode == MODE_OFF || mode == MODE_DEVICE) {
            // Controller should stay silent. Stop any active rumble on this device.
            stopController(deviceId);
            return true;
        }

        InputDevice dev = InputDevice.getDevice(deviceId);
        if (dev == null) {
            Log.i(TAG, "DISPATCH dev=" + deviceId + " InputDevice.getDevice -> null, fallthrough");
            return false; // let stock code try (won't find anything, but no harm)
        }

        if (low == 0 && high == 0) {
            stopController(deviceId);
            recordKeepalive(deviceId, 0, 0);
            return true;
        }

        dispatchControllerInternal(dev, low, high, /*log*/ true);
        recordKeepalive(deviceId, low, high);
        // Game is actively rumbling — any prior suppression timeout is no
        // longer relevant. Clear it so the timeout enforcer doesn't fire while
        // real rumble is in progress.
        synchronized (suppressionStart) {
            suppressionStart.remove(deviceId);
        }
        return true;
    }

    /**
     * Called from the smali patch on GamepadDevice$Physical.g()V — fires
     * whenever stock GameHub's GamepadDevice.f(II)V routes a (0, 0) rumble
     * to the stop path.
     *
     * Returns true to SUPPRESS — stock g() is skipped, the motor's existing
     * VibrationEffect keeps running, and the keepalive runnable refreshes it
     * every 1.5 s up to MAX_SUSTAINED_RUMBLE_MS at which point the timeout
     * enforcer in keepaliveRunnable force-stops it.
     *
     * Returns false on a real game-driven stop — stock g() runs after us and
     * iterates the vibrator list canceling each. We also issue our supersede
     * pattern (1 ms minimum-amplitude vm.vibrate()) ahead of stock g() because
     * on Samsung's Vibrator HAL for InputDevice vibrators, Vibrator.cancel()
     * doesn't reliably halt BT-HID effects already uploaded to the controller.
     *
     * SDL phantom signature: every traced auto-expiry sits at gap=1000–1001 ms
     * exactly; real game stops cluster at <300 ms. The [950, 1050] ms window
     * splits them cleanly.
     */
    private boolean handleStop(int deviceId) {
        long now = SystemClock.uptimeMillis();
        long lastNonZeroWhen = 0L;
        boolean lastWasNonZero = false;
        synchronized (controllerKeepalive) {
            long[] st = controllerKeepalive.get(deviceId);
            if (st != null) {
                lastWasNonZero = (st[0] != 0 || st[1] != 0);
                lastNonZeroWhen = st[2];
            }
        }

        if (lastWasNonZero && lastNonZeroWhen > 0) {
            long gap = now - lastNonZeroWhen;
            if (gap >= SDL_PHANTOM_MIN_MS && gap <= SDL_PHANTOM_MAX_MS) {
                // SDL auto-expiry phantom. Suppress: don't clear keepalive map,
                // don't cancel motor. The motor's VibrationEffect continues and
                // the keepalive runnable will refresh it every 1.5 s up to the
                // MAX_SUSTAINED_RUMBLE_MS timeout.
                synchronized (suppressionStart) {
                    suppressionStart.put(deviceId, now);
                }
                Log.i(TAG, "STOP-G suppress dev=" + deviceId + " gap=" + gap
                        + "ms (SDL phantom; keepalive will run for up to "
                        + MAX_SUSTAINED_RUMBLE_MS + "ms then force-stop)");
                return true;
            }
        }

        // Real game-driven stop.
        Log.i(TAG, "STOP-G dev=" + deviceId);
        recordKeepalive(deviceId, 0, 0);
        for (int i = 0; i < MAX_SLOTS; i++) {
            slotLow[i] = 0;
            slotHigh[i] = 0;
        }
        deviceActive = false;
        synchronized (suppressionStart) {
            suppressionStart.remove(deviceId);
        }
        // Supersede AHEAD of stock g()'s per-vibrator cancel.
        stopController(deviceId);
        return false;
    }

    /**
     * Diagnostic logger for guest-side rumble events arriving via
     * GamepadServerManager.onRumble. Logs only meaningful state transitions
     * (skips repeated same-value frames). Tags non-zero -> (0,0) arrivals in
     * the 900-1200 ms window as suspected SDL auto-expiry — the trigger for
     * deciding whether to port GameNative PR #1214's evshim keepalive.
     *
     * Reads previous state from slotLow/slotHigh/slotStamp BEFORE handleRumble
     * overwrites them, so each log line shows the actual delta from the last
     * frame. Filter logcat with `BhVibration` and grep "DIAG ".
     */
    private void logGuestTransition(int slot, int newLow, int newHigh) {
        int prevLow = diagPrevLow[slot];
        int prevHigh = diagPrevHigh[slot];
        long prevWhen = diagPrevWhen[slot];
        long now = SystemClock.uptimeMillis();

        // Always update the diagnostic state, even on idle frames, so the next
        // transition's gap measures from the most recent non-update event too.
        diagPrevLow[slot] = newLow;
        diagPrevHigh[slot] = newHigh;
        diagPrevWhen[slot] = now;

        if (prevLow == newLow && prevHigh == newHigh) return; // idle frame, no log

        long gap = (prevWhen > 0) ? (now - prevWhen) : -1L;
        boolean wasNonZero = (prevLow | prevHigh) != 0;
        boolean isZero = (newLow | newHigh) == 0;
        String tag = "";
        if (wasNonZero && isZero && gap >= 900L && gap <= 1200L) {
            tag = "  [SDL_AUTO_EXPIRY?]";
        }
        Log.i(TAG, "DIAG slot=" + slot
                + "  " + prevLow + "," + prevHigh
                + " -> " + newLow + "," + newHigh
                + "  gap=" + gap + "ms" + tag);
    }

    /**
     * Per-controller dispatch. Uses CombinedVibration.startParallel when the
     * device exposes a VibratorManager with ≥2 motors; otherwise falls back to
     * a single-vibrator blend (low*0.8 + high*0.33) that matches GameNative PR.
     *
     * Amplitude is scaled by the user's intensity percentage and floored at 1
     * so non-zero XInput values never get quantised away to silence.
     */
    private void dispatchControllerInternal(InputDevice dev, int low, int high, boolean logMotors) {
        int intensity = cachedIntensity;
        int lowAmp = scaleAmplitude(low, intensity);
        int highAmp = scaleAmplitude(high, intensity);
        if (lowAmp == 0 && highAmp == 0) return;

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            VibratorManager vm = dev.getVibratorManager();
            if (vm != null && tryCombinedDispatch(vm, lowAmp, highAmp, logMotors)) {
                return;
            }
        }

        // Fallback path: single-vibrator blend of low + high.
        Vibrator v = dev.getVibrator();
        if (v == null || !v.hasVibrator()) return;
        int blended = (int) Math.min(255, Math.max(1, Math.round(lowAmp * 0.80 + highAmp * 0.33)));
        vibrateSafe(v, blended, CONTROLLER_RUMBLE_MS, /*haptic*/ true);
    }

    private boolean tryCombinedDispatch(VibratorManager vm, int lowAmp, int highAmp, boolean logMotors) {
        int[] ids = vm.getVibratorIds();
        if (ids == null || ids.length == 0) return false;

        // Sort ascending to give us a deterministic "low motor = ids[0]" assignment.
        int[] sortedIds = ids.clone();
        java.util.Arrays.sort(sortedIds);

        if (sortedIds.length == 1) {
            Vibrator only = vm.getVibrator(sortedIds[0]);
            if (only == null) return false;
            int blended = (int) Math.min(255, Math.max(1, Math.round(lowAmp * 0.80 + highAmp * 0.33)));
            vibrateSafe(only, blended, CONTROLLER_RUMBLE_MS, /*haptic*/ true);
            return true;
        }

        Vibrator lowMotor = vm.getVibrator(sortedIds[0]);
        Vibrator highMotor = vm.getVibrator(sortedIds[1]);
        if (lowMotor == null || highMotor == null) return false;

        int effLow = clampAmplitude(lowAmp, lowMotor);
        int effHigh = clampAmplitude(highAmp, highMotor);

        CombinedVibration.ParallelCombination p = CombinedVibration.startParallel();
        if (effLow > 0) p.addVibrator(sortedIds[0], VibrationEffect.createOneShot(CONTROLLER_RUMBLE_MS, effLow));
        if (effHigh > 0) p.addVibrator(sortedIds[1], VibrationEffect.createOneShot(CONTROLLER_RUMBLE_MS, effHigh));

        CombinedVibration combined = p.combine();
        VibrationAttributes attrs = buildAttrs();
        if (attrs != null) {
            vm.vibrate(combined, attrs);
        } else {
            vm.vibrate(combined);
        }

        if (logMotors) {
            Log.i(TAG, "combined dispatch ids=" + java.util.Arrays.toString(sortedIds)
                    + " lowAmp=" + effLow + " highAmp=" + effHigh);
        }
        return true;
    }

    private int clampAmplitude(int amp, Vibrator v) {
        if (amp <= 0) return 0;
        if (v != null && !v.hasAmplitudeControl()) {
            // No amplitude support: any non-zero value = full strength pulse.
            return amp > 0 ? 255 : 0;
        }
        return Math.min(255, Math.max(1, amp));
    }

    private void stopController(int deviceId) {
        InputDevice dev = InputDevice.getDevice(deviceId);
        if (dev == null) {
            Log.i(TAG, "STOP dev=" + deviceId + " InputDevice null");
            return;
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                VibratorManager vm = dev.getVibratorManager();
                if (vm != null) {
                    int[] ids = vm.getVibratorIds();
                    if (ids != null && ids.length > 0) {
                        // Force-stop pattern: vm.cancel() alone does NOT reliably
                        // halt in-flight BT-HID rumble on Samsung's Vibrator HAL
                        // for InputDevice vibrators. But vibrate() always supersedes
                        // (proven empirically: tapping a different motor halts the
                        // previous one). Issue a 1ms minimum-amplitude pulse on
                        // every motor to replace whatever's running, then cancel
                        // for belt-and-suspenders.
                        CombinedVibration.ParallelCombination p = CombinedVibration.startParallel();
                        for (int id : ids) {
                            p.addVibrator(id, VibrationEffect.createOneShot(1L, 1));
                        }
                        VibrationAttributes attrs = buildAttrs();
                        if (attrs != null) {
                            vm.vibrate(p.combine(), attrs);
                        } else {
                            vm.vibrate(p.combine());
                        }
                        vm.cancel();
                        Log.i(TAG, "STOP dev=" + deviceId + " supersede+cancel ids="
                                + java.util.Arrays.toString(ids));
                        return;
                    }
                    Log.i(TAG, "STOP dev=" + deviceId + " vm has no vibrator ids; cancel()");
                    vm.cancel();
                    return;
                }
            }
            Vibrator v = dev.getVibrator();
            if (v != null) {
                Log.i(TAG, "STOP dev=" + deviceId + " single-vibrator supersede+cancel");
                try { v.vibrate(VibrationEffect.createOneShot(1L, 1)); } catch (Throwable ignored) {}
                v.cancel();
            } else {
                Log.i(TAG, "STOP dev=" + deviceId + " no Vibrator/VibratorManager");
            }
        } catch (Throwable t) {
            Log.w(TAG, "STOP dev=" + deviceId + " threw", t);
        }
    }

    private void recordKeepalive(int deviceId, int low, int high) {
        long now = SystemClock.uptimeMillis();
        synchronized (controllerKeepalive) {
            long[] st = controllerKeepalive.get(deviceId);
            if (st == null) {
                st = new long[3];
                controllerKeepalive.put(deviceId, st);
            }
            st[0] = low;
            st[1] = high;
            st[2] = now;
        }
    }

    /**
     * Phone (device) dispatch: aggregate across all active slots using MAX
     * of each motor, then blend and apply a haptic curve so low-end bias
     * doesn't make weak rumbles imperceptible.
     */
    private void dispatchDevice() {
        ensureContext();
        Context ctx = appContext;
        if (ctx == null) return;

        int maxLow = 0, maxHigh = 0;
        long now = SystemClock.uptimeMillis();
        for (int i = 0; i < MAX_SLOTS; i++) {
            if (now - slotStamp[i] > 1500L) { slotLow[i] = 0; slotHigh[i] = 0; continue; }
            if (slotLow[i] > maxLow) maxLow = slotLow[i];
            if (slotHigh[i] > maxHigh) maxHigh = slotHigh[i];
        }
        if (maxLow == 0 && maxHigh == 0) { deviceActive = false; return; }

        int intensity = cachedIntensity;
        int lowAmp = scaleAmplitude(maxLow, intensity);
        int highAmp = scaleAmplitude(maxHigh, intensity);
        int blended = Math.min(255, Math.max(1, (int) Math.round(lowAmp * 0.80 + highAmp * 0.33)));

        // Haptic curve pow(x, 0.6) — makes small values more perceptible on the phone.
        double norm = blended / 255.0;
        int shaped = (int) Math.min(255, Math.max(1, Math.round(Math.pow(norm, 0.6) * 255.0)));

        Vibrator v = resolveDeviceVibrator(ctx);
        if (v == null) return;
        vibrateSafe(v, shaped, DEVICE_RUMBLE_MS, /*haptic*/ false);
        lastDeviceDispatch = now;
        deviceActive = true;
    }

    private void refreshDeviceRumble(long now) {
        // Recompute from last known slot values and re-dispatch if still active.
        int maxLow = 0, maxHigh = 0;
        for (int i = 0; i < MAX_SLOTS; i++) {
            if (now - slotStamp[i] > 1500L) { slotLow[i] = 0; slotHigh[i] = 0; continue; }
            if (slotLow[i] > maxLow) maxLow = slotLow[i];
            if (slotHigh[i] > maxHigh) maxHigh = slotHigh[i];
        }
        if (maxLow == 0 && maxHigh == 0) {
            deviceActive = false;
            return;
        }
        dispatchDevice();
    }

    private Vibrator resolveDeviceVibrator(Context ctx) {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                VibratorManager vm = (VibratorManager) ctx.getSystemService(Context.VIBRATOR_MANAGER_SERVICE);
                if (vm != null) return vm.getDefaultVibrator();
            }
            return (Vibrator) ctx.getSystemService(Context.VIBRATOR_SERVICE);
        } catch (Throwable t) {
            return null;
        }
    }

    private void vibrateSafe(Vibrator v, int amplitude, long durationMs, boolean haptic) {
        try {
            if (v == null || !v.hasVibrator()) return;
            int amp = amplitude;
            if (!v.hasAmplitudeControl()) amp = VibrationEffect.DEFAULT_AMPLITUDE;
            VibrationEffect eff = VibrationEffect.createOneShot(durationMs, amp);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                VibrationAttributes attrs = buildAttrs();
                if (attrs != null) { v.vibrate(eff, attrs); return; }
            }
            AudioAttributes audio = new AudioAttributes.Builder()
                    .setUsage(haptic ? AudioAttributes.USAGE_GAME : AudioAttributes.USAGE_UNKNOWN)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build();
            v.vibrate(eff, audio);
        } catch (Throwable ignored) { }
    }

    private VibrationAttributes buildAttrs() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return null;
        try {
            return new VibrationAttributes.Builder()
                    .setUsage(VibrationAttributes.USAGE_MEDIA)
                    .build();
        } catch (Throwable t) {
            return null;
        }
    }

    /**
     * XInput rumble is 16-bit unsigned. Scale to 0..255 and apply user intensity.
     * Amplitude is floored at 1 (not 0) so barely-perceptible values don't vanish
     * entirely due to integer truncation.
     */
    public static int scaleAmplitude(int rawFreq, int intensityPercent) {
        int unsigned = rawFreq & 0xFFFF;
        if (unsigned == 0 || intensityPercent == 0) return 0;
        int base = (int) Math.round(unsigned * 255.0 / 65535.0);
        int scaled = (base * intensityPercent) / 100;
        return Math.min(255, Math.max(1, scaled));
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Settings I/O
    // ─────────────────────────────────────────────────────────────────────────

    private void reloadSettings() {
        ensureContext();
        Context ctx = appContext;
        if (ctx == null) return;
        SharedPreferences sp = ctx.getSharedPreferences(PREFS_FILE, Context.MODE_PRIVATE);
        int globalMode = sp.getInt(KEY_MODE_GLOBAL, DEFAULT_MODE);
        int globalIntensity = sp.getInt(KEY_INTENSITY_GLOBAL, DEFAULT_INTENSITY);
        if (containerId >= 0) {
            cachedMode = sp.getInt(KEY_MODE_PREFIX + containerId, globalMode);
            cachedIntensity = sp.getInt(KEY_INTENSITY_PREFIX + containerId, globalIntensity);
        } else {
            cachedMode = globalMode;
            cachedIntensity = globalIntensity;
        }
    }

    private void writeInt(String key, int val) {
        ensureContext();
        Context ctx = appContext;
        if (ctx == null) return;
        ctx.getSharedPreferences(PREFS_FILE, Context.MODE_PRIVATE)
                .edit().putInt(key, val).apply();
    }

    /**
     * ActivityThread.currentApplication() gives us a Context without needing
     * any caller to pass one in. Works from any thread after app initialisation.
     */
    private void ensureContext() {
        if (appContext != null) return;
        try {
            Class<?> at = Class.forName("android.app.ActivityThread");
            Method m = at.getMethod("currentApplication");
            Object app = m.invoke(null);
            if (app instanceof Context) {
                appContext = ((Context) app).getApplicationContext();
                reloadSettings();
            }
        } catch (Throwable t) {
            Log.w(TAG, "ensureContext failed", t);
        }
    }
}
