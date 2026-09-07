package com.jarvis.agent

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Bitmap
import android.graphics.Path
import android.graphics.Rect
import android.os.Bundle
import android.util.Log
import android.view.Display
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * JARVIS 的「手腳」：所有真的碰到畫面的動作都在這裡。
 *
 * 選 AccessibilityService 而不是 ADB 的理由：
 * - rootInActiveWindow 直接給 UI 樹（文字 + 座標 + 可點），多數任務不用截圖 → token 省一個數量級
 * - dispatchGesture / ACTION_SET_TEXT 是系統正規管道，不會被 realme 的「權限監控」擋
 * - 使用者只要在設定裡開一次，不用開發人員選項、不用配對
 *
 * 這個 service 本身不連網路；AgentService 收到指令後透過 [instance] 呼叫這裡。
 */
class JarvisAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "JarvisA11y"
        @Volatile var instance: JarvisAccessibilityService? = null
            private set
        val isRunning get() = instance != null
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.i(TAG, "accessibility connected")
    }

    override fun onDestroy() {
        instance = null
        super.onDestroy()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) { /* 不需要事件驅動 */ }
    override fun onInterrupt() {}

    // ------------------------------------------------------------------ 手勢
    private fun runGesture(path: Path, durationMs: Long): Boolean {
        val stroke = GestureDescription.StrokeDescription(path, 0, durationMs)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()
        val latch = CountDownLatch(1)
        var ok = false
        val dispatched = dispatchGesture(gesture, object : AccessibilityService.GestureResultCallback() {
            override fun onCompleted(g: GestureDescription?) { ok = true; latch.countDown() }
            override fun onCancelled(g: GestureDescription?) { ok = false; latch.countDown() }
        }, null)
        if (!dispatched) return false
        latch.await(durationMs + 2000, TimeUnit.MILLISECONDS)
        return ok
    }

    fun tap(x: Int, y: Int, durationMs: Long = 60): Boolean {
        val p = Path().apply { moveTo(x.toFloat(), y.toFloat()) }
        return runGesture(p, durationMs)
    }

    fun longPress(x: Int, y: Int): Boolean = tap(x, y, 800)

    fun swipe(x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Long = 400): Boolean {
        val p = Path().apply {
            moveTo(x1.toFloat(), y1.toFloat())
            lineTo(x2.toFloat(), y2.toFloat())
        }
        return runGesture(p, durationMs)
    }

    // ------------------------------------------------------------------ 全域鍵
    fun globalKey(name: String): Boolean {
        val action = when (name.lowercase()) {
            "back", "escape" -> GLOBAL_ACTION_BACK
            "home", "super", "win" -> GLOBAL_ACTION_HOME
            "recents", "app_switch", "alt+tab" -> GLOBAL_ACTION_RECENTS
            "notifications" -> GLOBAL_ACTION_NOTIFICATIONS
            "quick_settings" -> GLOBAL_ACTION_QUICK_SETTINGS
            "power" -> GLOBAL_ACTION_POWER_DIALOG
            "lock" -> GLOBAL_ACTION_LOCK_SCREEN
            "screenshot" -> GLOBAL_ACTION_TAKE_SCREENSHOT
            else -> return false
        }
        return performGlobalAction(action)
    }

    // ------------------------------------------------------------------ 文字
    /** 把文字塞進目前有焦點的輸入框；沒有焦點的框就找第一個可編輯的。支援中文。 */
    fun typeText(text: String, append: Boolean = true): String {
        val root = rootInActiveWindow ?: return "沒有可用的視窗"
        val target = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
            ?: findFirst(root) { it.isEditable }
            ?: return "畫面上沒有正在輸入的文字框，請先點一下輸入框"
        val existing = if (append) (target.text?.toString() ?: "") else ""
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, existing + text)
        }
        val ok = target.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
        return if (ok) "OK" else "輸入框拒絕 SET_TEXT（可能是自繪 / WebView 輸入框）"
    }

    fun pressEnterOnFocused(): Boolean {
        val root = rootInActiveWindow ?: return false
        val target = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT) ?: return false
        // ACTION_IME_ENTER = 鍵盤上的「送出 / 搜尋」鍵（API 30+），比模擬按鍵可靠
        return target.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id)
    }

    private fun findFirst(node: AccessibilityNodeInfo, pred: (AccessibilityNodeInfo) -> Boolean): AccessibilityNodeInfo? {
        if (pred(node)) return node
        for (i in 0 until node.childCount) {
            val c = node.getChild(i) ?: continue
            val r = findFirst(c, pred)
            if (r != null) return r
        }
        return null
    }

    // ------------------------------------------------------------------ UI 樹
    /**
     * 精簡版 UI 樹：一行一個元件，只留有文字 / 描述 / 可點擊且可見的節點。
     * 格式：`🔘 (cx,cy) '文字' #resourceId`，座標是螢幕真實像素，可直接拿去 tap。
     */
    fun uiTree(limit: Int = 120): String {
        val root = rootInActiveWindow ?: return "UI 樹是空的（沒有前景視窗）"
        val rows = ArrayList<String>()
        val bounds = Rect()
        fun walk(n: AccessibilityNodeInfo, depth: Int) {
            if (rows.size >= limit || depth > 40) return
            if (n.isVisibleToUser) {
                val text = (n.text?.toString()?.takeIf { it.isNotBlank() }
                    ?: n.contentDescription?.toString()?.takeIf { it.isNotBlank() }
                    ?: n.hintText?.toString()?.takeIf { it.isNotBlank() && n.isEditable }
                    ?: "")
                val clickable = n.isClickable || n.isEditable
                if (text.isNotEmpty() || clickable) {
                    n.getBoundsInScreen(bounds)
                    if (bounds.width() > 0 && bounds.height() > 0) {
                        val id = n.viewIdResourceName?.substringAfter('/') ?: ""
                        val flag = when {
                            n.isEditable -> "✏️"
                            clickable -> "🔘"
                            else -> "  "
                        }
                        val label = text.replace("\n", " ").take(40)
                        val sb = StringBuilder("$flag (${bounds.centerX()},${bounds.centerY()}) '$label'")
                        if (id.isNotEmpty()) sb.append(" #").append(id)
                        if (n.isChecked) sb.append(" [checked]")
                        rows.add(sb.toString())
                    }
                }
            }
            for (i in 0 until n.childCount) {
                val c = n.getChild(i) ?: continue
                walk(c, depth + 1)
            }
        }
        walk(root, 0)
        val pkg = root.packageName?.toString() ?: "?"
        if (rows.isEmpty()) return "UI 樹是空的（前景 $pkg 可能是遊戲 / 圖片 / 受保護內容），請改用截圖。"
        return "前景 App：$pkg\n元件（🔘=可點 ✏️=輸入框，座標為手機真實像素）：\n" + rows.joinToString("\n")
    }

    fun foregroundPackage(): String = rootInActiveWindow?.packageName?.toString() ?: "unknown"

    // ------------------------------------------------------------------ 截圖
    /** 用無障礙的 takeScreenshot（API 30+），不用 MediaProjection 的授權彈窗。 */
    fun screenshot(): Bitmap? {
        val result = AtomicReference<Bitmap?>()
        val latch = CountDownLatch(1)
        takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : AccessibilityService.TakeScreenshotCallback {
            override fun onSuccess(screenshot: AccessibilityService.ScreenshotResult) {
                val hw = screenshot.hardwareBuffer
                val bmp = Bitmap.wrapHardwareBuffer(hw, screenshot.colorSpace)
                // hardware bitmap 不能直接壓縮，先 copy 成軟體 bitmap
                result.set(bmp?.copy(Bitmap.Config.ARGB_8888, false))
                hw.close()
                latch.countDown()
            }
            override fun onFailure(errorCode: Int) {
                Log.w(TAG, "takeScreenshot failed: $errorCode")
                latch.countDown()
            }
        })
        latch.await(5, TimeUnit.SECONDS)
        return result.get()
    }
}
