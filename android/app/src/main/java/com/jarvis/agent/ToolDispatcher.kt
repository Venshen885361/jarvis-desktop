package com.jarvis.agent

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.media.AudioManager
import android.net.Uri
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream

/**
 * 把大腦送來的工具名稱翻成手機動作。名稱與 Python 端 devices/adb.py 完全一致，
 * 大腦不需要知道手機是走 ADB 還是 App。
 *
 * 座標系：截圖會縮到長邊 [MAX_EDGE]，模型回的座標要乘回真實像素；
 * get_ui_tree 給的是真實像素，之後的 click 不縮放 —— 跟著「最後一次看畫面」走。
 */
class ToolDispatcher(private val ctx: Context) {

    companion object {
        const val MAX_EDGE = 1024
        const val JPEG_QUALITY = 70
    }

    @Volatile private var scale = 1.0
    @Volatile private var offsetX = 0
    @Volatile private var offsetY = 0

    private fun a11y(): JarvisAccessibilityService =
        JarvisAccessibilityService.instance
            ?: throw IllegalStateException("無障礙服務未開啟：請到 設定 → 無障礙 → JARVIS 手腳服務 開啟。")

    /** 回傳 {"ok":true,"result":...} / {"ok":true,"image":{...}} / {"ok":false,"error":...}（不含 id）。 */
    fun handle(tool: String, args: JSONObject): JSONObject {
        return try {
            when {
                tool == "ping" -> ok("pong")
                tool.startsWith("computer:") -> computer(tool.substringAfter(':'), args)
                else -> ok(highLevel(tool, args))
            }
        } catch (e: Exception) {
            JSONObject().put("ok", false).put("error", e.message ?: e.toString())
        }
    }

    private fun ok(result: String) = JSONObject().put("ok", true).put("result", result)

    // ------------------------------------------------------------------ 座標
    private fun coord(arr: JSONArray?): Pair<Int, Int> {
        if (arr == null || arr.length() < 2) {
            val dm = ctx.resources.displayMetrics
            return dm.widthPixels / 2 to dm.heightPixels / 2
        }
        val x = Math.round(arr.getDouble(0) / scale).toInt() + offsetX
        val y = Math.round(arr.getDouble(1) / scale).toInt() + offsetY
        return x to y
    }

    // ------------------------------------------------------------------ computer toolset
    private fun computer(action: String, p: JSONObject): JSONObject {
        val s = a11y()
        Thread.sleep(120)
        when (action) {
            "screenshot" -> return screenshot(null)
            "zoom" -> {
                val r = p.optJSONArray("region")
                return screenshot(r)
            }
            "left_click", "double_click", "triple_click", "middle_click" -> {
                val (x, y) = coord(p.optJSONArray("coordinate"))
                val taps = when (action) { "double_click" -> 2; "triple_click" -> 3; else -> 1 }
                repeat(taps) { s.tap(x, y); Thread.sleep(80) }
                return ok("OK")
            }
            "right_click" -> {
                val (x, y) = coord(p.optJSONArray("coordinate"))
                s.longPress(x, y)
                return ok("OK（Android 沒有右鍵，已改為長按）")
            }
            "left_click_drag" -> {
                val (x1, y1) = coord(p.optJSONArray("start_coordinate"))
                val (x2, y2) = coord(p.optJSONArray("coordinate"))
                s.swipe(x1, y1, x2, y2, 600)
                return ok("OK")
            }
            "scroll" -> {
                val (x, y) = coord(p.optJSONArray("coordinate"))
                val amount = p.optInt("scroll_amount", 3) * 250
                val (dx, dy) = when (p.optString("scroll_direction", "down")) {
                    "up" -> 0 to amount
                    "left" -> -amount to 0
                    "right" -> amount to 0
                    else -> 0 to -amount   // 內容往下捲 = 手指往上滑
                }
                s.swipe(x, y, x + dx, y + dy, 300)
                return ok("OK")
            }
            "type" -> return ok(s.typeText(p.optString("text", "")))
            "key" -> {
                val keys = p.optString("text", "").split('+').map { it.trim().lowercase() }.filter { it.isNotEmpty() }
                val times = p.optInt("repeat", 1).coerceIn(1, 20)
                repeat(times) {
                    for (k in keys) {
                        val done = when (k) {
                            "return", "enter", "kp_enter" -> s.pressEnterOnFocused()
                            "backspace", "delete" -> backspace(s)
                            "volumeup" -> volume(AudioManager.ADJUST_RAISE)
                            "volumedown" -> volume(AudioManager.ADJUST_LOWER)
                            "volumemute" -> volume(AudioManager.ADJUST_TOGGLE_MUTE)
                            else -> s.globalKey(k)
                        }
                        if (!done) throw IllegalArgumentException("Android 不支援按鍵：$k")
                    }
                }
                return ok("OK")
            }
            "mouse_move" -> return ok("OK（Android 沒有游標，已略過）")
            "cursor_position" -> return ok("[0, 0]（Android 沒有游標）")
            "hold_key", "wait" -> {
                Thread.sleep((p.optDouble("duration", 1.0) * 1000).toLong().coerceIn(0L, 30000L))
                return ok("OK")
            }
            "left_mouse_down", "left_mouse_up" -> return ok("OK（Android 以 swipe 取代按住/放開，已略過）")
        }
        throw IllegalArgumentException("不支援的 computer action：$action")
    }

    private fun backspace(s: JarvisAccessibilityService): Boolean {
        // 沒有原生刪除鍵動作：把焦點框的文字去掉最後一個字
        val root = s.rootInActiveWindow ?: return false
        val node = root.findFocus(android.view.accessibility.AccessibilityNodeInfo.FOCUS_INPUT) ?: return false
        val t = node.text?.toString() ?: return true
        val args = android.os.Bundle().apply {
            putCharSequence(android.view.accessibility.AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, t.dropLast(1))
        }
        return node.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_SET_TEXT, args)
    }

    private fun volume(direction: Int): Boolean {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        am.adjustStreamVolume(AudioManager.STREAM_MUSIC, direction, AudioManager.FLAG_SHOW_UI)
        return true
    }

    // ------------------------------------------------------------------ 截圖
    private fun screenshot(region: JSONArray?): JSONObject {
        var bmp = a11y().screenshot() ?: throw IllegalStateException("截圖失敗（可能是受保護畫面或螢幕已鎖定）")
        var ox = 0; var oy = 0
        if (region != null && region.length() == 4) {
            val (x0, y0) = coord(JSONArray().put(region.getDouble(0)).put(region.getDouble(1)))
            val (x1, y1) = coord(JSONArray().put(region.getDouble(2)).put(region.getDouble(3)))
            val l = x0.coerceIn(0, bmp.width - 1); val t = y0.coerceIn(0, bmp.height - 1)
            val r = x1.coerceIn(l + 1, bmp.width); val b = y1.coerceIn(t + 1, bmp.height)
            bmp = Bitmap.createBitmap(bmp, l, t, r - l, b - t)
            ox = l; oy = t
        }
        val longEdge = maxOf(bmp.width, bmp.height)
        val sc = if (longEdge > MAX_EDGE) MAX_EDGE.toDouble() / longEdge else 1.0
        val out = if (sc < 1.0)
            Bitmap.createScaledBitmap(bmp, (bmp.width * sc).toInt(), (bmp.height * sc).toInt(), true)
        else bmp
        val bos = ByteArrayOutputStream()
        out.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, bos)
        scale = sc; offsetX = ox; offsetY = oy
        val img = JSONObject()
            .put("b64", Base64.encodeToString(bos.toByteArray(), Base64.NO_WRAP))
            .put("media_type", "image/jpeg")
            .put("width", out.width)
            .put("height", out.height)
        return JSONObject().put("ok", true).put("image", img)
    }

    // ------------------------------------------------------------------ 高階工具
    private fun highLevel(tool: String, a: JSONObject): String {
        when (tool) {
            "get_ui_tree" -> {
                val tree = a11y().uiTree()
                scale = 1.0; offsetX = 0; offsetY = 0   // 之後的座標是真實像素
                return tree
            }
            "open_application" -> {
                val q = a.optString("app_name", "")
                val pkg = findPackage(q) ?: return "Sir, 手機上找不到「$q」這個 App。"
                val intent = ctx.packageManager.getLaunchIntentForPackage(pkg)
                    ?: return "Sir, $pkg 沒有可啟動的畫面。"
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                ctx.startActivity(intent)
                return "Sir, 已在手機上開啟 ${appLabel(pkg)}。"
            }
            "focus_window" -> return highLevel("open_application", JSONObject().put("app_name", a.optString("keyword", "")))
            "open_url" -> {
                var url = a.optString("url", "")
                if (!url.startsWith("http://") && !url.startsWith("https://")) url = "https://$url"
                ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                return "Sir, 已在手機上開啟 $url。"
            }
            "set_volume" -> {
                val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
                when (a.optString("action", "up")) {
                    "up" -> am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_RAISE, AudioManager.FLAG_SHOW_UI)
                    "down" -> am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_LOWER, AudioManager.FLAG_SHOW_UI)
                    "mute" -> am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_TOGGLE_MUTE, AudioManager.FLAG_SHOW_UI)
                    "set" -> {
                        val max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
                        val level = (a.optInt("level", 50).coerceIn(0, 100) * max / 100)
                        am.setStreamVolume(AudioManager.STREAM_MUSIC, level, AudioManager.FLAG_SHOW_UI)
                    }
                }
                return "Sir, 手機音量已調整。"
            }
            "lock_screen" -> return if (a11y().globalKey("lock")) "Sir, 手機已鎖定。" else "Sir, 無法鎖定手機。"
            "list_windows" -> return "手機目前前景 App：${a11y().foregroundPackage()}"
            "read_clipboard", "write_clipboard" -> return "Sir, 手機 App 目前不提供剪貼簿存取。"
            "switch_input_method" -> return "Sir, 手機的輸入法切換請直接在鍵盤上操作。"
            "execute_shell" -> return "Sir, 手機 App 不提供 shell。"
            "analyze_camera_view", "camera_search", "lens_search", "open_gesture_selector" ->
                return "Sir, 鏡頭類工具請切回電腦或 Pi 本機執行。"
        }
        return "Sir, 手機不支援工具 $tool。"
    }

    private val aliases = mapOf(
        "line" to "jp.naver.line.android", "youtube" to "com.google.android.youtube",
        "chrome" to "com.android.chrome", "地圖" to "com.google.android.apps.maps",
        "maps" to "com.google.android.apps.maps", "google map" to "com.google.android.apps.maps",
        "instagram" to "com.instagram.android", "ig" to "com.instagram.android",
        "discord" to "com.discord", "spotify" to "com.spotify.music", "gmail" to "com.google.android.gm",
        "設定" to "com.android.settings", "settings" to "com.android.settings",
        "telegram" to "org.telegram.messenger", "twitter" to "com.twitter.android", "x" to "com.twitter.android",
        "threads" to "com.instagram.barcelona",
    )

    private fun findPackage(query: String): String? {
        val q = query.trim().lowercase()
        if (q.isEmpty()) return null
        aliases[q]?.let { if (isInstalled(it)) return it }
        val pm = ctx.packageManager
        val launchables = pm.queryIntentActivities(
            Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), PackageManager.MATCH_ALL
        )
        // 先比 App 顯示名稱（使用者講的通常是這個），再比 package 名
        val byLabel = launchables.firstOrNull { it.loadLabel(pm).toString().lowercase().replace(" ", "").contains(q.replace(" ", "")) }
        if (byLabel != null) return byLabel.activityInfo.packageName
        return launchables.map { it.activityInfo.packageName }
            .filter { it.lowercase().contains(q.replace(" ", "")) }
            .minByOrNull { it.length }
    }

    private fun isInstalled(pkg: String) = try {
        ctx.packageManager.getPackageInfo(pkg, 0); true
    } catch (e: PackageManager.NameNotFoundException) { false }

    private fun appLabel(pkg: String): String = try {
        ctx.packageManager.getApplicationLabel(ctx.packageManager.getApplicationInfo(pkg, 0)).toString()
    } catch (e: Exception) { pkg.substringAfterLast('.') }
}
