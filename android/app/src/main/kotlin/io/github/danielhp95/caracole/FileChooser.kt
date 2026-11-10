package io.github.danielhp95.caracole

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.webkit.ValueCallback
import android.webkit.WebChromeClient

/**
 * The page's file input (the sync sheet's Import a file, `#sync-file`) reaching Android's file picker:
 * WebChromeClient.onShowFileChooser asks [open], which opens ACTION_OPEN_DOCUMENT of any type (an export has no type
 * Android knows, and the input's `.caracole,.sqlite` are names, not types), and the activity's result comes back
 * through [result] to the page, the document's URI (the read permission the picker grants the app) or nothing for a
 * picker cancelled. One choice is open at a time: another asked for meanwhile ends the first with nothing.
 */
class FileChooser(private val activity: Activity) {
    private var waiting: ValueCallback<Array<Uri>>? = null

    /** The picker opened for [callback], the input's [params] (one file, or several when it takes several); true:
     * [callback] is always answered, by [result] or at once when no app picks a file. */
    fun open(callback: ValueCallback<Array<Uri>>, params: WebChromeClient.FileChooserParams?): Boolean {
        waiting?.onReceiveValue(null)
        waiting = callback
        val pick = Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*")
        if (params?.mode == WebChromeClient.FileChooserParams.MODE_OPEN_MULTIPLE) {
            pick.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
        }
        try {
            activity.startActivityForResult(pick, REQUEST)
        } catch (e: ActivityNotFoundException) {
            waiting = null
            callback.onReceiveValue(null)
            Handoff.toast(activity, activity.getString(R.string.no_picker))
        }
        return true
    }

    /** The picker's answer, handed to the page: true when [requestCode] was this chooser's. */
    fun result(requestCode: Int, resultCode: Int, data: Intent?): Boolean {
        if (requestCode != REQUEST) return false
        val callback = waiting ?: return true
        waiting = null
        callback.onReceiveValue(if (resultCode == Activity.RESULT_OK) picked(data) else null)
        return true
    }

    /** The documents picked: the clip's when there are several, else the one. */
    private fun picked(data: Intent?): Array<Uri>? {
        data ?: return null
        val clip = data.clipData
        if (clip != null && clip.itemCount > 0) return Array(clip.itemCount) { clip.getItemAt(it).uri }
        return data.data?.let { arrayOf(it) }
    }

    companion object {
        /** The activity result's request code for the picker. */
        const val REQUEST = 7
    }
}
