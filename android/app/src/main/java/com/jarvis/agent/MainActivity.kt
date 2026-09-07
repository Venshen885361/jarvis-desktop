package com.jarvis.agent

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

/** 設定頁：三個欄位 + 連線 / 中斷 + 兩個「去授權」按鈕。沒有其他花樣。 */
class MainActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs
    private lateinit var status: TextView
    private lateinit var accStatus: TextView
    private lateinit var log: TextView

    private val statusReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            status.text = intent.getStringExtra("status") ?: return
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        prefs = Prefs(this)

        status = findViewById(R.id.status)
        accStatus = findViewById(R.id.accStatus)
        log = findViewById(R.id.log)
        val url = findViewById<EditText>(R.id.url)
        val token = findViewById<EditText>(R.id.token)
        val name = findViewById<EditText>(R.id.name)

        url.setText(prefs.url)
        token.setText(prefs.token)
        name.setText(prefs.name)

        findViewById<Button>(R.id.connect).setOnClickListener {
            prefs.url = url.text.toString()
            prefs.token = token.text.toString()
            prefs.name = name.text.toString()
            if (!prefs.isConfigured) {
                Toast.makeText(this, "位址要以 ws:// 或 wss:// 開頭", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            if (prefs.token.isEmpty()) {
                Toast.makeText(this, "密語不能空白（跟 .env 的 JARVIS_AGENT_TOKEN 一樣）", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            askNotificationPermission()
            AgentService.start(this)
        }
        findViewById<Button>(R.id.disconnect).setOnClickListener { AgentService.stop(this) }
        findViewById<Button>(R.id.openAccessibility).setOnClickListener {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
        findViewById<Button>(R.id.battery).setOnClickListener { requestIgnoreBattery() }
    }

    override fun onResume() {
        super.onResume()
        ContextCompat.registerReceiver(
            this, statusReceiver, IntentFilter(AgentService.BROADCAST_STATUS), ContextCompat.RECEIVER_NOT_EXPORTED
        )
        status.text = AgentService.lastStatus
        refreshPermissionState()
    }

    override fun onPause() {
        unregisterReceiver(statusReceiver)
        super.onPause()
    }

    private fun refreshPermissionState() {
        val on = JarvisAccessibilityService.isRunning
        accStatus.text = if (on) "無障礙服務：已開啟 ✓" else "無障礙服務：未開啟（JARVIS 無法操作手機）"
        accStatus.setTextColor(if (on) 0xFF4ADE80.toInt() else 0xFFF87171.toInt())

        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        val ignoring = pm.isIgnoringBatteryOptimizations(packageName)
        val lines = mutableListOf(
            "電池最佳化：" + if (ignoring) "已關閉 ✓" else "未關閉（背景可能被殺）",
            "系統：Android ${Build.VERSION.RELEASE} · ${Build.MANUFACTURER} ${Build.MODEL}",
        )
        if (Build.MANUFACTURER.equals("realme", true) || Build.MANUFACTURER.equals("oppo", true)) {
            lines += "realme/OPPO 提醒：設定 → 電池 → App 電池用量 → JARVIS Agent → 「不限制」；" +
                "最近任務把 JARVIS Agent 鎖定，否則無障礙服務重開機後會被關掉。"
        }
        log.text = lines.joinToString("\n")
    }

    private fun requestIgnoreBattery() {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        if (pm.isIgnoringBatteryOptimizations(packageName)) {
            Toast.makeText(this, "已經關閉電池最佳化", Toast.LENGTH_SHORT).show()
            return
        }
        startActivity(
            Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                .setData(Uri.parse("package:$packageName"))
        )
    }

    private fun askNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
    }
}
