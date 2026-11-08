package com.example.dialergateway

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.telephony.SubscriptionManager

/** Works out which physical SIM slot (0 or 1) an event belongs to. The server uses the slot to find the tenant. */
object Slots {
    fun fromIntent(ctx: Context, intent: Intent): Int {
        for (k in listOf("android.telephony.extra.SLOT_INDEX", "slot", "simSlot", "phone")) {
            val v = intent.getIntExtra(k, -1)
            if (v in 0..1) return v
        }
        val sub = intent.getIntExtra("subscription", intent.getIntExtra("android.telephony.extra.SUBSCRIPTION_INDEX", -1))
        if (sub >= 0) slotForSubscription(ctx, sub)?.let { return it }
        return Config.defaultSlot(ctx) // some phones do not say; the setting is the fallback
    }

    @SuppressLint("MissingPermission")
    fun slotForSubscription(ctx: Context, subId: Int): Int? = try {
        ctx.getSystemService(SubscriptionManager::class.java).getActiveSubscriptionInfo(subId)?.simSlotIndex
    } catch (e: Exception) { null }

    @SuppressLint("MissingPermission")
    fun subscriptionForSlot(ctx: Context, slot: Int): Int? = try {
        ctx.getSystemService(SubscriptionManager::class.java).activeSubscriptionInfoList
            ?.firstOrNull { it.simSlotIndex == slot }?.subscriptionId
    } catch (e: Exception) { null }
}
