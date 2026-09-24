package com.haus.app

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.haus.app.data.AuthPrefs
import com.haus.app.ui.login.LoginActivity
import com.haus.app.ui.terminal.TerminalActivity
import kotlinx.coroutines.launch

/**
 * Splash / router. Reads the stored token off the main thread and
 * forwards the user to either the terminal or the login screen.
 */
class MainActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = AuthPrefs(this)
        lifecycleScope.launch {
            val token = prefs.getToken()
            val target = if (token.isNullOrEmpty()) LoginActivity::class.java
                         else TerminalActivity::class.java
            startActivity(Intent(this@MainActivity, target))
            finish()
        }
    }
}