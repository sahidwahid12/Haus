package com.haus.app.ui.login

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.haus.app.R
import com.haus.app.data.AuthPrefs
import com.haus.app.data.model.LoginRequest
import com.haus.app.databinding.ActivityLoginBinding
import com.haus.app.net.ApiClient
import com.haus.app.ui.forgot.ForgotPasswordActivity
import com.haus.app.ui.register.RegisterActivity
import com.haus.app.ui.terminal.TerminalActivity
import com.haus.app.ui.common.HausNotice
import com.haus.app.ui.common.HausNoticeLevel
import com.haus.app.util.ErrorMessages
import kotlinx.coroutines.launch

class LoginActivity : AppCompatActivity() {

    private lateinit var binding: ActivityLoginBinding
    private lateinit var prefs: AuthPrefs

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityLoginBinding.inflate(layoutInflater)
        setContentView(binding.root)
        prefs = AuthPrefs(this)

        binding.btnLogin.setOnClickListener { doLogin() }
        binding.btnRegister.setOnClickListener {
            startActivity(Intent(this, RegisterActivity::class.java))
        }
        binding.tvForgot.setOnClickListener {
            startActivity(Intent(this, ForgotPasswordActivity::class.java))
        }
        if (intent.getBooleanExtra("reset_done", false)) {
            HausNotice.show(binding.root, getString(R.string.forgot_reset_done),
                HausNoticeLevel.SUCCESS, key = "reset-success")
            intent.removeExtra("reset_done")
        }
    }

    private fun setBusy(busy: Boolean) {
        binding.btnLogin.isEnabled = !busy
        binding.btnRegister.isEnabled = !busy
        binding.progress.visibility = if (busy) android.view.View.VISIBLE else android.view.View.GONE
    }

    private fun doLogin() {
        val username = binding.etUsername.text.toString().trim()
        val password = binding.etPassword.text.toString()
        if (username.isEmpty() || password.isEmpty()) {
            HausNotice.show(binding.root, getString(R.string.login_required_fields),
                HausNoticeLevel.INFO, key = "login-validation", duration = com.google.android.material.snackbar.Snackbar.LENGTH_SHORT)
            return
        }
        setBusy(true)
        lifecycleScope.launch {
            try {
                val resp = ApiClient.api.login(LoginRequest(username, password))
                prefs.save(resp.token, resp.username)
                startActivity(Intent(this@LoginActivity, TerminalActivity::class.java))
                finish()
            } catch (e: Exception) {
                setBusy(false)
                HausNotice.show(binding.root, ErrorMessages.message(e).take(180),
                    HausNoticeLevel.ERROR, key = "login-api-error")
            }
        }
    }
}