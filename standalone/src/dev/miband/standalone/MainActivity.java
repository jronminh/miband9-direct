package dev.miband.standalone;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.PowerManager;
import android.provider.Settings;
import android.text.method.ScrollingMovementMethod;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

/**
 * Plain-views UI (no layout XML, no resource IDs to wire up): status,
 * MAC + auth-key entry, permission/settings shortcuts, start/stop, log path.
 */
public class MainActivity extends Activity {
    private TextView status;
    private EditText macField, keyField;
    private final Handler handler = new Handler();

    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            status.setText("BLE state: " + BleService.stateName(BleService.currentState())
                    + "\nLog: " + DataLogger.lastWriteSummary());
            handler.postDelayed(this, 3000);
        }
    };

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);

        SharedPreferences prefs = getSharedPreferences("standalone", 0);

        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(16);
        root.setPadding(pad, pad, pad, pad);
        scroll.addView(root);
        setContentView(scroll);

        status = new TextView(this);
        status.setMovementMethod(new ScrollingMovementMethod());
        addSection(root, "Status", status);

        macField = new EditText(this);
        macField.setHint("Band MAC address, e.g. AA:BB:CC:DD:EE:FF");
        macField.setText(prefs.getString("mac", ""));
        final SharedPreferences fprefs = prefs;
        Button saveMac = button("Save MAC + (re)connect", new View.OnClickListener() {
            @Override public void onClick(View v) {
                String mac = macField.getText().toString().trim();
                fprefs.edit().putString("mac", mac).apply();
                Intent i = new Intent(MainActivity.this, BleService.class);
                i.putExtra("mac", mac);
                startForegroundService(i);
                toast("saved, connecting…");
            }
        });
        addSection(root, "Band MAC", macField, saveMac);

        keyField = new EditText(this);
        keyField.setHint("32-hex-char auth key");
        keyField.setText(prefs.getString("authkey", ""));
        Button saveKey = button("Save auth key", new View.OnClickListener() {
            @Override public void onClick(View v) {
                fprefs.edit().putString("authkey", keyField.getText().toString().trim()).apply();
                toast("saved; reconnect to use it");
            }
        });
        addSection(root, "Auth key", keyField, saveKey);

        Button perms = button("Grant Bluetooth + notification permissions", new View.OnClickListener() {
            @Override public void onClick(View v) { requestRuntimePermissions(); }
        });
        Button notifAccess = button("Open notification-listener settings", new View.OnClickListener() {
            @Override public void onClick(View v) {
                startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS));
            }
        });
        Button filesAccess = button("Open all-files-access settings", new View.OnClickListener() {
            @Override public void onClick(View v) { openAllFilesAccess(); }
        });
        Button battOpt = button("Ignore battery optimizations", new View.OnClickListener() {
            @Override public void onClick(View v) { requestIgnoreBatteryOptimizations(); }
        });
        addSection(root, "One-time setup", perms, notifAccess, filesAccess, battOpt);

        Button start = button("Start service", new View.OnClickListener() {
            @Override public void onClick(View v) {
                startForegroundService(new Intent(MainActivity.this, BleService.class));
            }
        });
        Button stop = button("Stop service", new View.OnClickListener() {
            @Override public void onClick(View v) {
                stopService(new Intent(MainActivity.this, BleService.class));
            }
        });
        addSection(root, "Service", start, stop);
    }

    @Override
    protected void onResume() {
        super.onResume();
        handler.post(refresh);
    }

    @Override
    protected void onPause() {
        handler.removeCallbacks(refresh);
        super.onPause();
    }

    private void requestRuntimePermissions() {
        java.util.List<String> perms = new java.util.ArrayList<>();
        if (Build.VERSION.SDK_INT >= 31) {
            perms.add(Manifest.permission.BLUETOOTH_CONNECT);
            perms.add(Manifest.permission.BLUETOOTH_SCAN);
        }
        if (Build.VERSION.SDK_INT >= 33) {
            perms.add(Manifest.permission.POST_NOTIFICATIONS);
        }
        if (perms.isEmpty()) {
            toast("no runtime permissions needed on this Android version");
            return;
        }
        requestPermissions(perms.toArray(new String[0]), 1);
    }

    private void openAllFilesAccess() {
        if (Build.VERSION.SDK_INT >= 30) {
            try {
                Intent i = new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                        Uri.parse("package:" + getPackageName()));
                startActivity(i);
            } catch (Throwable t) {
                startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
            }
        } else {
            toast("pre-Android-11: storage permission is granted at install/runtime automatically");
        }
    }

    private void requestIgnoreBatteryOptimizations() {
        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        if (pm != null && !pm.isIgnoringBatteryOptimizations(getPackageName())) {
            Intent i = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                    Uri.parse("package:" + getPackageName()));
            startActivity(i);
        } else {
            toast("already exempt (or unsupported on this Android version)");
        }
        toast("Samsung devices also need: Settings > Battery > Background usage limits — exclude this app manually");
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_LONG).show();
    }

    private int dp(int v) {
        return (int) (v * getResources().getDisplayMetrics().density);
    }

    private Button button(String label, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(label);
        b.setOnClickListener(l);
        return b;
    }

    private void addSection(LinearLayout root, String title, View... views) {
        TextView t = new TextView(this);
        t.setText(title);
        t.setTextSize(16);
        t.setPadding(0, dp(12), 0, dp(4));
        root.addView(t);
        for (View v : views) root.addView(v);
    }
}
