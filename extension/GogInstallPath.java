package app.revanced.extension.gamehub;

import android.content.Context;

import java.io.File;

public final class GogInstallPath {

    private GogInstallPath() {}

    public static File getInstallDir(Context ctx, String dirName) {
        return BhStoragePath.getInstallDir(ctx, "gog_games", dirName);
    }
}
