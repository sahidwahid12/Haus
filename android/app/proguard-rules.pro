# Keep JavascriptInterface methods used by the WebView terminal bridge
-keepattributes *Annotation*
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
