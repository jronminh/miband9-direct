package dev.miband.standalone.proto;

import static dev.miband.standalone.proto.Protobuf.*;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/**
 * Command builders + reply parsers for the subset of the protocol this app
 * needs: battery read, phone-notification forward, notification dismiss.
 * Port of the relevant parts of client/commands.py and store/data.py.
 */
public final class Commands {
    private Commands() {}

    public static final int TYPE_DEVICE = 2, SUB_BATTERY = 1;
    public static final int TYPE_NOTIFICATION = 7, SUB_NOTIFY = 0, SUB_DISMISS = 1;

    /** Command{type=7, subtype=0, notification{notification2{notification3{...}}}}. */
    public static byte[] buildNotification(int nid, String pkg, String app, String title, String body) {
        String ts = timestamp();
        byte[] n3 = concatAll(
                pbBytes(1, pkg),
                pbBytes(2, app),
                pbBytes(3, title),
                pbBytes(4, ""),
                pbBytes(5, body),
                pbBytes(6, ts),
                pbVarint(7, nid));
        byte[] notification = pbBytes(3, pbBytes(1, n3));
        return pbBytes(9, notification);
    }

    /** Dismiss: NotificationDismiss{NotificationId{id, package}}. */
    public static byte[] buildDismiss(int nid, String pkg) {
        byte[] nidMsg = concatAll(pbVarint(1, nid), pbBytes(2, pkg));
        byte[] dismiss = pbBytes(1, nidMsg);
        return pbBytes(9, pbBytes(4, dismiss));
    }

    public static final class Battery {
        public final int level;
        public final int state;
        Battery(int level, int state) {
            this.level = level;
            this.state = state;
        }
    }

    /** Extract {level, state} from a (2,1) reply body, or null. */
    public static Battery parseBattery(int ctype, int csub, byte[] body) {
        if (ctype != TYPE_DEVICE || csub != SUB_BATTERY) return null;
        byte[] system = pbGetBytes(body, 4, WT_BYTES);
        if (system == null) return null;
        byte[] power = pbGetBytes(system, 2, WT_BYTES);
        if (power == null) return null;
        byte[] battery = pbGetBytes(power, 1, WT_BYTES);
        if (battery == null) return null;
        Long level = pbGetVarint(battery, 1);
        Long state = pbGetVarint(battery, 2);
        if (level == null) return null;
        return new Battery(level.intValue(), state == null ? -1 : state.intValue());
    }

    private static String timestamp() {
        SimpleDateFormat f = new SimpleDateFormat("yyyyMMdd'T'HHmmss", Locale.US);
        return f.format(new Date());
    }
}
