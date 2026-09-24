package com.haus.app.util

import com.google.gson.Gson
import retrofit2.HttpException
import java.io.InterruptedIOException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

/**
 * Best-effort extraction of the `detail` field from a Retrofit HttpException
 * so we can show the server's human-readable error instead of the raw
 * exception text.
 */
object ErrorMessages {
    private data class FastApiError(val detail: String?)

    fun message(t: Throwable): String {
        // Timeouts / connectivity get a helpful message rather than "timeout".
        if (t is SocketTimeoutException || t is InterruptedIOException) {
            return "Server is slow to respond (it may be waking up). Please try again."
        }
        if (t is UnknownHostException) {
            return "Cannot reach the server. Check your connection."
        }
        if (t is HttpException) {
            try {
                val body = t.response()?.errorBody()?.string()
                if (!body.isNullOrBlank()) {
                    val parsed = Gson().fromJson(body, FastApiError::class.java)
                    val d = parsed?.detail?.trim()
                    if (!d.isNullOrEmpty()) return d
                }
            } catch (_: Exception) {
            }
            return when (t.code()) {
                401 -> "Invalid username or password"
                409 -> "Username already taken"
                429 -> "Account limit reached for this network"
                500, 502, 503, 504 -> "Server error, please try again in a moment"
                else -> "HTTP ${t.code()}"
            }
        }
        return t.message ?: "Network error"
    }
}