package com.haus.app.ui.common

import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.View
import android.widget.TextView
import androidx.core.content.ContextCompat
import com.google.android.material.R as MaterialR
import com.google.android.material.snackbar.Snackbar
import com.haus.app.R
import java.util.WeakHashMap

/**
 * Haus-styled in-app notice. Replaces plain Android Toasts with a consistent,
 * accessible Material notice that stays attached to the current screen.
 */
enum class HausNoticeLevel { INFO, SUCCESS, ERROR }

object HausNotice {
    private val active = WeakHashMap<View, Snackbar>()
    private val activeKeys = WeakHashMap<View, String>()

    fun show(
        anchor: View,
        message: CharSequence,
        level: HausNoticeLevel = HausNoticeLevel.INFO,
        key: String = message.toString(),
        duration: Int = Snackbar.LENGTH_LONG,
        actionText: CharSequence? = null,
        action: (() -> Unit)? = null
    ) {
        if (message.isBlank()) return
        if (activeKeys[anchor] == key && active[anchor]?.isShown == true) return

        active[anchor]?.dismiss()
        val snackbar = Snackbar.make(anchor, message, duration)
        val view = snackbar.view
        val context = anchor.context
        val fill = when (level) {
            HausNoticeLevel.ERROR -> ContextCompat.getColor(context, R.color.haus_notice_error_bg)
            HausNoticeLevel.SUCCESS -> ContextCompat.getColor(context, R.color.haus_notice_success_bg)
            HausNoticeLevel.INFO -> ContextCompat.getColor(context, R.color.haus_surface_high)
        }
        val accent = when (level) {
            HausNoticeLevel.ERROR -> ContextCompat.getColor(context, R.color.md_error)
            else -> ContextCompat.getColor(context, R.color.haus_accent)
        }
        view.background = GradientDrawable().apply {
            setColor(fill)
            cornerRadius = 14f * context.resources.displayMetrics.density
            setStroke((1 * context.resources.displayMetrics.density).toInt(), accent)
        }
        view.elevation = 8f * context.resources.displayMetrics.density
        view.setPadding(
            (16 * context.resources.displayMetrics.density).toInt(),
            (10 * context.resources.displayMetrics.density).toInt(),
            (12 * context.resources.displayMetrics.density).toInt(),
            (10 * context.resources.displayMetrics.density).toInt()
        )
        view.accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        view.findViewById<TextView>(MaterialR.id.snackbar_text)?.apply {
            setTextColor(ContextCompat.getColor(context, R.color.haus_text_primary))
            maxLines = 4
            textSize = 14f
        }
        if (actionText != null && action != null) {
            snackbar.setActionTextColor(accent)
            snackbar.setAction(actionText) { action() }
        }
        active[anchor] = snackbar
        activeKeys[anchor] = key
        snackbar.addCallback(object : Snackbar.Callback() {
            override fun onDismissed(transientBottomBar: Snackbar?, event: Int) {
                if (active[anchor] === snackbar) {
                    active.remove(anchor)
                    activeKeys.remove(anchor)
                }
            }
        })
        snackbar.show()
    }

    fun clear(anchor: View) {
        active.remove(anchor)?.dismiss()
        activeKeys.remove(anchor)
    }
}
