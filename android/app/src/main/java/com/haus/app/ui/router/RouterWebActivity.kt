package com.haus.app.ui.router

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import com.haus.app.R
import com.haus.app.databinding.ActivityRouterWebBinding
import com.haus.app.ui.common.HausNotice
import com.haus.app.ui.common.HausNoticeLevel
import com.haus.app.util.Constants

class RouterWebActivity : AppCompatActivity() {
    private lateinit var binding: ActivityRouterWebBinding
    private var routerUrl: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityRouterWebBinding.inflate(layoutInflater)
        setContentView(binding.root)
        routerUrl = intent.getStringExtra(EXTRA_URL).orEmpty()
        if (!isHausUrl(routerUrl)) {
            showError("Invalid Dashboard link")
            return
        }

        binding.btnClose.setOnClickListener { finish() }
        binding.btnBrowser.setOnClickListener {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(routerUrl)))
        }
        setupWebView()
        binding.webView.loadUrl(routerUrl)
    }

    private fun setupWebView() {
        CookieManager.getInstance().setAcceptCookie(true)
        binding.webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            builtInZoomControls = false
            displayZoomControls = false
        }
        // Deliberately no JavascriptInterface: the router UI is untrusted web
        // content and must not inherit the terminal's Android bridge.
        binding.webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val target = request.url.toString()
                return if (isHausUrl(target)) {
                    false
                } else {
                    startActivity(Intent(Intent.ACTION_VIEW, request.url))
                    true
                }
            }

            override fun onPageStarted(view: WebView?, url: String?, favicon: android.graphics.Bitmap?) {
                binding.progress.visibility = View.VISIBLE
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                binding.progress.visibility = View.GONE
            }

            override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: android.webkit.WebResourceError?) {
                if (request?.isForMainFrame == true) {
                    showError(getString(R.string.router_unavailable))
                }
            }
        }
    }

    private fun isHausUrl(value: String): Boolean {
        val expected = Uri.parse(Constants.BASE_URL)
        val actual = Uri.parse(value)
        return actual.scheme == expected.scheme && actual.host == expected.host &&
            actual.port.let { it == -1 || it == expected.port }
    }

    private fun showError(message: String) {
        binding.progress.visibility = View.GONE
        HausNotice.show(binding.root, message, HausNoticeLevel.ERROR, key = "router-error")
    }

    override fun onBackPressed() {
        if (binding.webView.canGoBack()) binding.webView.goBack() else super.onBackPressed()
    }

    companion object {
        const val EXTRA_URL = "router_url"
    }
}
