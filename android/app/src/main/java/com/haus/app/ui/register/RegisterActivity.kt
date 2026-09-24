package com.haus.app.ui.register

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.haus.app.R
import com.haus.app.data.AuthPrefs
import com.haus.app.data.model.RegisterRequest
import com.haus.app.databinding.ActivityRegisterBinding
import com.haus.app.net.ApiClient
import com.haus.app.ui.login.LoginActivity
import com.haus.app.ui.terminal.TerminalActivity
import com.haus.app.ui.common.HausNotice
import com.haus.app.ui.common.HausNoticeLevel
import com.haus.app.util.ErrorMessages
import kotlinx.coroutines.launch

class RegisterActivity : AppCompatActivity() {

    private lateinit var binding: ActivityRegisterBinding
    private lateinit var prefs: AuthPrefs
    private val usernameRe = Regex("^[a-z0-9_]{3,20}$")
    private val emailRe = Regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityRegisterBinding.inflate(layoutInflater)
        setContentView(binding.root)
        prefs = AuthPrefs(this)

        binding.btnRegister.setOnClickListener { doRegister() }
        binding.btnLogin.setOnClickListener {
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
        }
    }

    private fun setBusy(busy: Boolean) {
        binding.btnRegister.isEnabled = !busy
        binding.btnLogin.isEnabled = !busy
        binding.progress.visibility = if (busy) android.view.View.VISIBLE else android.view.View.GONE
    }

    private fun doRegister() {
        val username = binding.etUsername.text.toString().trim().lowercase()
        val email = binding.etEmail.text.toString().trim().lowercase()
        val password = binding.etPassword.text.toString()
        val confirm = binding.etConfirm.text.toString()

        if (username.isEmpty() || email.isEmpty() || password.isEmpty() || confirm.isEmpty()) {
            HausNotice.show(binding.root, getString(R.string.register_required), HausNoticeLevel.INFO,
                key = "register-validation", duration = com.google.android.material.snackbar.Snackbar.LENGTH_SHORT); return
        }
        if (!usernameRe.matches(username)) {
            HausNotice.show(binding.root, getString(R.string.register_username_invalid), HausNoticeLevel.ERROR,
                key = "register-validation"); return
        }
        if (!emailRe.matches(email)) {
            HausNotice.show(binding.root, getString(R.string.register_email_invalid), HausNoticeLevel.ERROR,
                key = "register-validation"); return
        }
        if (password.length < 6) {
            HausNotice.show(binding.root, getString(R.string.register_password_short), HausNoticeLevel.ERROR,
                key = "register-validation"); return
        }
        if (password != confirm) {
            HausNotice.show(binding.root, getString(R.string.register_password_mismatch), HausNoticeLevel.ERROR,
                key = "register-validation"); return
        }

        setBusy(true)
        lifecycleScope.launch {
            try {
                val resp = ApiClient.api.register(RegisterRequest(username, password, email))
                prefs.save(resp.token, resp.username)
                HausNotice.show(binding.root,
                    getString(R.string.register_subtitle) + " · " + resp.container,
                    HausNoticeLevel.SUCCESS, key = "register-success")
                startActivity(Intent(this@RegisterActivity, TerminalActivity::class.java))
                finish()
            } catch (e: Exception) {
                setBusy(false)
                HausNotice.show(binding.root, ErrorMessages.message(e).take(180),
                    HausNoticeLevel.ERROR, key = "register-api-error")
            }
        }
    }
}