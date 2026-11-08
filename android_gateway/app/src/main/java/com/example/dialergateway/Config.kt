package com.example.dialergateway

import android.content.Context

object Config {
    private fun p(c: Context) = c.getSharedPreferences("gateway", Context.MODE_PRIVATE)

    fun serverUrl(c: Context): String = p(c).getString("server", "") ?: ""
    fun apiKey(c: Context): String = p(c).getString("key", "") ?: ""
    fun defaultSlot(c: Context): Int = p(c).getInt("slot", 0)
    fun enabled(c: Context): Boolean = p(c).getBoolean("enabled", false)

    fun save(c: Context, server: String, key: String, slot: Int) {
        p(c).edit().putString("server", server.trim().trimEnd('/')).putString("key", key.trim()).putInt("slot", slot).apply()
    }

    fun setEnabled(c: Context, on: Boolean) {
        p(c).edit().putBoolean("enabled", on).apply()
    }
}
