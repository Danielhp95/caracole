package android.print

import android.os.CancellationSignal
import android.os.ParcelFileDescriptor
import java.io.File

/**
 * A print adapter run as Android's print spooler runs it, into [file]: laid out for [attributes], then every page
 * written (PrintTest's look at what Export PDF prints, which the system's print dialog keeps from a test). Its
 * callbacks' constructors are this package's alone, so the helper is of this package. Call it on the main thread;
 * [done] gets the document's info, or why it failed.
 */
object PrintedPdf {
    fun write(adapter: PrintDocumentAdapter, attributes: PrintAttributes, file: File,
              done: (PrintDocumentInfo?, String?) -> Unit) {
        adapter.onStart()
        adapter.onLayout(null, attributes, CancellationSignal(), object : PrintDocumentAdapter.LayoutResultCallback() {
            override fun onLayoutFinished(info: PrintDocumentInfo, changed: Boolean) {
                val out = ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_WRITE or
                    ParcelFileDescriptor.MODE_CREATE or ParcelFileDescriptor.MODE_TRUNCATE)
                adapter.onWrite(arrayOf(PageRange.ALL_PAGES), out, CancellationSignal(),
                                object : PrintDocumentAdapter.WriteResultCallback() {
                                    override fun onWriteFinished(pages: Array<out PageRange>) = end(info, null)
                                    override fun onWriteFailed(error: CharSequence?) = end(info, "write failed: $error")
                                    override fun onWriteCancelled() = end(info, "write cancelled")

                                    private fun end(info: PrintDocumentInfo, why: String?) {
                                        out.close()
                                        adapter.onFinish()
                                        done(info, why)
                                    }
                                })
            }

            override fun onLayoutFailed(error: CharSequence?) = done(null, "layout failed: $error")
            override fun onLayoutCancelled() = done(null, "layout cancelled")
        }, null)
    }
}
