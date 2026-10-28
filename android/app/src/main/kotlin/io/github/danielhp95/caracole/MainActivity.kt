package io.github.danielhp95.caracole

import android.animation.ValueAnimator
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View
import android.view.ViewGroup
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.ImageButton
import android.widget.PopupMenu
import android.widget.TextView
import android.window.OnBackInvokedCallback
import android.window.OnBackInvokedDispatcher
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.webkit.WebViewAssetLoader
import io.github.danielhp95.caracole.mirror.Links
import io.github.danielhp95.caracole.mirror.Route
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * The library screen: a WebView showing the mirror's pages, caracole's own, unchanged, at
 * `https://appassets.androidplatform.net/<path>` (the root, as on caracole serve: [Links]), with a small bar
 * (the page's title; Sync now, Library, Settings) and the sync's line under it. A pinch sizes the pages' text
 * ([pinchToSize]), and shows the size it is at over the page while it lasts ([sizeLabel]).
 */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var status: TextView
    private lateinit var title: TextView
    private lateinit var empty: View
    private lateinit var links: Links
    private lateinit var loader: WebViewAssetLoader
    private lateinit var settings: Settings
    private lateinit var pinch: TextPinch
    private lateinit var label: SizeLabel
    /** The WebView's own text zoom, as Android's font size has it: what [TextZoom.DEFAULT] stands for. */
    private var ownTextZoom = TextZoom.DEFAULT
    private var scope: CoroutineScope = MainScope()
    private var hiding: Job? = null
    private var shown = false

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowCompat.getInsetsController(window, window.decorView).isAppearanceLightStatusBars = false
        setContentView(R.layout.activity_main)
        web = findViewById(R.id.web)
        status = findViewById(R.id.status)
        title = findViewById(R.id.title)
        empty = findViewById(R.id.empty)
        settings = Settings(this)
        fitInsets()

        val mirror = Caracole.mirror(this)
        links = Links(mirror)
        loader = WebViewAssetLoader.Builder()
            .setDomain(Links.HOST)
            .addPathHandler(Links.PREFIX, MirrorPathHandler(mirror))
            .build()

        ownTextZoom = web.settings.textZoom
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            javaScriptCanOpenWindowsAutomatically = false
            setSupportMultipleWindows(false)
            setGeolocationEnabled(false)
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            safeBrowsingEnabled = false
            // A pinch sizes the text alone, and the page reflows to the screen's width: it is never zoomed as a
            // picture, nor wider than the screen.
            setSupportZoom(false)
            builtInZoomControls = false
            displayZoomControls = false
            textZoom = TextZoom.applied(ownTextZoom, settings.textZoom)
        }
        label = sizeLabel()
        pinch = TextPinch(settings.textZoom, frame = { web.postOnAnimation(it) }, apply = { size ->
            sizeText(size)
            label.sized(size)
        })
        pinchToSize()
        web.webViewClient = Client()
        web.webChromeClient = object : WebChromeClient() {
            override fun onReceivedTitle(view: WebView, text: String?) {
                title.text = text?.takeIf { it.isNotBlank() } ?: getString(R.string.app_name)
            }
        }
        // A link with `download` (a Guitar Pro file on the library page) comes here, not as a navigation.
        web.setDownloadListener { url, _, _, _, _ -> follow(url) }

        findViewById<ImageButton>(R.id.more).setOnClickListener { menu(it) }
        findViewById<View>(R.id.open_settings).setOnClickListener { openSettings() }

        if (savedInstanceState != null && web.restoreState(savedInstanceState) != null) {
            shown = true
        } else if (!showLibrary()) {
            openSettings() // a first start, with no copy yet
        }
        backCallback()
    }

    override fun onResume() {
        super.onResume()
        pinch.set(settings.textZoom) // as Settings' Reset may have left it
        if (!shown) showLibrary()
    }

    override fun onStart() {
        super.onStart()
        scope = MainScope()
        scope.launch { Caracole.status.collect { show(it) } }
    }

    override fun onStop() {
        scope.cancel()
        super.onStop()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        if (shown) web.saveState(outState)
    }

    override fun onDestroy() {
        web.destroy()
        super.onDestroy()
    }

    /** Opens the library page if the mirror has one; false when it has none yet. */
    private fun showLibrary(): Boolean {
        val start = Caracole.mirror(this).manifest()?.start
        empty.visibility = if (start == null) View.VISIBLE else View.GONE
        if (start == null) return false
        web.loadUrl(Links.address(start))
        shown = true
        return true
    }

    private fun openSettings() = startActivity(Intent(this, SettingsActivity::class.java))

    private fun menu(anchor: View) {
        val popup = PopupMenu(this, anchor)
        popup.menuInflater.inflate(R.menu.main, popup.menu)
        popup.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.sync_now -> Syncs.now(this)
                R.id.library -> showLibrary()
                R.id.settings -> openSettings()
            }
            true
        }
        popup.show()
    }

    /** The sync's line: while it runs, how far; at its end, "Up to date" or the error, for a few seconds. */
    private fun show(state: SyncState) {
        hiding?.cancel()
        when (state) {
            SyncState.Idle -> status.visibility = View.GONE
            is SyncState.Running -> {
                val p = state.progress
                status.text = if (p == null) getString(R.string.syncing_asking) else getString(R.string.syncing, p.done, p.total)
                status.visibility = View.VISIBLE
            }
            is SyncState.Ended -> {
                val outcome = state.outcome
                val age = System.currentTimeMillis() - outcome.at
                if (age > SHOW_ENDED_MS) {
                    status.visibility = View.GONE
                    return
                }
                status.text = when {
                    !outcome.ok -> outcome.text
                    outcome.text == "nothing changed" -> getString(R.string.up_to_date)
                    else -> getString(R.string.up_to_date_changes, outcome.text)
                }
                status.visibility = View.VISIBLE
                if (outcome.ok && !shown) showLibrary()
                hiding = scope.launch {
                    delay(SHOW_ENDED_MS - age)
                    status.visibility = View.GONE
                }
            }
        }
    }

    /** Where a link the page follows goes ([Links.route]); true when the WebView doesn't load it. */
    private fun follow(url: String): Boolean = when (val route = links.route(url)) {
        Route.Page -> false
        is Route.File -> { Handoff.openFile(this, route.served); true }
        is Route.Browser -> { Handoff.openBrowser(this, route.url); true }
        Route.ServerOnly -> { Handoff.toast(this, getString(R.string.server_only)); true }
        Route.Missing -> { Handoff.toast(this, getString(R.string.missing)); true }
        Route.Ignored -> true
    }

    private inner class Client : WebViewClient() {
        override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse =
            // The copy is all the WebView shows: no request of a page leaves the phone.
            loader.shouldInterceptRequest(request.url) ?: MirrorPathHandler.notFound()

        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean =
            if (request.isForMainFrame) follow(request.url.toString()) else false

        override fun doUpdateVisitedHistory(view: WebView, url: String?, isReload: Boolean) = backCallback()

        override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
            // The page's renderer died (killed for memory, say): start the screen again rather than crash.
            (view.parent as? ViewGroup)?.removeView(view)
            view.destroy()
            recreate()
            return true
        }
    }

    // Back goes back in the WebView, then leaves. From Android 13 a callback, registered while there is
    // somewhere to go back to (Android 16 sends a targetSdk 36 app no onBackPressed).
    private var backRegistered = false
    private val onBack: Any? = if (Build.VERSION.SDK_INT >= 33) OnBackInvokedCallback { web.goBack() } else null

    private fun backCallback() {
        if (Build.VERSION.SDK_INT < 33) return
        val want = web.canGoBack()
        if (want == backRegistered) return
        val callback = onBack as OnBackInvokedCallback
        if (want) onBackInvokedDispatcher.registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT, callback)
        else onBackInvokedDispatcher.unregisterOnBackInvokedCallback(callback)
        backRegistered = want
    }

    // Android 8 to 12 alone: from 13 the manifest's enableOnBackInvokedCallback sends Back to backCallback's.
    @SuppressLint("GestureBackNavigation")
    @Deprecated("Android 13 and later use backCallback")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else @Suppress("DEPRECATION") super.onBackPressed()
    }

    /**
     * Two fingers apart make the text larger, together smaller ([TextPinch]), kept in [Settings]. A touch of one
     * finger goes on to the page as it was: a scroll, a tap, a swipe, a double tap. A second finger makes the touch
     * the pinch's: the page lets go of it (a touch cancelled: no scroll, swipe or tap comes of it) and sees none of
     * the rest. The WebView never sees two fingers: before a pinch is told apart from a slip, it would zoom the page
     * as a picture with them, its own zoom off or not (WebView 133 did, by about a fifth each pinch).
     */
    @SuppressLint("ClickableViewAccessibility") // no click here: a tap reaches the page untouched
    private fun pinchToSize() {
        val detector = ScaleGestureDetector(this, object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
            override fun onScaleBegin(detector: ScaleGestureDetector): Boolean {
                pinch.begin()
                label.began(pinch.zoom)
                return true
            }

            override fun onScale(detector: ScaleGestureDetector): Boolean {
                pinch.scale(detector.scaleFactor)
                return true
            }

            override fun onScaleEnd(detector: ScaleGestureDetector) {
                val size = pinch.end()
                settings.textZoom = size
                label.ended(size)
            }
        })
        detector.isQuickScaleEnabled = false // a double tap held and dragged stays the page's
        detector.isStylusScaleEnabled = false
        var pinching = false
        web.setOnTouchListener { view, event ->
            detector.onTouchEvent(event)
            if (event.actionMasked == MotionEvent.ACTION_POINTER_DOWN && !pinching) {
                pinching = true
                // The touch the page knows of, its first finger's, cancelled.
                val cancel = MotionEvent.obtain(event.downTime, event.eventTime, MotionEvent.ACTION_CANCEL,
                    event.getX(0), event.getY(0), 0)
                cancel.source = event.source
                view.onTouchEvent(cancel)
                cancel.recycle()
            }
            val pinched = pinching
            if (event.actionMasked == MotionEvent.ACTION_UP || event.actionMasked == MotionEvent.ACTION_CANCEL) pinching = false
            pinched
        }
    }

    /**
     * The pill near the top of the page that shows the size a pinch is at ([SizeLabel]): "135%", in the bar's colours,
     * not a Toast, which would queue behind the last one. A screen reader hears the size once, at the pinch's end
     * (`announceForAccessibility`: a live region would read every step).
     */
    private fun sizeLabel(): SizeLabel {
        val pill = findViewById<TextView>(R.id.size_label)
        return SizeLabel(
            show = { size ->
                pill.animate().cancel() // a fade under way stops, and its end, which hides the pill, never comes
                pill.alpha = 1f
                pill.text = getString(R.string.text_size, size)
                pill.visibility = View.VISIBLE
            },
            hide = { fade ->
                if (fade) pill.animate().alpha(0f).setDuration(FADE_MS).withEndAction { pill.visibility = View.GONE }
                else pill.visibility = View.GONE
            },
            announce = { size ->
                @Suppress("DEPRECATION") // Android 16's advice is a live region, which would speak at each step
                web.announceForAccessibility(getString(R.string.text_size_said, size))
            },
            later = { delay, block ->
                val run = Runnable(block)
                pill.postDelayed(run, delay)
                ({ pill.removeCallbacks(run) })
            },
            // Animations off (the accessibility setting Remove animations): hidden at once, never faded.
            calm = { !ValueAnimator.areAnimatorsEnabled() },
        )
    }

    /**
     * The pages' text at [percent] of their own, as Android's font size draws them. A sheet viewer measures its chords to keep each over its syllable,
     * and measures them again when the window changes size (viewer.js's `resize` listener): told of one, it lays the
     * sheet out again in the new size. Other pages reflow by themselves, and a resize changes nothing on them.
     */
    private fun sizeText(percent: Int) {
        web.settings.textZoom = TextZoom.applied(ownTextZoom, percent)
        web.evaluateJavascript(RELAYOUT, null)
    }

    /** Edge to edge: the bar under the status bar, the page above the navigation bar and the keyboard. */
    private fun fitInsets() {
        val bar = findViewById<View>(R.id.bar)
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.root)) { root, insets ->
            val sys = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
            bar.setPadding(bar.paddingLeft, sys.top, bar.paddingRight, 0)
            root.setPadding(sys.left, 0, sys.right, maxOf(sys.bottom, ime.bottom))
            WindowInsetsCompat.CONSUMED
        }
    }

    private companion object {
        const val SHOW_ENDED_MS = 5_000L
        const val RELAYOUT = "window.dispatchEvent(new Event('resize'))"
        const val FADE_MS = 250L
    }
}
