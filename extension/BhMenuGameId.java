package com.xj.winemu.common;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import java.lang.reflect.Method;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Shared per-game id capture for the injected per-game vibration menu row.
 *
 * GameHub resolves a row's gameId from a *running* WineActivity. From a
 * pre-launch More Menu / library popup there is none, so without this
 * capture our PC Vibration Settings row falls back to global prefs. The
 * smali apply_menu_patches.py injects a single
 *   invoke-static/range {p0 .. p0}, BhMenuGameId.captureGameId(Object)V
 * at index 0 of the three per-game menu builders (Lx57.a More Menu,
 * Lted.f library-tile popup, Lpzc.j0 library-list popup); p0 is the
 * menu-data param in each. This runs once per menu open and stashes
 * the id here. BhMenuRowClick.invoke reads getCaptured() when the row
 * is tapped.
 *
 * The id is parsed from menuData.toString(): GameHub's Kotlin
 * data/value classes render a stable ServerGameId(value=&lt;int&gt;) or
 * gameId=&lt;int&gt; token regardless of R8 field renaming. For Laub
 * (library-list popup, holds a kept-name GameInfo) we additionally
 * walk the declared fields for a GameInfo instance by type rather than
 * by name.
 *
 * Mirrors the captured id to SharedPreferences as well. The capture
 * runs in the main UI process, but BhVibrationController consumers
 * also run inside com.xj.winemu.WineActivity which the manifest pins
 * to a separate ":wine" process. A static field doesn't cross that
 * boundary, so we cross via prefs so the launch-time consumers still
 * see the captured id.
 */
public final class BhMenuGameId {

    private static final String TAG = "BhMenuGameId";

    private static final Pattern P_SERVER =
        Pattern.compile("ServerGameId\\(value=(-?\\d+)\\)");
    private static final Pattern P_GAMEID =
        Pattern.compile("gameId=(\\d+)");

    private static volatile String sCapturedGameId;

    private static final String PREFS_FILE = "bh_menu_gameid";
    private static final String PREFS_KEY  = "id";

    private BhMenuGameId() { }

    /** Injected at index 0 of the menu builders with the menu-data param. */
    public static void captureGameId(Object menuData) {
        try {
            String id = resolve(menuData);
            sCapturedGameId = id;
            if (id != null && !id.isEmpty()) persist(id);
        } catch (Throwable t) {
            Log.w(TAG, "captureGameId failed", t);
        }
    }

    /**
     * Last captured per-game id, or null. In-process static first;
     * on a miss (the ":wine" launch process where the static was
     * never set) read the disk mirror written by the menu open in
     * the main process.
     */
    public static String getCaptured() {
        String id = sCapturedGameId;
        if (id != null && !id.isEmpty()) return id;
        id = readPersisted();
        if (id != null && !id.isEmpty()) {
            sCapturedGameId = id;
            return id;
        }
        return null;
    }

    private static void persist(String id) {
        try {
            SharedPreferences sp = prefs();
            if (sp != null) sp.edit().putString(PREFS_KEY, id).commit();
        } catch (Throwable t) {
            Log.w(TAG, "persist failed", t);
        }
    }

    private static String readPersisted() {
        try {
            SharedPreferences sp = prefs();
            if (sp != null) return sp.getString(PREFS_KEY, null);
        } catch (Throwable ignored) { }
        return null;
    }

    /** App context via ActivityThread — no Context is plumbed into the row. */
    private static SharedPreferences prefs() {
        try {
            Class<?> at = Class.forName("android.app.ActivityThread");
            Method m = at.getMethod("currentApplication");
            Object app = m.invoke(null);
            if (app instanceof Context) {
                return ((Context) app).getApplicationContext()
                        .getSharedPreferences(PREFS_FILE, Context.MODE_PRIVATE);
            }
        } catch (Throwable ignored) { }
        return null;
    }

    private static final String GAMEINFO_CLS =
        "com.xiaoji.egggame.game.di.model.game.GameInfo";

    private static String resolve(Object menuData) {
        if (menuData == null) return null;

        // 1) toString() token — works for Lf37 (More Menu) and Lued
        //    (tile popup) which both expose stable ServerGameId / gameId
        //    tokens regardless of R8 renaming.
        try {
            String s = String.valueOf(menuData);
            if (s != null) {
                Matcher m = P_SERVER.matcher(s);
                if (m.find()) return m.group(1);
                m = P_GAMEID.matcher(s);
                if (m.find()) return m.group(1);
            }
        } catch (Throwable ignored) { }

        // 2) GameInfo.getServerGameId() — works for Laub which holds a
        //    kept-name GameInfo. The class FQN is preserved by R8 keep
        //    rules, but field/accessor names are not, so we locate the
        //    GameInfo by VALUE type rather than by name.
        try {
            Class<?> giCls = Class.forName(GAMEINFO_CLS);
            Object gi = (giCls.isInstance(menuData)) ? menuData
                                                     : findFieldOfType(menuData, giCls);
            if (gi != null) {
                Method g = giCls.getMethod("getServerGameId");
                Object id = g.invoke(gi);
                if (id != null) return String.valueOf(id);
            }
        } catch (Throwable ignored) { }

        return null;
    }

    /** Shallow scan of host's declared fields for an instance of {@code type}. */
    private static Object findFieldOfType(Object host, Class<?> type) {
        try {
            for (java.lang.reflect.Field f : host.getClass().getDeclaredFields()) {
                if (!type.isAssignableFrom(f.getType())) continue;
                f.setAccessible(true);
                Object v = f.get(host);
                if (type.isInstance(v)) return v;
            }
        } catch (Throwable ignored) { }
        return null;
    }
}
