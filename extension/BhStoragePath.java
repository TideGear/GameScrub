package app.revanced.extension.gamehub;

import android.content.Context;
import android.content.SharedPreferences;

import java.io.File;

public final class BhStoragePath {

    private BhStoragePath() {}

    /**
     * SD card on:  {sdCardRoot}/bannerhub/{storeFolder}/{gameName}
     * SD card off: {filesDir}/{storeFolder}/{gameName}
     */
    public static File getInstallDir(Context ctx, String storeFolder, String gameName) {
        return new File(getStoreBase(ctx, storeFolder), gameName);
    }

    public static File getStoreBase(Context ctx, String storeFolder) {
        SharedPreferences prefs = ctx.getSharedPreferences("steam_storage_pref", 0);
        if (prefs.getBoolean("use_custom_storage", false)) {
            String sdPath = prefs.getString("steam_storage_path", null);
            if (sdPath != null && !sdPath.isEmpty()) {
                return new File(new File(sdPath, "bannerhub"), storeFolder);
            }
        }
        return new File(ctx.getFilesDir(), storeFolder);
    }
}
