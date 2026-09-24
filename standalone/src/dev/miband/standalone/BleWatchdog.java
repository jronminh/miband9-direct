package dev.miband.standalone;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;

/**
 * Second line of defense against the OS killing BleService outright: a
 * persisted, periodic JobScheduler job that just re-starts it. Framework-only
 * (no WorkManager/gradle dependency resolution available in this build).
 * JobScheduler's minimum periodic interval is 15 minutes.
 */
public class BleWatchdog extends JobService {
    static final int JOB_ID = 0xB1;
    static final long PERIOD_MS = 15 * 60 * 1000;

    static void schedule(Context ctx) {
        JobScheduler js = (JobScheduler) ctx.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (js == null) return;
        if (js.getPendingJob(JOB_ID) != null) return; // already scheduled
        JobInfo info = new JobInfo.Builder(JOB_ID, new ComponentName(ctx, BleWatchdog.class))
                .setPeriodic(PERIOD_MS)
                .setPersisted(true) // survives reboot (RECEIVE_BOOT_COMPLETED also re-schedules via BootReceiver)
                .build();
        js.schedule(info);
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        // Starting an already-running service is a harmless no-op (onStartCommand
        // just re-runs, onCreate does not); this is intentionally unconditional.
        getApplicationContext().startForegroundService(new Intent(this, BleService.class));
        jobFinished(params, false);
        return false;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true; // reschedule if the system stopped us early
    }
}
