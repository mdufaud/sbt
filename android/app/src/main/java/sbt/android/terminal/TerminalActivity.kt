package __SBT_NAMESPACE__

import android.app.Activity
import android.content.Intent
import android.content.res.Configuration
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.text.Spannable
import android.text.SpannableStringBuilder
import android.text.TextUtils
import android.text.style.ForegroundColorSpan
import android.text.style.StyleSpan
import android.util.TypedValue

class TerminalActivity : Activity() {
    private lateinit var rootLayout: LinearLayout
    private lateinit var outputView: TextView
    private lateinit var scrollView: ScrollView
    private lateinit var actionBar: LinearLayout
    private lateinit var inputField: EditText
    private lateinit var argsField: EditText
    private lateinit var sendBtn: Button
    private lateinit var restartBtn: Button
    private val handler = Handler(Looper.getMainLooper())

    private var nativeThread: Thread? = null
    private var processRunning = false
    private var stdinPipeFd: Int = -1
    private var userScrolling = false

    // Output batching to avoid flooding UI thread
    private val outputBuffer = StringBuilder()
    @Volatile
    private var flushPending = false

    // ANSI SGR parser state, carried across flushes
    private var ansiFg: Int? = null
    private var ansiBold = false
    private val ansiPending = StringBuilder()

    // Scrollback cap: keep the newest chars, drop oldest whole lines. Bounds the
    // TextView buffer so append + relayout stay O(1) per flush instead of O(n).
    private val maxOutputChars = 100_000

    companion object {
        var loadError: Throwable? = null
        @Volatile var nativeMainCalled = false

        // ANSI 16-color palette (VS Code dark terminal theme)
        private val ANSI_NORMAL = intArrayOf(
            0xFF000000.toInt(), 0xFFCD3131.toInt(), 0xFF0DBC79.toInt(), 0xFFE5E510.toInt(),
            0xFF2472C8.toInt(), 0xFFBC3FBC.toInt(), 0xFF11A8CD.toInt(), 0xFFE5E5E5.toInt()
        )
        private val ANSI_BRIGHT = intArrayOf(
            0xFF666666.toInt(), 0xFFF14C4C.toInt(), 0xFF23D18B.toInt(), 0xFFF5F543.toInt(),
            0xFF3B8EEA.toInt(), 0xFFD670D6.toInt(), 0xFF29B8DB.toInt(), 0xFFFFFFFF.toInt()
        )
        init {
            try {
                System.loadLibrary("__SBT_LIB_NAME__")
            } catch (e: Throwable) {
                loadError = e
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (loadError != null) {
            showError("Failed to load native library", loadError!!)
            return
        }
        // If the process is still alive but the Activity was recreated (e.g. Android
        // reclaimed it after hours in background), native global state from the previous
        // main() call is corrupted. Kill the process and relaunch cleanly.
        if (nativeMainCalled) {
            val intent = packageManager.getLaunchIntentForPackage(packageName)
            if (intent != null) {
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
                startActivity(intent)
            }
            android.os.Process.killProcess(android.os.Process.myPid())
            return
        }
        try {
            setupUI()
            val argsStr = intent.getStringExtra("restart_args")
            val args = if (!argsStr.isNullOrEmpty()) {
                argsStr.split(Regex("\\s+")).toTypedArray()
            } else {
                arrayOf()
            }
            launchNative(args)
        } catch (e: Throwable) {
            showError("Activity setup failed", e)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        if (stdinPipeFd >= 0) {
            nativeCloseStdin(stdinPipeFd)
            stdinPipeFd = -1
        }
    }

    private fun launchNative(args: Array<String>) {
        nativeMainCalled = true
        processRunning = true
        handler.post { updateActionBar() }
        nativeThread = Thread {
            try {
                nativeMain(args)
            } catch (e: Throwable) {
                handler.post {
                    outputView.append("\n[JNI Error] ${e.message}\n")
                }
            }
            processRunning = false
            handler.post {
                flushOutput()
                updateActionBar()
            }
        }
        nativeThread!!.start()
    }

    private fun updateActionBar() {
        if (processRunning) {
            inputField.visibility = View.VISIBLE
            sendBtn.visibility = View.VISIBLE
            argsField.visibility = View.GONE
            restartBtn.visibility = View.GONE
        } else {
            inputField.visibility = View.GONE
            sendBtn.visibility = View.GONE
            argsField.visibility = View.VISIBLE
            restartBtn.visibility = View.VISIBLE
        }
    }

    private fun dpToPx(dp: Int): Int {
        return (dp * resources.displayMetrics.density).toInt()
    }

    private fun getScaledTextSize(): Float {
        val isTablet = (resources.configuration.screenLayout
                and Configuration.SCREENLAYOUT_SIZE_MASK) >= Configuration.SCREENLAYOUT_SIZE_LARGE
        val isLandscape = resources.configuration.orientation == Configuration.ORIENTATION_LANDSCAPE
        return when {
            isTablet && isLandscape -> 13f
            isTablet -> 12f
            isLandscape -> 10f
            else -> 11f
        }
    }

    private fun makeButton(label: String, color: String, onClick: () -> Unit): Button {
        val btnHeight = dpToPx(44)
        val btnPadH = dpToPx(16)
        val cornerRadius = dpToPx(6).toFloat()

        return Button(this).apply {
            text = label
            typeface = Typeface.MONOSPACE
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            setTextColor(Color.WHITE)
            isAllCaps = false
            minimumHeight = btnHeight
            minimumWidth = dpToPx(48)
            setPadding(btnPadH, 0, btnPadH, 0)
            val bg = GradientDrawable().apply {
                setColor(Color.parseColor(color))
                this.cornerRadius = cornerRadius
            }
            background = bg
            setOnClickListener { onClick() }
        }
    }

    private fun setupUI() {
        val bgColor = Color.parseColor("#1E1E1E")
        val fgColor = Color.parseColor("#CCCCCC")
        val barBgColor = Color.parseColor("#2D2D2D")
        val textSize = getScaledTextSize()
        val barPadding = dpToPx(6)
        val barSpacing = dpToPx(6)
        val textPadding = dpToPx(8)

        rootLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(bgColor)
            fitsSystemWindows = true
        }

        // Output area
        scrollView = ScrollView(this).apply {
            setBackgroundColor(bgColor)
            isVerticalScrollBarEnabled = true
            isSmoothScrollingEnabled = true
            setOnTouchListener { _, event ->
                when (event.action) {
                    MotionEvent.ACTION_DOWN, MotionEvent.ACTION_MOVE -> userScrolling = true
                    MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                        if (isNearBottom()) userScrolling = false
                    }
                }
                false
            }
        }
        outputView = TextView(this).apply {
            typeface = Typeface.MONOSPACE
            setTextSize(TypedValue.COMPLEX_UNIT_SP, textSize)
            setTextColor(fgColor)
            setPadding(textPadding, textPadding, textPadding, textPadding)
        }
        scrollView.addView(outputView)
        rootLayout.addView(scrollView, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f
        ))

        // Unified action bar: [input] [send] / [args] [restart]
        actionBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setBackgroundColor(barBgColor)
            setPadding(barPadding, barPadding, barPadding, barPadding)
            gravity = Gravity.CENTER_VERTICAL
        }

        val inputBg = GradientDrawable().apply {
            setColor(Color.parseColor("#383838"))
            cornerRadius = dpToPx(6).toFloat()
        }

        // Stdin input (visible while running)
        inputField = EditText(this).apply {
            typeface = Typeface.MONOSPACE
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            setTextColor(fgColor)
            setHintTextColor(Color.parseColor("#666666"))
            hint = "stdin..."
            background = inputBg
            isSingleLine = true
            minimumHeight = dpToPx(44)
            setPadding(dpToPx(12), dpToPx(8), dpToPx(12), dpToPx(8))
            imeOptions = EditorInfo.IME_ACTION_SEND
            setOnEditorActionListener { _, actionId, event ->
                if (actionId == EditorInfo.IME_ACTION_SEND ||
                    (event != null && event.keyCode == KeyEvent.KEYCODE_ENTER
                            && event.action == KeyEvent.ACTION_DOWN)) {
                    sendStdinLine()
                    true
                } else false
            }
        }

        sendBtn = makeButton("\u23CE", "#569CD6") { sendStdinLine() }

        // Args input (visible when stopped)
        val argsBg = GradientDrawable().apply {
            setColor(Color.parseColor("#383838"))
            cornerRadius = dpToPx(6).toFloat()
        }
        argsField = EditText(this).apply {
            typeface = Typeface.MONOSPACE
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            setTextColor(fgColor)
            setHintTextColor(Color.parseColor("#666666"))
            hint = "args..."
            background = argsBg
            isSingleLine = true
            minimumHeight = dpToPx(44)
            setPadding(dpToPx(12), dpToPx(8), dpToPx(12), dpToPx(8))
            imeOptions = EditorInfo.IME_ACTION_GO
            setOnEditorActionListener { _, actionId, event ->
                if (actionId == EditorInfo.IME_ACTION_GO ||
                    (event != null && event.keyCode == KeyEvent.KEYCODE_ENTER
                            && event.action == KeyEvent.ACTION_DOWN)) {
                    restartWithArgs()
                    true
                } else false
            }
        }

        restartBtn = makeButton("\u25B6", "#4EC9B0") { restartWithArgs() }

        val inputParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
            marginEnd = barSpacing
        }
        actionBar.addView(inputField, inputParams)
        actionBar.addView(sendBtn)

        val argsParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
            marginEnd = barSpacing
        }
        actionBar.addView(argsField, argsParams)
        actionBar.addView(restartBtn)

        rootLayout.addView(actionBar, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        ))

        setContentView(rootLayout)
    }

    private fun sendStdinLine() {
        val text = inputField.text.toString()
        inputField.text.clear()
        if (processRunning && stdinPipeFd >= 0) {
            val line = text + "\n"
            Thread { nativeWriteStdin(stdinPipeFd, line) }.start()
        }
    }

    private fun restartWithArgs() {
        val argsText = argsField.text.toString().trim()
        val intent = packageManager.getLaunchIntentForPackage(packageName)
        if (intent != null) {
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
            if (argsText.isNotEmpty()) {
                intent.putExtra("restart_args", argsText)
            }
            startActivity(intent)
            android.os.Process.killProcess(android.os.Process.myPid())
        }
    }

    private fun isNearBottom(): Boolean {
        val diff = outputView.bottom - (scrollView.scrollY + scrollView.height)
        return diff < 200
    }

    private fun scrollToBottom() {
        scrollView.post {
            scrollView.scrollTo(0, Math.max(0, outputView.bottom - scrollView.height))
        }
    }

    private fun flushOutput() {
        val chunk: String
        synchronized(outputBuffer) {
            chunk = outputBuffer.toString()
            outputBuffer.clear()
        }
        flushPending = false
        if (chunk.isNotEmpty()) {
            outputView.append(ansiToSpannable(chunk))
            trimOutput()
            if (!userScrolling || isNearBottom()) {
                scrollToBottom()
            }
        }
    }

    // Drop oldest lines once the buffer exceeds maxOutputChars. Deletes up to the
    // next newline after the overflow so a line is never cut mid-way; the removed
    // range's spans go with it. TextView.append makes the text Editable, so
    // editableText is non-null here.
    private fun trimOutput() {
        val editable = outputView.editableText ?: return
        val overflow = editable.length - maxOutputChars
        if (overflow <= 0) return
        val nl = TextUtils.indexOf(editable, '\n', overflow)
        val cut = if (nl >= 0) nl + 1 else overflow
        editable.delete(0, cut)
    }

    // Translate ANSI SGR escapes into colored/bold spans, stripping other CSI
    // sequences (cursor moves, clears). State persists across chunks; a partial
    // escape at a chunk boundary is held in ansiPending until completed.
    private fun ansiToSpannable(chunk: String): CharSequence {
        val sb = SpannableStringBuilder()
        val input = ansiPending.toString() + chunk
        ansiPending.setLength(0)
        val run = StringBuilder()
        fun flushRun() {
            if (run.isEmpty()) return
            val start = sb.length
            sb.append(run)
            ansiFg?.let { sb.setSpan(ForegroundColorSpan(it), start, sb.length, Spannable.SPAN_EXCLUSIVE_EXCLUSIVE) }
            if (ansiBold) sb.setSpan(StyleSpan(Typeface.BOLD), start, sb.length, Spannable.SPAN_EXCLUSIVE_EXCLUSIVE)
            run.setLength(0)
        }
        var i = 0
        while (i < input.length) {
            val c = input[i]
            if (c == '\u001b') {
                if (i + 1 >= input.length) { ansiPending.append(input.substring(i)); break }
                if (input[i + 1] == '[') {
                    var j = i + 2
                    while (j < input.length && input[j] !in '@'..'~') j++
                    if (j >= input.length) { ansiPending.append(input.substring(i)); break }
                    if (input[j] == 'm') { flushRun(); applySgr(input.substring(i + 2, j)) }
                    i = j + 1
                    continue
                }
                i++ // lone ESC, drop
                continue
            }
            run.append(c)
            i++
        }
        flushRun()
        return sb
    }

    private fun applySgr(params: String) {
        val codes = if (params.isEmpty()) listOf(0) else params.split(';').map { it.toIntOrNull() ?: 0 }
        for (code in codes) {
            when (code) {
                0 -> { ansiFg = null; ansiBold = false }
                1 -> ansiBold = true
                22 -> ansiBold = false
                39 -> ansiFg = null
                in 30..37 -> ansiFg = ANSI_NORMAL[code - 30]
                in 90..97 -> ansiFg = ANSI_BRIGHT[code - 90]
                // background and unsupported codes are ignored
            }
        }
    }

    @Suppress("unused")
    fun appendOutput(text: String) {
        synchronized(outputBuffer) {
            outputBuffer.append(text)
        }
        if (!flushPending) {
            flushPending = true
            handler.postDelayed({ flushOutput() }, 32)
        }
    }

    @Suppress("unused")
    fun setStdinPipeFd(fd: Int) {
        stdinPipeFd = fd
    }

    @Suppress("unused")
    fun getCacheAbsolutePath(): String {
        return cacheDir.absolutePath
    }

    private external fun nativeMain(args: Array<String>)
    private external fun nativeWriteStdin(fd: Int, text: String)
    private external fun nativeCloseStdin(fd: Int)

    private fun showError(title: String, error: Throwable) {
        val tv = TextView(this).apply {
            text = "$title:\n${error}\n\n${error.stackTraceToString()}"
            setTextColor(Color.RED)
            setBackgroundColor(Color.parseColor("#1E1E1E"))
            setPadding(32, 32, 32, 32)
            textSize = 12f
            typeface = Typeface.MONOSPACE
        }
        val sv = ScrollView(this)
        sv.addView(tv)
        setContentView(sv)
    }
}
