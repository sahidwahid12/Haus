package com.haus.app.data.model

data class RegisterRequest(
    val username: String,
    val password: String,
    val email: String
)

data class LoginRequest(
    val username: String,
    val password: String
)

data class ForgotRequest(val username: String)

data class ResetRequest(
    val username: String,
    val code: String,
    val new_password: String
)

data class AuthResponse(
    val token: String,
    val username: String,
    val container: String
)

data class MeResponse(
    val username: String,
    val container: String
)

data class MessageResponse(
    val ok: Boolean? = null,
    val message: String? = null
)

data class RouterSessionResponse(
    val url: String,
    val expires_at: Long? = null
)