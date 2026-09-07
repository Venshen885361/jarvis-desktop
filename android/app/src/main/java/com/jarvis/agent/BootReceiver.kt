package com.jarvis.agent

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** 手機重開後把常駐連線拉起來（realme 需要在電池設定放行，否則系統可能不送這個廣播）。 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val prefs = Prefs(context)
        if (prefs.autoStart && prefs.isConfigured) AgentService.start(context)
    }
}
