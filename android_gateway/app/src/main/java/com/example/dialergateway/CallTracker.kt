package com.example.dialergateway

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.telephony.TelephonyManager
import org.json.JSONObject
import java.util.UUID

/** Turns Android phone-state broadcasts into events for the server. */
object CallTracker {
    private val handler = Handler(Looper.getMainLooper())
    private var lastState = TelephonyManager.EXTRA_STATE_IDLE

    // inbound call being tracked
    private var inboundId: String? = null
    private var inboundSlot = 0
    private var numberSent = false
    private var answeredAt = 0L
    private var rejectedByCommand = false

    // outbound call started by a server command
    @Volatile var outboundLogId: Long? = null
    private var outboundStart = 0L

    @Synchronized
    fun markRejected() { rejectedByCommand = true }

    @Synchronized
    fun onState(ctx: Context, state: String, number: String?, slot: Int) {
        val wantsNumber = state == TelephonyManager.EXTRA_STATE_RINGING && number != null && inboundId != null && !numberSent
        if (state == lastState && !wantsNumber) return
        val now = System.currentTimeMillis()

        when (state) {
            TelephonyManager.EXTRA_STATE_RINGING -> {
                if (inboundId == null) {
                    inboundId = UUID.randomUUID().toString()
                    inboundSlot = slot
                    numberSent = false
                    answeredAt = 0
                    rejectedByCommand = false
                    // Newer Android versions sometimes deliver the number in a second broadcast.
                    if (number == null) handler.postDelayed({ sendIncoming(ctx, null) }, 1500)
                }
                if (number != null) sendIncoming(ctx, number)
            }
            TelephonyManager.EXTRA_STATE_OFFHOOK -> {
                if (lastState == TelephonyManager.EXTRA_STATE_RINGING && inboundId != null) {
                    sendIncoming(ctx, null) // make sure the server knows about the call first
                    answeredAt = now
                    sendStatus(ctx, "answered", null)
                } else if (outboundLogId != null) {
                    outboundStart = now
                    GatewayService.sendResult(outboundLogId!!, "ringing")
                }
            }
            TelephonyManager.EXTRA_STATE_IDLE -> {
                if (inboundId != null) {
                    sendIncoming(ctx, null)
                    when {
                        answeredAt > 0 -> sendStatus(ctx, "ended", ((now - answeredAt) / 1000).toInt())
                        rejectedByCommand -> Unit // already reported as rejected
                        else -> sendStatus(ctx, "missed", null)
                    }
                    inboundId = null
                } else if (outboundLogId != null) {
                    val id = outboundLogId!!
                    if (outboundStart > 0) GatewayService.sendResult(id, "ended", ((now - outboundStart) / 1000).toInt())
                    else GatewayService.sendResult(id, "failed")
                    outboundLogId = null
                    outboundStart = 0
                }
            }
        }
        lastState = state
    }

    @Synchronized
    private fun sendIncoming(ctx: Context, number: String?) {
        val id = inboundId ?: return
        if (numberSent) return
        numberSent = true
        EventQueue.enqueue(
            ctx, "/webhook/incoming-call",
            JSONObject().put("sim_slot", inboundSlot).put("remote_number", number ?: "unknown").put("event_id", id),
        )
    }

    private fun sendStatus(ctx: Context, status: String, duration: Int?) {
        val id = inboundId ?: return
        val body = JSONObject().put("sim_slot", inboundSlot).put("event_id", id).put("status", status)
        if (duration != null) body.put("duration_seconds", duration)
        EventQueue.enqueue(ctx, "/webhook/call-status", body)
    }
}
