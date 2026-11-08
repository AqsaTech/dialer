package com.example.dialergateway

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import android.telephony.TelephonyManager
import org.json.JSONObject
import java.util.UUID

class PhoneStateReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (!Config.enabled(ctx)) return
        val state = intent.getStringExtra(TelephonyManager.EXTRA_STATE) ?: return
        @Suppress("DEPRECATION")
        val number = intent.getStringExtra(TelephonyManager.EXTRA_INCOMING_NUMBER)
        CallTracker.onState(ctx.applicationContext, state, number, Slots.fromIntent(ctx, intent))
    }
}

class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (!Config.enabled(ctx)) return
        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        if (parts.isEmpty()) return
        val sender = parts.first().originatingAddress ?: "unknown"
        val body = parts.joinToString("") { it.messageBody ?: "" }
        if (body.isBlank()) return
        EventQueue.enqueue(
            ctx, "/webhook/incoming-sms",
            JSONObject()
                .put("sim_slot", Slots.fromIntent(ctx, intent))
                .put("remote_number", sender)
                .put("body", body)
                .put("event_id", UUID.randomUUID().toString()),
        )
    }
}

/** Reports whether an SMS we were asked to send actually left the phone. */
class SmsSentReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        val logId = intent.getLongExtra("log_id", -1)
        if (logId < 0) return
        GatewayService.sendResult(logId, if (resultCode == Activity.RESULT_OK) "sent" else "failed")
    }
}

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (Config.enabled(ctx)) GatewayService.start(ctx)
    }
}
