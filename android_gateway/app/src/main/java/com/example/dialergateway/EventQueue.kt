package com.example.dialergateway

import android.content.Context
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * Events (incoming call, incoming SMS, call status) are saved to disk first and sent with retries.
 * Each event carries a fixed event_id, so a retry can never create a duplicate on the server.
 */
object EventQueue {
    private const val KEY = "queue"
    private const val MAX_AGE_MS = 24 * 60 * 60 * 1000L
    private val lock = Any()
    private val running = AtomicBoolean(false)

    private fun prefs(c: Context) = c.getSharedPreferences("gateway_queue", Context.MODE_PRIVATE)
    private fun load(c: Context) = JSONArray(prefs(c).getString(KEY, "[]"))
    private fun save(c: Context, a: JSONArray) = prefs(c).edit().putString(KEY, a.toString()).apply()

    fun enqueue(ctx: Context, path: String, body: JSONObject) {
        val c = ctx.applicationContext
        synchronized(lock) {
            val a = load(c)
            a.put(JSONObject().put("path", path).put("body", body).put("ts", System.currentTimeMillis()))
            save(c, a)
        }
        flush(c)
    }

    private fun first(c: Context): JSONObject? = synchronized(lock) { load(c).optJSONObject(0) }

    private fun dropFirst(c: Context) = synchronized(lock) {
        val old = load(c)
        val rest = JSONArray()
        for (i in 1 until old.length()) rest.put(old.get(i))
        save(c, rest)
    }

    fun flush(ctx: Context) {
        val c = ctx.applicationContext
        if (!running.compareAndSet(false, true)) return
        thread(name = "event-queue") {
            try {
                var wait = 2_000L
                while (true) {
                    val item = first(c) ?: break
                    if (System.currentTimeMillis() - item.optLong("ts") > MAX_AGE_MS) { dropFirst(c); continue }
                    val server = Config.serverUrl(c)
                    val key = Config.apiKey(c)
                    if (server.isEmpty() || key.isEmpty()) break
                    val req = Request.Builder()
                        .url(server + item.getString("path"))
                        .header("X-Gateway-Key", key)
                        .post(item.getJSONObject("body").toString().toRequestBody("application/json".toMediaType()))
                        .build()
                    val code: Int = try {
                        Net.http.newCall(req).execute().use { it.code }
                    } catch (e: Exception) {
                        -1 // no network or server down
                    }
                    if (code in 200..299) {
                        dropFirst(c)
                        wait = 2_000L
                    } else if (code in 400..499 && code != 401 && code != 403 && code != 429) {
                        dropFirst(c) // the payload itself is bad, retrying would never help
                    } else {
                        Thread.sleep(wait)
                        wait = (wait * 2).coerceAtMost(60_000L)
                    }
                }
            } finally {
                running.set(false)
            }
        }
    }
}
