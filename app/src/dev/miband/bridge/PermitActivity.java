package dev.miband.bridge;
import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
public class PermitActivity extends Activity {
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        String mac = getIntent().getStringExtra("mac");
        if (mac != null) getSharedPreferences("bridge",0).edit().putString("mac", mac).apply();
        startForegroundService(new Intent(this, BleService.class));
        finish();
    }
}