package dev.miband.bridge;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
public class BootReceiver extends BroadcastReceiver {
    public void onReceive(Context c, Intent i) {
        c.startForegroundService(new Intent(c, BleService.class));
    }
}