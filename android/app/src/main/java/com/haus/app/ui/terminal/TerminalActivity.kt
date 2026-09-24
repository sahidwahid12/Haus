package com.haus.app.ui.terminal

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.haus.app.R
import com.haus.app.data.AuthPrefs
import com.haus.app.databinding.ActivityTerminalBinding
import com.haus.app.net.TerminalWsClient
import com.haus.app.net.WsListener
import com.haus.app.net.WsStatus
import com.haus.app.net.ApiClient
import com.haus.app.ui.common.HausNotice
import com.haus.app.ui.common.HausNoticeLevel
import com.haus.app.ui.login.LoginActivity
import com.haus.app.ui.router.RouterWebActivity
import com.haus.app.util.ErrorMessages
import kotlinx.coroutines.launch
import org.json.JSONObject

class TerminalActivity : AppCompatActivity(), WsListener {

    private lateinit var binding: ActivityTerminalBinding
    private lateinit var prefs: AuthPrefs
    private lateinit var wsClient: TerminalWsClient

    private var ctrlActive = false
    private var altActive = false
    private var attempt = 0
    private var userLabel = ""

    /** Bridges xterm.js events back into the native WS client. */
    inner class WebViewBridge {
        @JavascriptInterface
        fun onInput(data: String) {
            var out = data
            val ctrl = ctrlActive
            val alt = altActive
            if (ctrl || alt) {
                out = applyModifiers(data, ctrl, alt)
                // The sticky modifier is consumed by the next keystroke; clear it
                // and refresh the key-bar on the UI thread.
                runOnUiThread {
                    if (ctrl) ctrlActive = false
                    if (alt) altActive = false
                    updateToggleVisuals()
                }
            }
            wsClient.sendInput(out)
        }

        @JavascriptInterface
        fun onResize(cols: Double, rows: Double) {
            wsClient.sendResize(rows.toInt(), cols.toInt())
        }
    }

    /**
     * Combine the on-screen CTRL/ALT modifiers with soft-keyboard input, since
     * xterm only forwards the raw character for keys typed on the device
     * keyboard. Ctrl maps a character to its control code; Alt prefixes ESC.
     */
    private fun applyModifiers(data: String, ctrl: Boolean, alt: Boolean): String {
        val sb = StringBuilder(data.length + 1)
        for (ch in data) {
            var c = ch
            if (ctrl) c = (c.code and 0x1F).toChar()
            if (alt) sb.append('\u001b')
            sb.append(c)
        }
        return sb.toString()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityTerminalBinding.inflate(layoutInflater)
        setContentView(binding.root)
        prefs = AuthPrefs(this)

        lifecycleScope.launch {
            val token = prefs.getToken()
            val username = prefs.getUsername()
            if (token.isNullOrEmpty()) {
                goLogin(); return@launch
            }
            userLabel = username ?: ""
            binding.tvUser.text = "haus@$userLabel"
            wsClient = TerminalWsClient(token, this@TerminalActivity)
            setupWebView()
            setupKeybar()
            wsClient.connect()
            setStatus(WsStatus.CONNECTING)
            binding.btnDisconnect.setOnClickListener { goLogin() }
            binding.btnRouter.setOnClickListener { openRouterDashboard() }

            // Barisan tombol (ESC/CTRL/ALT/panah) bisa disembunyikan/ditampilkan
            // seperti extra-keys di Termux. Pilihannya diingat antar sesi.
            val keyPrefs = getSharedPreferences("haus_terminal", MODE_PRIVATE)
            fun applyKeys(visible: Boolean) {
                binding.keybarScroller.visibility = if (visible) View.VISIBLE else View.GONE
                binding.btnKeys.text = getString(
                    if (visible) R.string.terminal_keys_hide else R.string.terminal_keys_show)
                keyPrefs.edit().putBoolean("keys_hidden", !visible).apply()
                // refit terminal after the layout changes height
                binding.webView.postDelayed(
                    { binding.webView.evaluateJavascript("fitTerminal()", null) }, 150)
            }
            applyKeys(!keyPrefs.getBoolean("keys_hidden", false))
            binding.btnKeys.setOnClickListener {
                applyKeys(binding.keybarScroller.visibility != View.VISIBLE)
            }

            binding.btnReconnect.setOnClickListener {
                attempt = 0
                wsClient.close()
                wsClient.connect()
                setStatus(WsStatus.CONNECTING)
                binding.btnReconnect.visibility = View.GONE
            }
        }
    }

    private fun openRouterDashboard() {
        if (!::prefs.isInitialized) return
        binding.btnRouter.isEnabled = false
        lifecycleScope.launch {
            try {
                val token = prefs.getToken()
                if (token.isNullOrEmpty()) {
                    HausNotice.show(binding.root, "Session expired. Please sign in again.",
                        HausNoticeLevel.ERROR, key = "router-auth")
                    goLogin()
                    return@launch
                }
                val response = ApiClient.api.createRouterSession("Bearer $token")
                startActivity(Intent(this@TerminalActivity, RouterWebActivity::class.java).apply {
                    putExtra(RouterWebActivity.EXTRA_URL, response.url)
                })
            } catch (e: Exception) {
                HausNotice.show(binding.root, ErrorMessages.message(e).take(180),
                    HausNoticeLevel.ERROR, key = "router-api-error")
            } finally {
                binding.btnRouter.isEnabled = true
            }
        }
    }

    private fun setupWebView() {
        // The WebView renders white by default; paint the Haus background up front so
        // there is never a white flash / blank screen while the local terminal page loads.
        binding.webView.setBackgroundColor(ContextCompat.getColor(this, R.color.haus_bg))
        binding.webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = true
            // Required so the local xterm.js / xterm.css assets and the Android JS
            // bridge load correctly on stricter WebViews (API 30+).
            allowFileAccessFromFileURLs = true
            allowUniversalAccessFromFileURLs = true
            builtInZoomControls = false
            displayZoomControls = false
        }
        binding.webView.addJavascriptInterface(WebViewBridge(), "Android")
        binding.webView.webChromeClient = android.webkit.WebChromeClient()
        binding.webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                view?.evaluateJavascript("fitTerminal()", null)
            }

            override fun onReceivedError(
                view: WebView?, errorCode: Int, description: String?, failingUrl: String?
            ) {
                super.onReceivedError(view, errorCode, description, failingUrl)
                HausNotice.show(
                    binding.root,
                    "Terminal gagal dimuat: ${description ?: "error $errorCode"}",
                    HausNoticeLevel.ERROR, key = "terminal-load-error"
                )
            }
        }
        binding.webView.loadUrl("file:///android_asset/terminal.html")
        // Fallback fit in case onPageFinished fires before the layout settles.
        binding.webView.postDelayed(
            { binding.webView.evaluateJavascript("fitTerminal()", null) }, 600
        )
    }

    private data class KeyDef(
        val label: String,
        val raw: String? = null,
        val send: String? = null,
        val toggle: String? = null
    )

    private fun setupKeybar() {
        val keys = listOf(
            KeyDef("ESC", raw = "\u001b"),
            KeyDef("TAB", raw = "\t"),
            KeyDef("CTRL", toggle = "ctrl"),
            KeyDef("ALT", toggle = "alt"),
            KeyDef("↑", raw = "\u001b[A"),
            KeyDef("↓", raw = "\u001b[B"),
            KeyDef("←", raw = "\u001b[D"),
            KeyDef("→", raw = "\u001b[C"),
            KeyDef("ENTER", raw = "\r"),
            KeyDef("-", send = "-"),
            KeyDef("/", send = "/"),
            KeyDef("|", send = "|"),
            KeyDef("~", send = "~"),
            KeyDef(".", send = "."),
            KeyDef(",", send = ","),
            KeyDef("*", send = "*"),
            KeyDef(" ", send = " ")
        )

        val pad = (6 * resources.displayMetrics.density).toInt()
        for (k in keys) {
            val btn = Button(this).apply {
                text = k.label
                textSize = 12f
                minWidth = (40 * resources.displayMetrics.density).toInt()
                setPadding(pad, pad / 2, pad, pad / 2)
                setBackgroundResource(R.drawable.key_bg)
                setTextColor(ContextCompat.getColor(this@TerminalActivity, R.color.haus_text_primary))
                setOnClickListener { onKeyPressed(k) }
            }
            if (k.toggle != null) btn.tag = k.toggle
            binding.keybar.addView(btn)
        }
    }

    private fun onKeyPressed(k: KeyDef) {
        when {
            k.toggle == "ctrl" -> {
                ctrlActive = !ctrlActive; updateToggleVisuals()
            }
            k.toggle == "alt" -> {
                altActive = !altActive; updateToggleVisuals()
            }
            k.raw != null -> wsClient.sendInput(k.raw)
            k.send != null -> {
                var out = k.send
                if (ctrlActive && out.length == 1 && out[0].isLetter()) {
                    out = ((out.uppercase()[0].code - 64).toChar()).toString()
                    ctrlActive = false; updateToggleVisuals()
                }
                if (altActive) {
                    out = "\u001b$out"
                    altActive = false; updateToggleVisuals()
                }
                wsClient.sendInput(out)
            }
        }
    }

    private fun updateToggleVisuals() {
        for (i in 0 until binding.keybar.childCount) {
            val v = binding.keybar.getChildAt(i)
            val t = v.tag
            val active = (t == "ctrl" && ctrlActive) || (t == "alt" && altActive)
            v.background = if (active) {
                ContextCompat.getDrawable(this, R.drawable.key_bg_active)
            } else {
                ContextCompat.getDrawable(this, R.drawable.key_bg)
            }
            (v as? Button)?.setTextColor(
                if (active) ContextCompat.getColor(this, R.color.haus_accent_on)
                else ContextCompat.getColor(this, R.color.haus_text_primary)
            )
        }
    }

    // ----- WS callbacks -----
    override fun onOutput(data: String) {
        val quoted = JSONObject.quote(data)
        runOnUiThread { binding.webView.evaluateJavascript("writeTerminal($quoted)", null) }
    }

    override fun onStatus(status: WsStatus) {
        runOnUiThread {
            when (status) {
                WsStatus.OPEN -> {
                    attempt = 0
                    binding.statusText.text = getString(R.string.terminal_status_connected)
                    binding.statusText.setTextColor(ContextCompat.getColor(this, R.color.haus_accent))
                    binding.btnReconnect.visibility = View.GONE
                }
                WsStatus.CONNECTING -> {
                    binding.statusText.text = getString(R.string.terminal_status_connecting)
                    binding.statusText.setTextColor(ContextCompat.getColor(this, R.color.haus_text_secondary))
                }
                WsStatus.CLOSED -> {
                    binding.statusText.text = getString(R.string.terminal_status_disconnected)
                    binding.statusText.setTextColor(ContextCompat.getColor(this, R.color.md_error))
                }
                WsStatus.ERROR -> {
                    attempt += 1
                    if (attempt <= 5) {
                        binding.statusText.text = getString(R.string.terminal_status_reconnecting, attempt)
                        binding.statusText.setTextColor(ContextCompat.getColor(this, R.color.haus_text_secondary))
                        binding.btnReconnect.visibility = View.VISIBLE
                        binding.webView.postDelayed({ tryAutoReconnect() }, 3000L * attempt)
                    } else {
                        binding.statusText.text = getString(R.string.terminal_status_error)
                        binding.statusText.setTextColor(ContextCompat.getColor(this, R.color.md_error))
                        binding.btnReconnect.visibility = View.VISIBLE
                        HausNotice.show(binding.root, "Connection failed. Tap Reconnect to try again.",
                            HausNoticeLevel.ERROR, key = "terminal-final-connection-error")
                    }
                }
                WsStatus.UNAUTHORIZED -> {
                    HausNotice.show(binding.root, "Session expired. Please sign in again.",
                        HausNoticeLevel.ERROR, key = "terminal-session-expired")
                    binding.webView.postDelayed({ goLogin() }, 900)
                }
            }
        }
    }

    private fun tryAutoReconnect() {
        if (binding.statusText.text?.toString().orEmpty().startsWith("↻").not()) return
        wsClient.close()
        wsClient.connect()
        setStatus(WsStatus.CONNECTING)
    }

    private fun setStatus(s: WsStatus) = onStatus(s)

    private fun goLogin() {
        lifecycleScope.launch {
            prefs.clear()
            startActivity(Intent(this@TerminalActivity, LoginActivity::class.java))
            finish()
        }
    }

    override fun onDestroy() {
        if (::wsClient.isInitialized) wsClient.close()
        super.onDestroy()
    }
}