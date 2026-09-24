package com.haus.app.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.first

private val Context.dataStore by preferencesDataStore(name = "haus_auth")

class AuthPrefs(private val context: Context) {

    private val token = stringPreferencesKey("token")
    private val username = stringPreferencesKey("username")

    suspend fun save(token: String, username: String) {
        context.dataStore.edit {
            it[this.token] = token
            it[this.username] = username
        }
    }

    suspend fun clear() {
        context.dataStore.edit { it.clear() }
    }

    suspend fun getToken(): String? = context.dataStore.data.first()[this.token]
    suspend fun getUsername(): String? = context.dataStore.data.first()[this.username]
}