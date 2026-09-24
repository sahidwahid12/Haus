package com.haus.app.net

import com.haus.app.util.Constants
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONObject
import java.util.concurrent.TimeUnit

enum class WsStatus { CONNECTING, OPEN, CLOSED, ERROR, UNAUTHORIZED }

interface WsListener {
    fun onStatus(status: WsStatus)
    fun onOutput(data: String)
}

/**
 * Native OkHttp WebSocket client that bridges to the Haus backend.
 *  Server messages:
 *      {"type":"output","data":"..."}     -> rendered in terminal
 *      {"type":"error","message":"..."}   -> unauthorized from server
 *  Client messages:
 *      {"type":"input","data":"..."}      -> user keystrokes / pasted text
 *      {"type":"resize","rows":r,"cols":c}
 */
class TerminalWsClient(private val token: String, private val listener: WsListener) {

    private val client = OkHttpClient.Builder()
        .pingInterval(15, TimeUnit.SECONDS)
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS) // no read timeout (long-lived)
        .build()

    private var ws: WebSocket? = null

    fun connect() {
        listener.onStatus(WsStatus.CONNECTING)
        val url = Constants.WS_URL.removeSuffix("/") + "/ws?token=" + token
        val request = Request.Builder().url(url).build()
        ws = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                listener.onStatus(WsStatus.OPEN)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    val o = JSONObject(text)
                    when (o.optString("type")) {
                        "output" -> listener.onOutput(o.optString("data"))
                        "error" -> listener.onStatus(WsStatus.UNAUTHORIZED)
                    }
                } catch (_: Exception) {
                }
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                onMessage(webSocket, bytes.utf8())
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                // 401/403 = bad token; anything else = transient network error.
                val code = response?.code
                listener.onStatus(if (code == 401 || code == 403) WsStatus.UNAUTHORIZED else WsStatus.ERROR)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                listener.onStatus(WsStatus.CLOSED)
            }
        })
    }

    fun sendInput(data: String) {
        ws?.send(JSONObject().apply {
            put("type", "input")
            put("data", data)
        }.toString())
    }

    fun sendResize(rows: Int, cols: Int) {
        ws?.send(JSONObject().apply {
            put("type", "resize")
            put("rows", rows)
            put("cols", cols)
        }.toString())
    }

    fun close() {
        ws?.close(1000, null)
        ws = null
    }
}