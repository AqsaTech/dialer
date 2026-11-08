package com.example.dialergateway

import android.annotation.SuppressLint
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.telecom.PhoneAccountHandle
import android.telecom.TelecomManager
import android.telephony.SmsManager
import android.telephony.SubscriptionManager
import android.telephony.TelephonyManager
import android.util.Log
import org.json.JSONObject

/** Runs commands that the server sends over the WebSocket. */
object CommandExecutor {
    private const val TAG = "CommandExecutor"

    fun handle(ctx: Context, cmd: JSONObject) {
        val logId = cmd.optLong("log_id", -1)
        val slot = cmd.optInt("sim_slot", 0)
        try {
            when (cmd.optString("cmd")) {
                "dial" -> dial(ctx, logId, cmd.getString("to"), slot)
                "sms" -> sms(ctx, logId, cmd.getString("to"), cmd.getString("body"), slot)
                "answer" -> answer(ctx)
                "reject" -> reject(ctx, logId)
                "hangup" -> endCall(ctx)
                else -> Log.w(TAG, "unknown command: $cmd")
            }
        } catch (e: Throwable) {
            Log.e(TAG, "command failed", e)
            if (logId >= 0 && cmd.optString("cmd") in listOf("dial", "sms")) GatewayService.sendResult(logId, "failed")
        }
    }

    @SuppressLint("MissingPermission")
    private fun dial(ctx: Context, logId: Long, to: String, slot: Int) {
        val tm = ctx.getSystemService(TelecomManager::class.java)
        val extras = Bundle()
        accountForSlot(ctx, tm, slot)?.let { extras.putParcelable(TelecomManager.EXTRA_PHONE_ACCOUNT_HANDLE, it) }
        CallTracker.outboundLogId = logId
        tm.placeCall(Uri.fromParts("tel", to, null), extras)
    }

    /** Finds the calling account of a SIM slot. Returns null if unsure, and Android then uses its default SIM. */
    @SuppressLint("MissingPermission")
    private fun accountForSlot(ctx: Context, tm: TelecomManager, slot: Int): PhoneAccountHandle? = try {
        val info = ctx.getSystemService(SubscriptionManager::class.java)
            .activeSubscriptionInfoList?.firstOrNull { it.simSlotIndex == slot }
        val telephony = ctx.getSystemService(TelephonyManager::class.java)
        if (info == null) null
        else tm.callCapablePhoneAccounts.firstOrNull { handle ->
            if (Build.VERSION.SDK_INT >= 30) {
                telephony.createForPhoneAccountHandle(handle)?.subscriptionId == info.subscriptionId
            } else {
                val icc = info.iccId
                !icc.isNullOrEmpty() && handle.id.contains(icc)
            }
        }
    } catch (e: Exception) { null }

    @SuppressLint("MissingPermission")
    @Suppress("DEPRECATION")
    private fun sms(ctx: Context, logId: Long, to: String, body: String, slot: Int) {
        val subId = Slots.subscriptionForSlot(ctx, slot)
        val manager = if (subId != null) SmsManager.getSmsManagerForSubscriptionId(subId) else SmsManager.getDefault()
        val parts = manager.divideMessage(body)
        val sentIntent = PendingIntent.getBroadcast(
            ctx, logId.toInt(),
            Intent(ctx, SmsSentReceiver::class.java).putExtra("log_id", logId),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        manager.sendMultipartTextMessage(to, null, parts, ArrayList(parts.map { sentIntent }), null)
    }

    @SuppressLint("MissingPermission")
    private fun answer(ctx: Context) {
        ctx.getSystemService(TelecomManager::class.java).acceptRingingCall()
    }

    @SuppressLint("MissingPermission")
    private fun reject(ctx: Context, logId: Long) {
        CallTracker.markRejected()
        ctx.getSystemService(TelecomManager::class.java).endCall()
        if (logId >= 0) GatewayService.sendResult(logId, "rejected")
    }

    @SuppressLint("MissingPermission")
    private fun endCall(ctx: Context) {
        ctx.getSystemService(TelecomManager::class.java).endCall()
    }
}
