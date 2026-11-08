package com.example.dialergateway

import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

object Net {
    val http: OkHttpClient = OkHttpClient.Builder()
        .callTimeout(15, TimeUnit.SECONDS)
        .build()

    // Keeps the socket alive through NAT and detects dead connections.
    val ws: OkHttpClient = OkHttpClient.Builder()
        .pingInterval(25, TimeUnit.SECONDS)
        .build()
}
