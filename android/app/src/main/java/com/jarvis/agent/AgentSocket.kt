package com.jarvis.agent

import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 跟大腦 hub 的 WebSocket 連線（手機是 client，主動連出去，所以 NAT / 熱點 / Tailscale 都通）。
 *
 * 協定與 jarvis/devices/hub.py 對稱：
 *   → {"type":"hello","token":..,"name":..,"platform":"android"}
 *   ← {"type":"hello","ok":true}
 *   ← {"id":1,"tool":"computer:screenshot","args":{}}
 *   → {"id":1,"ok":true,"image":{..}} / {"id":1,"ok":true,"result":".."} / {"id":1,"ok":false,"error":".."}
 *
 * 斷線用指數退避重連（2s → 30s），永不放棄；使用者按「中斷」才停。
 */
class AgentSocket(
    private val url: String,
    private val token: String,
    private val name: String,
    private val dispatcher: ToolDispatcher,
    private val onStatus: (String) -> Unit,
) {
    companion object { private const val TAG = "JarvisSocket" }

    private val client = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)   // 讓 NAT / 省電不會默默把連線收掉
        .readTimeout(0, TimeUnit.SECONDS)
        .build()
    private val worker = Executors.newSingleThreadExecutor()   // 工具一次做一個，跟大腦的同步 loop 對齊
    private val stopped = AtomicBoolean(false)
    private var ws: WebSocket? = null
    private var backoffMs = 2000L

    fun start() {
        stopped.set(false)
        connect()
    }

    fun stop() {
        stopped.set(true)
        ws?.close(1000, "user")
        ws = null
        onStatus("已中斷")
    }

    private fun connect() {
        if (stopped.get()) return
        onStatus("連線中… $url")
        val req = Request.Builder().url(url).build()
        ws = client.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                backoffMs = 2000L
                webSocket.send(
                    JSONObject().put("type", "hello").put("token", token)
                        .put("name", name).put("platform", "android").toString()
                )
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val msg = try { JSONObject(text) } catch (e: Exception) { return }
                if (msg.optString("type") == "hello") {
                    if (msg.optBoolean("ok")) onStatus("已連線：$name @ $url")
                    else onStatus("被拒絕：${msg.optString("error", "token 錯誤")}")
                    return
                }
                if (!msg.has("id")) return
                val id = msg.get("id")
                val tool = msg.optString("tool", "")
                val args = msg.optJSONObject("args") ?: JSONObject()
                worker.execute {
                    val t0 = System.currentTimeMillis()
                    val reply = dispatcher.handle(tool, args)
                    reply.put("id", id)
                    webSocket.send(reply.toString())
                    Log.d(TAG, "$tool ${System.currentTimeMillis() - t0}ms ok=${reply.optBoolean("ok")}")
                    onStatus("已連線 · 最近：$tool")
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.w(TAG, "failure: ${t.message}")
                scheduleReconnect("連線失敗：${t.message ?: t.javaClass.simpleName}")
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                scheduleReconnect("連線關閉（$code）")
            }
        })
    }

    private fun scheduleReconnect(why: String) {
        if (stopped.get()) return
        onStatus("$why，${backoffMs / 1000}s 後重連")
        val delay = backoffMs
        backoffMs = (backoffMs * 2).coerceAtMost(30_000L)
        Thread {
            try { Thread.sleep(delay) } catch (e: InterruptedException) { return@Thread }
            connect()
        }.start()
    }
}
