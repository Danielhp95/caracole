package io.github.danielhp95.caracole

import android.Manifest
import android.animation.ValueAnimator
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
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
import io.github.danielhp95.caracole.mirror.Links
import io.github.danielhp95.caracole.mirror.Route
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.io.ByteArrayInputStream
import java.io.File
import java.io.IOException
import java.net.URI
import kotlin.coroutines.resume

/**
 * The library screen: a WebView showing the phone's own caracole, its server on `http://127.0.0.1:8738` (the library
 * page, and the mirror's pages, caracole's own, unchanged, at their paths on caracole serve: [Links]), with a small
 * bar (the page's title; Copy pages, Logbook, Settings) and the sync's line under it. The WebView carries the launch's
 * cookie and loads that exact origin alone. A pinch sizes the pages' text ([pinchToSize]), and shows the size it is
 * at over the page while it lasts ([sizeLabel]).
 */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var status: TextView
    private lateinit var title: TextView
    /** Where links go, once the server has started (the WebView's client reads it on its own threads). */
    @Volatile private var links: Links? = null
    private var files: LocalFiles? = null
    /** The server's origin, once it has started. */
    private var origin: String? = null
    private lateinit var settings: Settings
    private lateinit var pinch: TextPinch
    private lateinit var label: SizeLabel
    /** alphaTab's bundle from the APK's assets, which the sandboxed Guitar Pro page asks for with no cookie. */
    private lateinit var alphaTab: AlphaTabAssets
    /** The WebView's own text zoom, as Android's font size has it: what [TextZoom.DEFAULT] stands for. */
    private var ownTextZoom = TextZoom.DEFAULT
    private var scope: CoroutineScope = MainScope()
    /** The screen's own work, from its creation to its end: the server's start, a file handed off. */
    private val screen: CoroutineScope = MainScope()
    private var hiding: Job? = null
    private var shown = false
    /** The page an intent asked the screen to show (a song shared to the app: ShareLinkActivity's), until the server
     * has started. */
    private var asked: String? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowCompat.getInsetsController(window, window.decorView).isAppearanceLightStatusBars = false
        setContentView(R.layout.activity_main)
        web = findViewById(R.id.web)
        status = findViewById(R.id.status)
        title = findViewById(R.id.title)
        settings = Settings(this)
        alphaTab = AlphaTabAssets(this)
        fitInsets()

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
        // A link with `download` (a Guitar Pro file on the library page, the viewer's Export PDF), or a file the
        // WebView can't show, comes here, not as a navigation.
        web.setDownloadListener { url, _, _, _, _ -> follow(url, download = true) }

        findViewById<ImageButton>(R.id.more).setOnClickListener { menu(it) }
        backCallback()
        screen.launch { start(savedInstanceState) }
    }

    /**
     * The phone's caracole started (in this process, once), then the launch's cookie set for its origin, then its
     * library page, or the history Android saved when it is today's origin's. A first start, with nothing set up
     * (no copy, no address), opens Settings too.
     */
    private suspend fun start(saved: Bundle?) {
        val phone = try {
            withContext(Dispatchers.IO) { Caracole.phone(this@MainActivity) }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Throwable) {
            // Anything, an Error among them (the bundled SQLite's native library that won't load, say): said on the
            // screen, never a crash.
            say(getString(R.string.no_server, e.message ?: e.javaClass.simpleName))
            return
        }
        val origin = phone.server.origin
        files = LocalFiles(phone.app::handle, URI(origin), Caracole.secret)
        links = Links(URI(origin)) { Caracole.isFile(this, it) }
        this.origin = origin
        if (!withCookie(origin)) {
            say(getString(R.string.no_cookie))
            return
        }
        val page = asked ?: if (saved == null) SharedLink.shown(intent?.getStringExtra(SharedLink.PAGE)) else null
        asked = null
        if (page != null) {
            showPage(page)
        } else if (saved != null && SavedScreen.restores(saved.getString(SavedScreen.ORIGIN), origin) &&
            web.restoreState(saved) != null) {
            shown = true
        } else {
            showLibrary()
        }
        if (saved == null && page == null && settings.server.isBlank() && Caracole.mirror(this).manifest() == null) {
            openSettings()
        }
    }

    /** A song shared to the app while the screen was open (MainActivity is single-task): its page, once the server
     * has started. */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        val page = SharedLink.shown(intent.getStringExtra(SharedLink.PAGE)) ?: return
        if (origin != null) showPage(page) else asked = page
    }

    /** The launch's cookie, set for [origin] before the WebView asks it for anything; false when it can't be. */
    private suspend fun withCookie(origin: String): Boolean = suspendCancellableCoroutine { done ->
        val cookies = CookieManager.getInstance()
        cookies.setAcceptCookie(true)
        cookies.setCookie(origin, Caracole.cookie()) { set ->
            cookies.flush()
            if (done.isActive) done.resume(set)
        }
    }

    override fun onResume() {
        super.onResume()
        pinch.set(settings.textZoom) // as Settings' Reset may have left it
        if (!shown && origin != null) showLibrary()
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
        if (shown) {
            web.saveState(outState)
            outState.putString(SavedScreen.ORIGIN, origin)
        }
    }

    override fun onDestroy() {
        screen.cancel()
        web.destroy()
        super.onDestroy()
    }

    /** A page of the phone's server by its path and query ("/share?text=…", already encoded), once it has started. */
    private fun showPage(page: String) {
        val origin = origin ?: return
        web.loadUrl(origin + page)
        shown = true
    }

    /**
     * The share page's Cancel: the screen back where it was before the share (the WebView's history before its first
     * share page, else the library page), and the app that shared in front again.
     */
    private fun leaveShare() {
        val history = web.copyBackForwardList()
        var at = history.currentIndex
        while (at >= 0 && SharedLink.isSharePage(history.getItemAtIndex(at)?.url, origin)) at--
        if (at >= 0 && at < history.currentIndex) web.goBackOrForward(at - history.currentIndex) else showLibrary()
        moveTaskToBack(true)
    }

    /** Opens the library page, the server's own, once it has started. */
    private fun showLibrary() {
        val links = links ?: return
        web.loadUrl(links.address(""))
        shown = true
    }

    /**
     * The library page's Sync tab (`#tab=sync`): where the phone and the computer compare their libraries, and each
     * takes what the other changed, the computer's address the one Settings keeps. From the library page itself a
     * change of its address alone (tabs.js hears it); from any other page, the library page at that tab.
     */
    private fun showSyncTab() {
        val links = links ?: return
        askToNotify()
        web.loadUrl(links.address("") + SYNC_TAB)
        shown = true
    }

    /** Android 13 and later show the notification of a sync that runs (SyncService) only once asked; it runs either
     * way. */
    private fun askToNotify() {
        if (Build.VERSION.SDK_INT < 33) return
        if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) return
        requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), NOTIFY)
    }

    private fun openSettings() = startActivity(Intent(this, SettingsActivity::class.java))

    private fun menu(anchor: View) {
        val popup = PopupMenu(this, anchor)
        popup.menuInflater.inflate(R.menu.main, popup.menu)
        popup.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.sync_now -> Syncs.now(this)
                R.id.sync_tab -> showSyncTab()
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

    /** A line in the status bar, kept until the next sync's. */
    private fun say(text: String) {
        hiding?.cancel()
        status.text = text
        status.visibility = View.VISIBLE
    }

    /**
     * Where a link the page follows goes ([Links.route]; with [download], one the WebView's download listener heard);
     * true when the WebView doesn't load it. The viewer's Export PDF prints the viewer shown ([Printer]).
     */
    private fun follow(url: String, download: Boolean = false): Boolean {
        val links = links ?: return true
        if (!download && SharedLink.isCancel(url, origin)) {
            leaveShare()
            return true
        }
        return when (val route = links.route(url, download)) {
            Route.Page -> false
            is Route.File -> { handOff(route.path); true }
            is Route.Browser -> { Handoff.openBrowser(this, route.url); true }
            is Route.Print -> { Printer.print(this, web, route.url); true }
            Route.Ignored -> true
        }
    }

    /**
     * The library's file at [path] to another app: read from the phone's server in this process ([LocalFiles], the
     * launch's cookie and all), copied into the cache's handoff/ and handed over ([Handoff]); or why it can't be.
     */
    private fun handOff(path: String) {
        val files = files ?: return
        screen.launch {
            val refused: String? = try {
                withContext(Dispatchers.IO) {
                    when (val got = files.get(path)) {
                        is Fetched.File -> {
                            val copy = Handoff.copyInto(File(cacheDir, Handoff.FOLDER), path, got)
                            withContext(Dispatchers.Main) { Handoff.openFile(this@MainActivity, copy, got.type) }
                            null
                        }
                        is Fetched.Refused ->
                            if (got.status == 404) getString(R.string.missing)
                            else got.message ?: getString(R.string.not_served, got.status)
                    }
                }
            } catch (e: IOException) {
                getString(R.string.handoff_failed, e.message ?: e.javaClass.simpleName)
            }
            if (refused != null) Handoff.toast(this@MainActivity, refused)
        }
    }

    private inner class Client : WebViewClient() {
        override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
            // alphaTab's bundle first, from the APK ([AlphaTabAssets]). Then the phone's server, at its exact origin,
            // is all the WebView loads: anything else (another port of 127.0.0.1 among them, which the launch's
            // cookie would reach, cookies ignoring the port) is a 404 here and reaches no socket.
            alphaTab.answer(request) ?: if (links?.loads(request.url.toString()) == true) null else notFound()

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

    private fun notFound() =
        WebResourceResponse("text/plain", "utf-8", 404, "Not Found", emptyMap(), ByteArrayInputStream(ByteArray(0)))

    private companion object {
        const val SHOW_ENDED_MS = 5_000L
        const val SYNC_TAB = "#tab=sync"
        const val NOTIFY = 1
        const val RELAYOUT = "window.dispatchEvent(new Event('resize'))"
        const val FADE_MS = 250L
    }
}
