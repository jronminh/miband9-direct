package dev.miband.standalone;

import android.app.Notification;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

/**
 * Forwards phone notifications (SMS/calls/app alerts) to the band. Requires
 * the user to grant "Notification access" once in Settings (MainActivity has
 * a button for that). Minimal filtering only: skip our own notifications and
 * ongoing/foreground-service notifications; allow/deny lists are future work.
 */
public class NotifyListenerService extends NotificationListenerService {

    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        if (sbn == null) return;
        String pkg = sbn.getPackageName();
        if (pkg == null || pkg.equals(getPackageName())) return;

        Notification n = sbn.getNotification();
        if (n == null) return;
        if ((n.flags & Notification.FLAG_ONGOING_EVENT) != 0) return;
        if ((n.flags & Notification.FLAG_FOREGROUND_SERVICE) != 0) return;

        Bundle extras = n.extras;
        CharSequence titleCs = extras != null ? extras.getCharSequence(Notification.EXTRA_TITLE) : null;
        CharSequence textCs = extras != null ? extras.getCharSequence(Notification.EXTRA_TEXT) : null;
        String title = titleCs != null ? titleCs.toString() : "";
        String text = textCs != null ? textCs.toString() : "";
        if (title.isEmpty() && text.isEmpty()) return;

        String app = appLabel(pkg);
        BleService.forwardNotification(pkg, app, title, text);
    }

    private String appLabel(String pkg) {
        try {
            PackageManager pm = getPackageManager();
            ApplicationInfo ai = pm.getApplicationInfo(pkg, 0);
            return pm.getApplicationLabel(ai).toString();
        } catch (Throwable t) {
            return pkg;
        }
    }
}
