package io.github.danielhp95.caracole

import android.app.Activity
import android.os.Bundle
import android.util.TypedValue
import android.widget.TextView
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat

/**
 * The phone's backups, from Settings' Backups row (lane alerts-backups): the backups listed, one made, one exported to
 * a file the owner picks, one restored.
 *
 * Until its lane lands it says it isn't built yet.
 */
class BackupsActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, 16f, resources.displayMetrics).toInt()
        val text = TextView(this).apply {
            text = getString(R.string.backups_not_built)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
        }
        ViewCompat.setOnApplyWindowInsetsListener(text) { view, insets ->
            val sys = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            view.setPadding(sys.left + pad, sys.top + pad, sys.right + pad, sys.bottom + pad)
            WindowInsetsCompat.CONSUMED
        }
        setContentView(text)
    }
}
