package com.example.dialergateway

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject

/** Keeps the connection to the server open and runs the commands it sends. */
class GatewayService : Service() {
    companion object {
        @Volatile private var socket: WebSocket? = null

        fun start(ctx: Context) {
            ctx.startForegroundService(Intent(ctx, GatewayService::class.java))
        }

        fun stop(ctx: Context) {
            ctx.stopService(Intent(ctx, GatewayService::class.java))
        }

        /** Report progress of a command back to the server. Sent only while the socket is connected. */
        fun sendResult(logId: Long, status: String, duration: Int? = null) {
            val msg = JSONObject().put("type", "result").put("log_id", logId).put("status", status)
            if (duration != null) msg.put("duration_seconds", duration)
            socket?.send(msg.toString())
        }
    }

    private lateinit var worker: Handler
    private var running = false
    private var backoff = 2_000L

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val thread = HandlerThread("gateway-worker").also { it.start() }
        worker = Handler(thread.looper)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val channelId = "gateway"
        getSystemService(NotificationManager::class.java)
            .createNotificationChannel(NotificationChannel(channelId, "Gateway", NotificationManager.IMPORTANCE_LOW))
        val notification = Notification.Builder(this, channelId)
            .setContentTitle("Dialer gateway is running")
            .setContentText("Connected calls and texts are sent to your server")
            .setSmallIcon(android.R.drawable.stat_sys_phone_call)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 34) startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        else startForeground(1, notification)

        if (!running) {
            running = true
            connect()
            heartbeat()
        } else {
            socket?.cancel() // settings may have changed: drop the connection and reconnect with the new ones
        }
        EventQueue.flush(this)
        return START_STICKY
    }

    private fun connect() {
        if (!running) return
        val server = Config.serverUrl(this)
        val key = Config.apiKey(this)
        if (server.isEmpty() || key.isEmpty()) return
        val url = server.replaceFirst("https://", "wss://").replaceFirst("http://", "ws://") + "/ws/gateway"
        val request = Request.Builder().url(url).header("X-Gateway-Key", key).build()

        socket = Net.ws.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                backoff = 2_000L
                EventQueue.flush(this@GatewayService)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val cmd = try { JSONObject(text) } catch (e: Exception) { return }
                if (cmd.has("cmd")) worker.post { CommandExecutor.handle(applicationContext, cmd) }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = scheduleReconnect(webSocket)
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = scheduleReconnect(webSocket)
        })
    }

    private fun scheduleReconnect(closed: WebSocket) {
        if (socket === closed) socket = null
        if (!running) return
        worker.postDelayed({ connect() }, backoff)
        backoff = (backoff * 2).coerceAtMost(60_000L)
    }

    private fun heartbeat() {
        worker.postDelayed({
            socket?.send("{\"type\":\"ping\"}")
            if (running) heartbeat()
        }, 30_000L)
    }

    override fun onDestroy() {
        running = false
        socket?.close(1000, "service stopped")
        socket = null
        worker.looper.quitSafely()
        super.onDestroy()
    }
}
