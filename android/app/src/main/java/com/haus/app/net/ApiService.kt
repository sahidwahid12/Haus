package com.haus.app.net

import com.haus.app.data.model.AuthResponse
import com.haus.app.data.model.ForgotRequest
import com.haus.app.data.model.LoginRequest
import com.haus.app.data.model.MeResponse
import com.haus.app.data.model.MessageResponse
import com.haus.app.data.model.RegisterRequest
import com.haus.app.data.model.ResetRequest
import com.haus.app.data.model.RouterSessionResponse
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST

interface ApiService {
    @POST("api/register")
    suspend fun register(@Body body: RegisterRequest): AuthResponse

    @POST("api/login")
    suspend fun login(@Body body: LoginRequest): AuthResponse

    @GET("api/me")
    suspend fun me(@Header("Authorization") auth: String): MeResponse

    @POST("api/forgot-password")
    suspend fun forgotPassword(@Body body: ForgotRequest): MessageResponse

    @POST("api/reset-password")
    suspend fun resetPassword(@Body body: ResetRequest): MessageResponse

    @POST("api/router/session")
    suspend fun createRouterSession(@Header("Authorization") auth: String): RouterSessionResponse
}