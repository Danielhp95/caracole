package android.database

/** A stand-in, for the JVM's tests, of Android's android.database.SQLException: what the bundled SQLite throws on
 * the device, where androidx.sqlite.SQLiteException is a typealias of it (SqliteErrorsTest). */
open class SQLException(message: String) : RuntimeException(message)
