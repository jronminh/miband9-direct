package dev.miband.standalone;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/**
 * Appends raw, greppable text lines to /sdcard/MiBandLogs/YYYY-MM-DD.txt.
 * Deliberately no schema/format versioning: this is prep data for a future
 * feature, kept as plain "<iso-timestamp>\t<metric>\t<value...>\n" lines.
 */
final class DataLogger {
    static final File DIR = new File(android.os.Environment.getExternalStorageDirectory(), "MiBandLogs");

    private static final SimpleDateFormat DAY = new SimpleDateFormat("yyyy-MM-dd", Locale.US);
    private static final SimpleDateFormat ISO = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US);

    private DataLogger() {}

    static synchronized void append(String metric, String value) {
        try {
            if (!DIR.exists()) DIR.mkdirs();
            Date now = new Date();
            File f = new File(DIR, DAY.format(now) + ".txt");
            try (FileWriter w = new FileWriter(f, true)) {
                w.write(ISO.format(now) + "\t" + metric + "\t" + value + "\n");
            }
        } catch (IOException ignored) {
            // best-effort logging; never crash the service over a write failure
        }
    }

    static String lastWriteSummary() {
        if (!DIR.exists()) return "no log folder yet";
        File f = new File(DIR, DAY.format(new Date()) + ".txt");
        if (!f.exists()) return "no entries today";
        return f.getAbsolutePath() + " (" + f.length() + " bytes)";
    }
}
