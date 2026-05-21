package com.xj.winemu.vibration;

import android.app.Activity;
import android.content.Intent;
import android.util.Log;

import com.xj.winemu.common.BhMenuGameId;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

/**
 * Onclick handler for the "PC Vibration Settings" row injected into the
 * three per-game library menu surfaces (game detail More Menu, library-tile
 * popup, library-list 3-dot popup).
 *
 * The host APK ships kotlin-stdlib so all Function0/Function1 / Unit
 * references work at runtime. We deliberately don't `implements Function1`
 * here so this fork's javac step doesn't need kotlin-stdlib on the
 * classpath — the host's R8 rename means a direct Java `implements
 * Function1` wouldn't satisfy the host's type check anyway. All Function0
 * / Function1 contracts are fulfilled by {@link java.lang.reflect.Proxy}
 * instances created at row-construction time inside the appendXxxRow
 * helpers below.
 *
 * The Context is resolved at click time by reflectively walking
 * ActivityThread.mActivities to find the currently-resumed Activity. This
 * avoids needing a captured Context at construction time, which would
 * otherwise require the bytecode patch to find an appropriate Context
 * register inside the heavily-obfuscated Compose Composables.
 *
 * The per-game id is read from {@link BhMenuGameId#getCaptured()} (set by
 * the index-0 captureGameId(p0) injection in each of the three menu
 * builders), so the dialog opens scoped to the right game even from a
 * pre-launch menu where no WineActivity is on the stack yet.
 */
public final class BhMenuRowClick {

    private static final String TAG = "BhMenuRowClick";

    /** Cached kotlin.Unit.INSTANCE resolved via reflection — runtime-only
     *  so this Java module compiles without kotlin-stdlib on the classpath. */
    private static volatile Object UNIT;

    private static Object kotlinUnit() {
        Object u = UNIT;
        if (u != null) return u;
        try {
            Class<?> c = Class.forName("kotlin.Unit");
            Field f = c.getField("INSTANCE");
            u = f.get(null);
            UNIT = u;
            return u;
        } catch (Throwable t) {
            return null;
        }
    }

    public Object invoke(Object ignoredFromCompose) {
        try {
            Activity host = resolveTopActivity();
            if (host == null) {
                Log.w(TAG, "no top Activity resolvable; cannot launch settings");
                return kotlinUnit();
            }
            Intent intent = new Intent(host, BhVibrationSettingsActivity.class);
            String gameId = BhMenuGameId.getCaptured();
            if (gameId == null || gameId.isEmpty()) gameId = sniffGameIdFromStack();
            if (gameId != null && !gameId.isEmpty()) {
                // BhVibrationSettingsActivity reads EXTRA_GAME_ID
                // ("bh_vibration.gameId"), not "gameId" — using the
                // wrong key here is why per-game never took effect.
                intent.putExtra(BhVibrationSettingsActivity.EXTRA_GAME_ID, gameId);
            }
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            host.startActivity(intent);
        } catch (Throwable t) {
            Log.w(TAG, "menu click failed", t);
        }
        return kotlinUnit();
    }

    /** Walk ActivityThread.mActivities to find the most-recently-resumed Activity. */
    private static Activity resolveTopActivity() {
        try {
            Class<?> atCls = Class.forName("android.app.ActivityThread");
            Method cur = atCls.getMethod("currentActivityThread");
            Object at = cur.invoke(null);
            if (at == null) return null;
            Field fActs = atCls.getDeclaredField("mActivities");
            fActs.setAccessible(true);
            Object acts = fActs.get(at);
            if (!(acts instanceof Map)) return null;
            Activity best = null;
            for (Object record : ((Map<?, ?>) acts).values()) {
                if (record == null) continue;
                Field fAct = record.getClass().getDeclaredField("activity");
                fAct.setAccessible(true);
                Object a = fAct.get(record);
                if (!(a instanceof Activity)) continue;
                Activity activity = (Activity) a;
                if (activity.isFinishing()) continue;
                try {
                    Field fPaused = record.getClass().getDeclaredField("paused");
                    fPaused.setAccessible(true);
                    Object paused = fPaused.get(record);
                    if (paused instanceof Boolean && !((Boolean) paused)) {
                        return activity;
                    }
                } catch (NoSuchFieldException ignored) { }
                best = activity;
            }
            return best;
        } catch (Throwable t) {
            Log.w(TAG, "resolveTopActivity failed", t);
            return null;
        }
    }

    /**
     * Game detail More Menu row appender. Constructs a Liae 3-arg row via
     * reflection and adds it to the passed list builder. Called from a
     * single-instruction smali injection inside Lx57.a — keeps the
     * bytecode patch trivial (no register juggling, no verifier risk) at
     * the cost of a runtime reflection lookup.
     *
     * The obfuscated class names iae/o05/pw6/zz4 are stable in the
     * GameHub 6.0.4 base APK; if a future R8 map shifts them the
     * helper silently no-ops (logged) and the menu falls back to the
     * original rows.
     */
    public static void appendVibrationRowTo(Object menuList) {
        try {
            if (!(menuList instanceof List)) return;
            @SuppressWarnings("unchecked")
            List<Object> list = (List<Object>) menuList;

            Class<?> iaeCls = Class.forName("iae");
            Class<?> o05Cls = Class.forName("o05");
            Class<?> pw6Cls = Class.forName("pw6");

            // Resolve a gear/settings icon. Lzz4 is the
            // ComposableSingletons class for menu-row icons; the `b0`
            // field holds an Lxrl wrapper whose getValue() returns an
            // Lo05 (Painter or vector ref).
            Class<?> zz4Cls = Class.forName("zz4");
            Field iconHolderField = zz4Cls.getDeclaredField("b0");
            iconHolderField.setAccessible(true);
            Object xrlWrapper = iconHolderField.get(null);
            if (xrlWrapper == null) {
                Log.w(TAG, "zz4.b0 is null; cannot resolve icon");
                return;
            }
            Object iconValue = xrlWrapper.getClass().getMethod("getValue").invoke(xrlWrapper);
            if (!o05Cls.isInstance(iconValue)) {
                Log.w(TAG, "zz4.b0.getValue() did not return Lo05");
                return;
            }

            // R8 renamed kotlin.jvm.functions.Function1 to Lpw6 in the
            // host APK, so our Java `implements Function1<Object,
            // Object>` IS a different JVM class from the host's Lpw6.
            // Liae's ctor requires Lpw6 specifically — direct Java
            // implements doesn't satisfy the type check. Fix: a Proxy
            // that implements Lpw6 at runtime and delegates invoke to
            // our BhMenuRowClick.
            final BhMenuRowClick handler = new BhMenuRowClick();
            Object click = java.lang.reflect.Proxy.newProxyInstance(
                pw6Cls.getClassLoader(),
                new Class<?>[]{ pw6Cls },
                (proxy, method, args) -> {
                    if ("invoke".equals(method.getName()) && method.getParameterCount() == 1) {
                        return handler.invoke(args != null && args.length > 0 ? args[0] : null);
                    }
                    if ("equals".equals(method.getName())) return proxy == args[0];
                    if ("hashCode".equals(method.getName())) return System.identityHashCode(proxy);
                    if ("toString".equals(method.getName())) return "BhMenuRowClickProxy";
                    return null;
                }
            );

            Constructor<?> ctor =
                iaeCls.getDeclaredConstructor(o05Cls, String.class, pw6Cls);
            ctor.setAccessible(true);

            Object row = ctor.newInstance(iconValue, "PC Vibration Settings", click);
            list.add(row);
        } catch (Throwable t) {
            Log.w(TAG, "appendVibrationRowTo failed", t);
        }
    }

    /**
     * Library-tile popup variant (Lted.f). Rows use Lscd(String actionId,
     * Lo05 icon, String label, Lnw6 onClick) with a Function0 click
     * handler (no args), and the 4 rows are collected into an
     * immutable List via Arrays.asList before being iterated for the
     * focus tree.
     *
     * The smali injection replaces that list with a new ArrayList
     * containing the original 4 rows plus our PC Vibration Settings
     * row. Returns the augmented list; the smali captures the return
     * value and reassigns it to the list register.
     */
    public static List<Object> appendScdRowToTedList(Object original) {
        try {
            if (!(original instanceof List)) return safeReturn(original);
            List<?> origList = (List<?>) original;
            ArrayList<Object> augmented = new ArrayList<>(origList);

            Class<?> scdCls = Class.forName("scd");
            Class<?> o05Cls = Class.forName("o05");
            Class<?> nw6Cls = Class.forName("nw6");
            Class<?> zz4Cls = Class.forName("zz4");

            Field iconField = zz4Cls.getDeclaredField("b0");
            iconField.setAccessible(true);
            Object xrlWrapper = iconField.get(null);
            if (xrlWrapper == null) return safeReturn(original);
            Object iconValue = xrlWrapper.getClass().getMethod("getValue").invoke(xrlWrapper);
            if (!o05Cls.isInstance(iconValue)) return safeReturn(original);

            // Function0 onClick via Proxy implementing Lnw6.
            final BhMenuRowClick handler = new BhMenuRowClick();
            Object click = java.lang.reflect.Proxy.newProxyInstance(
                nw6Cls.getClassLoader(),
                new Class<?>[]{ nw6Cls },
                (proxy, method, args) -> {
                    if ("invoke".equals(method.getName()) && method.getParameterCount() == 0) {
                        return handler.invoke(null);
                    }
                    if ("equals".equals(method.getName())) return proxy == args[0];
                    if ("hashCode".equals(method.getName())) return System.identityHashCode(proxy);
                    if ("toString".equals(method.getName())) return "BhMenuRowClickProxy0";
                    return null;
                }
            );

            Constructor<?> ctor =
                scdCls.getDeclaredConstructor(String.class, o05Cls, String.class, nw6Cls);
            ctor.setAccessible(true);

            Object row = ctor.newInstance(
                "local_detail_menu_pc_vibration",
                iconValue,
                "PC Vibration Settings",
                click
            );
            augmented.add(row);
            return augmented;
        } catch (Throwable t) {
            Log.w(TAG, "appendScdRowToTedList failed", t);
            return safeReturn(original);
        }
    }

    /**
     * Library-list 3-dot popup variant (Lpzc.j0). Uses a third row
     * data class:
     *   Lz4e(Lell label, Lnw6 onClick, int)  [synthetic 3-arg ctor]
     *     - Lell extends Ltdi(String key, Set<String> locales), a
     *       Compose Multiplatform string-resource descriptor; resolved
     *       at render time by Lxd3.l1.
     *     - Lnw6 is Function0 (no-arg lambda).
     *
     * Our label key "bh_pc_vibration_label" is also patched into the
     * resolver Lxd3.l1 via maybeResolveCustomLabel below, so the
     * Compose runtime doesn't need a matching CVR entry to render
     * "PC Vibration Settings".
     */
    public static List<Object> appendLibraryPopupRow(Object original) {
        try {
            if (!(original instanceof List)) return safeReturn(original);
            List<?> origList = (List<?>) original;
            ArrayList<Object> augmented = new ArrayList<>(origList);

            Class<?> z4eCls = Class.forName("z4e");
            Class<?> ellCls = Class.forName("ell");
            Class<?> tdiCls = Class.forName("tdi");
            Class<?> nw6Cls = Class.forName("nw6");

            // Lell is a Kotlin empty subclass of abstract Ltdi(String,
            // Set<String>) — at bytecode level the host does
            // `new-instance Lell; invoke Ltdi.<init>`, but
            // ellCls.getDeclaredConstructor(String.class, Set.class)
            // returns nothing because Lell declares no ctor itself.
            // Workaround: allocate Lell via sun.misc.Unsafe (skips
            // ctor entirely) and reflect-set the inherited Ltdi
            // fields a (key) and b (locales).
            Class<?> unsafeCls = Class.forName("sun.misc.Unsafe");
            Field theUnsafe = unsafeCls.getDeclaredField("theUnsafe");
            theUnsafe.setAccessible(true);
            Object unsafe = theUnsafe.get(null);
            Object label = unsafeCls.getMethod("allocateInstance", Class.class)
                .invoke(unsafe, ellCls);
            Field aField = tdiCls.getDeclaredField("a");
            aField.setAccessible(true);
            aField.set(label, "string:bh_pc_vibration_label");
            Field bField = tdiCls.getDeclaredField("b");
            bField.setAccessible(true);
            bField.set(label, Collections.emptySet());

            final BhMenuRowClick handler = new BhMenuRowClick();
            Object click = java.lang.reflect.Proxy.newProxyInstance(
                nw6Cls.getClassLoader(),
                new Class<?>[]{ nw6Cls },
                (proxy, method, args) -> {
                    if ("invoke".equals(method.getName()) && method.getParameterCount() == 0) {
                        return handler.invoke(null);
                    }
                    if ("equals".equals(method.getName())) return proxy == args[0];
                    if ("hashCode".equals(method.getName())) return System.identityHashCode(proxy);
                    if ("toString".equals(method.getName())) return "BhLibPopupRowClick";
                    return null;
                }
            );

            // Lz4e(Lell;Lnw6;I)V synthetic ctor — int=0 should be a
            // safe default group/category marker.
            Constructor<?> z4eCtor =
                z4eCls.getDeclaredConstructor(ellCls, nw6Cls, int.class);
            z4eCtor.setAccessible(true);
            Object row = z4eCtor.newInstance(label, click, 0);

            augmented.add(row);
            return augmented;
        } catch (Throwable t) {
            Log.w(TAG, "appendLibraryPopupRow failed", t);
            return safeReturn(original);
        }
    }

    @SuppressWarnings("unchecked")
    private static List<Object> safeReturn(Object o) {
        if (o instanceof List) return (List<Object>) o;
        return new ArrayList<>();
    }

    /**
     * Patched into the resolver Lxd3.l1 to short-circuit our sentinel
     * key BEFORE it hits the Compose Multiplatform resource lookup
     * (which throws "Resource with ID='string:bh_pc_vibration_label'
     * not found" because the runtime expects a manifest registration
     * alongside the .cvr entry, and just appending to the .cvr isn't
     * enough).
     *
     * Returns the row label when our sentinel key matches; returns
     * null otherwise so the stock resolver path runs unchanged.
     */
    public static String maybeResolveCustomLabel(Object ell) {
        try {
            Field aField = Class.forName("tdi").getDeclaredField("a");
            aField.setAccessible(true);
            Object key = aField.get(ell);
            if (key == null) return null;
            if ("string:bh_pc_vibration_label".equals(key)) {
                return "PC Vibration Settings";
            }
        } catch (Throwable t) {
            Log.w(TAG, "maybeResolveCustomLabel error", t);
        }
        return null;
    }

    /** If a WineActivity is in the stack, grab its gameId Intent extra. */
    private static String sniffGameIdFromStack() {
        try {
            Class<?> atCls = Class.forName("android.app.ActivityThread");
            Method cur = atCls.getMethod("currentActivityThread");
            Object at = cur.invoke(null);
            if (at == null) return null;
            Field fActs = atCls.getDeclaredField("mActivities");
            fActs.setAccessible(true);
            Object acts = fActs.get(at);
            if (!(acts instanceof Map)) return null;
            for (Object record : ((Map<?, ?>) acts).values()) {
                if (record == null) continue;
                Field fAct = record.getClass().getDeclaredField("activity");
                fAct.setAccessible(true);
                Object a = fAct.get(record);
                if (!(a instanceof Activity)) continue;
                String clsName = a.getClass().getName();
                if (!clsName.endsWith(".WineActivity")) continue;
                Intent it = ((Activity) a).getIntent();
                if (it == null) continue;
                String gid = it.getStringExtra("gameId");
                if (gid != null && !gid.isEmpty()) return gid;
            }
        } catch (Throwable ignored) { }
        return null;
    }
}
