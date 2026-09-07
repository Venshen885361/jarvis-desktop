package com.jarvis.agent

import android.content.Context

/** 三個設定值：大腦位址、密語、裝置名稱。存在私有 SharedPreferences。 */
class Prefs(ctx: Context) {
    private val sp = ctx.getSharedPreferences("jarvis", Context.MODE_PRIVATE)

    var url: String
        get() = sp.getString("url", "") ?: ""
        set(v) = sp.edit().putString("url", v.trim()).apply()

    var token: String
        get() = sp.getString("token", "") ?: ""
        set(v) = sp.edit().putString("token", v.trim()).apply()

    var name: String
        get() = sp.getString("name", "phone") ?: "phone"
        set(v) = sp.edit().putString("name", v.trim().ifEmpty { "phone" }).apply()

    /** 使用者按過「連線」且沒按「中斷」→ 開機自動連 */
    var autoStart: Boolean
        get() = sp.getBoolean("autoStart", false)
        set(v) = sp.edit().putBoolean("autoStart", v).apply()

    val isConfigured get() = url.startsWith("ws://") || url.startsWith("wss://")
}
