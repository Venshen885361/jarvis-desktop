package com.jarvis.agent

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat

/**
 * Foreground Service：讓 WebSocket 連線活在背景，通知列顯示狀態。
 * 沒有這個，Android 幾分鐘內就會把 process 收掉，大腦一叫手機就不在。
 */
class AgentService : Service() {

    companion object {
        const val ACTION_START = "com.jarvis.agent.START"
        const val ACTION_STOP = "com.jarvis.agent.STOP"
        const val BROADCAST_STATUS = "com.jarvis.agent.STATUS"
        private const val CHANNEL = "jarvis_status"
        private const val NOTIF_ID = 1

        @Volatile var lastStatus: String = "尚未連線"
            private set
        @Volatile var running = false
            private set

        fun start(ctx: Context) {
            val i = Intent(ctx, AgentService::class.java).setAction(ACTION_START)
            ctx.startForegroundService(i)
        }

        fun stop(ctx: Context) {
            ctx.startService(Intent(ctx, AgentService::class.java).setAction(ACTION_STOP))
        }
    }

    private var socket: AgentSocket? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                socket?.stop(); socket = null
                running = false
                Prefs(this).autoStart = false
                publish("已中斷")
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
            else -> {
                createChannel()
                val notif = buildNotification("連線中…")
                if (Build.VERSION.SDK_INT >= 34) {
                    startForeground(NOTIF_ID, notif, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
                } else {
                    startForeground(NOTIF_ID, notif)
                }
                if (socket == null) {
                    val p = Prefs(this)
                    socket = AgentSocket(p.url, p.token, p.name, ToolDispatcher(applicationContext)) { publish(it) }
                        .also { it.start() }
                    running = true
                    p.autoStart = true
                }
                return START_STICKY   // 被系統殺掉就自動重啟
            }
        }
    }

    override fun onDestroy() {
        socket?.stop()
        running = false
        super.onDestroy()
    }

    private fun publish(status: String) {
        lastStatus = status
        val nm = getSystemService(NotificationManager::class.java)
        nm.notify(NOTIF_ID, buildNotification(status))
        sendBroadcast(Intent(BROADCAST_STATUS).setPackage(packageName).putExtra("status", status))
    }

    private fun createChannel() {
        val ch = NotificationChannel(CHANNEL, getString(R.string.notif_channel), NotificationManager.IMPORTANCE_LOW)
        getSystemService(NotificationManager::class.java).createNotificationChannel(ch)
    }

    private fun buildNotification(text: String): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val stop = PendingIntent.getService(
            this, 1, Intent(this, AgentService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_jarvis)
            .setContentTitle("JARVIS Agent")
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(open)
            .addAction(0, "中斷", stop)
            .build()
    }
}
