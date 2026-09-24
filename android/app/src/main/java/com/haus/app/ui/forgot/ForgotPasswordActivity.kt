package com.haus.app.ui.forgot

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.haus.app.R
import com.haus.app.data.model.ForgotRequest
import com.haus.app.data.model.ResetRequest
import com.haus.app.databinding.ActivityForgotBinding
import com.haus.app.net.ApiClient
import com.haus.app.ui.login.LoginActivity
import com.haus.app.ui.common.HausNotice
import com.haus.app.ui.common.HausNoticeLevel
import com.haus.app.util.ErrorMessages
import kotlinx.coroutines.launch

/**
 * Two-step password recovery:
 *   step 1: enter username, request a 6-digit code by email
 *   step 2: enter code + new password, submit reset
 * The server always returns the same generic success for step 1
 * (anti user-enumeration); the UI shows that message either way.
 */
class ForgotPasswordActivity : AppCompatActivity() {

    private lateinit var binding: ActivityForgotBinding
    private var pendingUsername: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityForgotBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.btnSend.setOnClickListener { sendCode() }
        binding.btnReset.setOnClickListener { submitReset() }
        binding.btnBack.setOnClickListener {
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
        }
    }

    private fun setBusy(step: Int, busy: Boolean) {
        if (step == 1) {
            binding.btnSend.isEnabled = !busy
            binding.progress1.visibility = if (busy) android.view.View.VISIBLE else android.view.View.GONE
        } else {
            binding.btnReset.isEnabled = !busy
            binding.progress2.visibility = if (busy) android.view.View.VISIBLE else android.view.View.GONE
        }
    }

    private fun sendCode() {
        val username = binding.etUsername.text.toString().trim().lowercase()
        if (username.isEmpty()) {
            HausNotice.show(binding.root, getString(R.string.forgot_username_required), HausNoticeLevel.INFO,
                key = "forgot-validation", duration = com.google.android.material.snackbar.Snackbar.LENGTH_SHORT); return
        }
        pendingUsername = username
        setBusy(1, true)
        lifecycleScope.launch {
            try {
                ApiClient.api.forgotPassword(ForgotRequest(username))
                binding.step1.visibility = android.view.View.GONE
                binding.step2.visibility = android.view.View.VISIBLE
                binding.tvSentFor.text = getString(R.string.forgot_sent_generic)
                HausNotice.show(binding.root, getString(R.string.forgot_sent_generic),
                    HausNoticeLevel.SUCCESS, key = "forgot-code-sent")
            } catch (e: Exception) {
                setBusy(1, false)
                HausNotice.show(binding.root, ErrorMessages.message(e).take(180),
                    HausNoticeLevel.ERROR, key = "forgot-api-error")
            }
        }
    }

    private fun submitReset() {
        val code = binding.etCode.text.toString().trim()
        val newPw = binding.etNew.text.toString()
        if (code.length != 6) {
            HausNotice.show(binding.root, getString(R.string.forgot_code_short), HausNoticeLevel.ERROR,
                key = "forgot-validation", duration = com.google.android.material.snackbar.Snackbar.LENGTH_SHORT); return
        }
        if (newPw.length < 6) {
            HausNotice.show(binding.root, getString(R.string.register_password_short), HausNoticeLevel.ERROR,
                key = "forgot-validation", duration = com.google.android.material.snackbar.Snackbar.LENGTH_SHORT); return
        }
        setBusy(2, true)
        lifecycleScope.launch {
            try {
                ApiClient.api.resetPassword(ResetRequest(pendingUsername, code, newPw))
                startActivity(Intent(this@ForgotPasswordActivity, LoginActivity::class.java).apply {
                    putExtra("reset_done", true)
                })
                finish()
            } catch (e: Exception) {
                setBusy(2, false)
                HausNotice.show(binding.root, ErrorMessages.message(e).take(180),
                    HausNoticeLevel.ERROR, key = "forgot-api-error")
            }
        }
    }
}