package com.haus.app.util

object Constants {
    /**
     * Base URL of the published Haus backend (WorkBuddy free publish link).
     * WebSocket URL is derived automatically (https -> wss).
     */
    const val BASE_URL: String = "https://a0b25aa3ce76bd678.sg2.agentos-app.run"

    /** WebSocket URL derived from BASE_URL (https -> wss). */
    val WS_URL: String
        get() = BASE_URL
            .removeSuffix("/")
            .replace("https://", "wss://")
            .replace("http://", "ws://")
}