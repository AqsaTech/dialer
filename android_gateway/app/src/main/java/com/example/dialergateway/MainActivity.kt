package com.example.dialergateway

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast

/** One simple screen: server address, gateway key, permissions, start and stop. */
class MainActivity : Activity() {
    private lateinit var server: EditText
    private lateinit var key: EditText
    private lateinit var slot: EditText
    private lateinit var status: TextView

    private val permissions: Array<String> = buildList {
        add(Manifest.permission.READ_PHONE_STATE)
        add(Manifest.permission.READ_CALL_LOG)
        add(Manifest.permission.CALL_PHONE)
        add(Manifest.permission.ANSWER_PHONE_CALLS)
        add(Manifest.permission.SEND_SMS)
        add(Manifest.permission.RECEIVE_SMS)
        if (Build.VERSION.SDK_INT >= 33) add(Manifest.permission.POST_NOTIFICATIONS)
    }.toTypedArray()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = (16 * resources.displayMetrics.density).toInt()
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(pad, pad, pad, pad) }

        fun label(t: String) = TextView(this).apply { text = t; setPadding(0, pad / 2, 0, 0) }
        fun field(hint: String, value: String, type: Int = InputType.TYPE_CLASS_TEXT) =
            EditText(this).apply { this.hint = hint; setText(value); inputType = type; setSingleLine() }
        fun button(t: String, onClick: () -> Unit) =
            Button(this).apply { text = t; setOnClickListener { onClick() } }

        server = field("https://your-server.com", Config.serverUrl(this), InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI)
        key = field("Gateway key (gw_...)", Config.apiKey(this), InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD)
        slot = field("0 or 1", Config.defaultSlot(this).toString(), InputType.TYPE_CLASS_NUMBER)
        status = TextView(this).apply { setPadding(0, pad, 0, 0) }

        root.addView(label("Server address"))
        root.addView(server)
        root.addView(label("Gateway key from the admin panel"))
        root.addView(key)
        root.addView(label("Default SIM slot, used when the phone does not say which SIM was used"))
        root.addView(slot)
        root.addView(button("1. Allow permissions") { requestPermissions(permissions, 1) })
        root.addView(button("2. Stop Android from sleeping this app") {
            startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        })
        root.addView(button("3. Save and start") { saveAndStart() })
        root.addView(button("Stop") {
            Config.setEnabled(this, false)
            GatewayService.stop(this)
            refresh()
        })
        root.addView(status, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        setContentView(root)
        refresh()
    }

    private fun saveAndStart() {
        val s = server.text.toString().trim()
        if (!s.startsWith("http://") && !s.startsWith("https://")) {
            Toast.makeText(this, "The address must start with http:// or https://", Toast.LENGTH_LONG).show()
            return
        }
        if (key.text.isNullOrBlank()) {
            Toast.makeText(this, "Enter the gateway key", Toast.LENGTH_LONG).show()
            return
        }
        Config.save(this, s, key.text.toString(), (slot.text.toString().toIntOrNull() ?: 0).coerceIn(0, 1))
        Config.setEnabled(this, true)
        GatewayService.start(this)
        refresh()
    }

    private fun refresh() {
        val missing = permissions.count { checkSelfPermission(it) != android.content.pm.PackageManager.PERMISSION_GRANTED }
        status.text = buildString {
            append(if (Config.enabled(this@MainActivity)) "Status: running" else "Status: stopped")
            if (missing > 0) append("\n$missing permission(s) still missing. Tap button 1.")
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        refresh()
    }

    override fun onResume() { super.onResume(); refresh() }
}
