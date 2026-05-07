package com.xj.winemu.vibration;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.SeekBar;
import android.widget.Spinner;
import android.widget.TextView;

/**
 * BhVibrationSettingsActivity — dialog-styled settings screen for PC-accurate rumble.
 *
 * Surfaces two controls per game container:
 *   - Mode:      Off | Controller | Device | Both
 *   - Intensity: 0 – 100 %
 *
 * Launched per-game from GameDetailSettingMenu via the static helper
 * {@link #launch(Context, String, String)}. Settings are stored in the
 * stock {@code pc_g_setting<gameId>} SharedPreferences file under prefixed
 * keys ({@code bh_vibration_mode}, {@code bh_vibration_intensity}) so
 * {@code BhSettingsExporter}'s existing per-game export/import path picks
 * them up automatically. Older config files lacking these keys fall back
 * to global defaults.
 */
public class BhVibrationSettingsActivity extends Activity {

    public static final String EXTRA_GAME_ID   = "bh_vibration.gameId";
    public static final String EXTRA_GAME_NAME = "bh_vibration.gameName";

    /** Launch entry point used by the BhVibrationLambda smali stub from
     *  GameDetailSettingMenu's per-game options menu. */
    public static void launch(Context ctx, String gameId, String gameName) {
        Intent it = new Intent(ctx, BhVibrationSettingsActivity.class);
        it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        if (gameId != null) it.putExtra(EXTRA_GAME_ID, gameId);
        if (gameName != null) it.putExtra(EXTRA_GAME_NAME, gameName);
        ctx.startActivity(it);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setBackgroundDrawable(new ColorDrawable(0xCC000000));

        String gameId   = getIntent() != null ? getIntent().getStringExtra(EXTRA_GAME_ID)   : null;
        String gameName = getIntent() != null ? getIntent().getStringExtra(EXTRA_GAME_NAME) : null;

        BhVibrationController ctl = BhVibrationController.getInstance();
        ctl.init(this);
        ctl.setContainerForSettings(gameId);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(24), dp(20), dp(24), dp(20));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(0xFF1B1B1B);
        bg.setCornerRadius(dp(12));
        root.setBackground(bg);

        TextView title = new TextView(this);
        title.setText("PC Vibration Settings");
        title.setTextColor(Color.WHITE);
        title.setTextSize(18);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setPadding(0, 0, 0, dp(4));
        root.addView(title);

        TextView subtitle = new TextView(this);
        if (gameName != null && !gameName.isEmpty()) {
            subtitle.setText(gameName);
        } else if (gameId != null && !gameId.isEmpty()) {
            subtitle.setText("Game " + gameId);
        } else {
            subtitle.setText("Global defaults");
        }
        subtitle.setTextColor(0xFFFFD54F);
        subtitle.setTextSize(13);
        subtitle.setPadding(0, 0, 0, dp(12));
        root.addView(subtitle);

        TextView desc = new TextView(this);
        desc.setText("Routes XInput rumble (low/high motor) from this Wine game to the controller, the phone, or both. Stored with the game's other PC settings.");
        desc.setTextColor(0xFFBBBBBB);
        desc.setTextSize(12);
        desc.setPadding(0, 0, 0, dp(16));
        root.addView(desc);

        // ── Mode ────────────────────────────────────────────────────────────
        TextView modeLabel = new TextView(this);
        modeLabel.setText("Mode");
        modeLabel.setTextColor(Color.WHITE);
        modeLabel.setTextSize(14);
        modeLabel.setPadding(0, 0, 0, dp(6));
        root.addView(modeLabel);

        final Spinner modeSpinner = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_dropdown_item,
                new String[] { "Off", "Controller", "Device", "Both" });
        modeSpinner.setAdapter(adapter);
        modeSpinner.setSelection(clampMode(ctl.getMode()));
        root.addView(modeSpinner);

        // ── Intensity ──────────────────────────────────────────────────────
        LinearLayout intRow = new LinearLayout(this);
        intRow.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout.LayoutParams rowLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        rowLp.topMargin = dp(16);
        intRow.setLayoutParams(rowLp);

        TextView intLabel = new TextView(this);
        intLabel.setText("Intensity");
        intLabel.setTextColor(Color.WHITE);
        intLabel.setTextSize(14);
        intRow.addView(intLabel, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        final TextView intValue = new TextView(this);
        intValue.setText(ctl.getIntensity() + "%");
        intValue.setTextColor(0xFFFFD54F);
        intValue.setTextSize(14);
        intRow.addView(intValue);
        root.addView(intRow);

        final SeekBar bar = new SeekBar(this);
        bar.setMax(100);
        bar.setProgress(ctl.getIntensity());
        LinearLayout.LayoutParams barLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        barLp.topMargin = dp(4);
        bar.setLayoutParams(barLp);
        root.addView(bar);

        // ── Save / Close ───────────────────────────────────────────────────
        LinearLayout btnRow = new LinearLayout(this);
        btnRow.setOrientation(LinearLayout.HORIZONTAL);
        btnRow.setGravity(Gravity.END);
        LinearLayout.LayoutParams btnRowLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        btnRowLp.topMargin = dp(20);
        btnRow.setLayoutParams(btnRowLp);

        Button close = new Button(this);
        close.setText("Close");
        close.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { finish(); }
        });
        btnRow.addView(close);
        root.addView(btnRow);

        // Wire change handlers → save immediately, no commit button needed.
        modeSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int pos, long id) {
                ctl.setMode(pos);
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });
        bar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar sb, int progress, boolean fromUser) {
                intValue.setText(progress + "%");
                if (fromUser) ctl.setIntensity(progress);
            }
            @Override public void onStartTrackingTouch(SeekBar sb) { }
            @Override public void onStopTrackingTouch(SeekBar sb) { }
        });

        FrameLayout wrapper = new FrameLayout(this);
        wrapper.setBackgroundColor(0x00000000);
        FrameLayout.LayoutParams rootLp = new FrameLayout.LayoutParams(
                dp(360), FrameLayout.LayoutParams.WRAP_CONTENT);
        rootLp.gravity = Gravity.CENTER;
        wrapper.addView(root, rootLp);
        setContentView(wrapper);
    }

    private int clampMode(int v) {
        if (v < 0) return 0;
        if (v > 3) return 3;
        return v;
    }

    private int dp(int v) {
        return (int) (v * getResources().getDisplayMetrics().density + 0.5f);
    }
}
