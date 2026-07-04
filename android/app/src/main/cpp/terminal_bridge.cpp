// Default Android terminal bridge for sbt.
// Redirects stdout/stderr to a scrolling terminal view via JNI.
// Provides stdin pipe, TMPDIR, crash reporting, and signal handling.
// The user's program provides: extern "C" int main(int argc, char** argv);

#include <jni.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <exception>
#include <vector>

#include <android/log.h>

extern int main(int argc, char **argv);

static JavaVM *g_jvm = nullptr;
static jobject g_activity = nullptr;
static jmethodID g_append_output = nullptr;
static jmethodID g_set_stdin_pipe_fd = nullptr;

static int g_stdout_pipe[2] = {-1, -1};
static int g_stderr_pipe[2] = {-1, -1};
static int g_stdin_pipe[2] = {-1, -1};
static int g_saved_stdout = -1;
static int g_saved_stderr = -1;
static int g_saved_stdin = -1;

static void forward_to_java(const char *text)
{
    JNIEnv *env = nullptr;
    bool attached = false;
    int status = g_jvm->GetEnv((void **)&env, JNI_VERSION_1_6);
    if (status == JNI_EDETACHED)
    {
        g_jvm->AttachCurrentThread(&env, nullptr);
        attached = true;
    }
    if (env != nullptr && g_activity != nullptr && g_append_output != nullptr)
    {
        jstring jstr = env->NewStringUTF(text);
        env->CallVoidMethod(g_activity, g_append_output, jstr);
        env->DeleteLocalRef(jstr);
    }
    if (attached)
    {
        g_jvm->DetachCurrentThread();
    }
}

static void forward_to_java_fmt(const char *fmt, ...)
{
    char buf[1024];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    forward_to_java(buf);
    __android_log_write(ANDROID_LOG_ERROR, "__SBT_LOG_TAG__", buf);
}

static void close_if_valid(int & fd)
{
    if (fd >= 0)
    {
        close(fd);
        fd = -1;
    }
}

static void restore_stdio()
{
    if (g_saved_stdout >= 0)
    {
        dup2(g_saved_stdout, STDOUT_FILENO);
        close(g_saved_stdout);
        g_saved_stdout = -1;
    }
    if (g_saved_stderr >= 0)
    {
        dup2(g_saved_stderr, STDERR_FILENO);
        close(g_saved_stderr);
        g_saved_stderr = -1;
    }
    if (g_saved_stdin >= 0)
    {
        dup2(g_saved_stdin, STDIN_FILENO);
        close(g_saved_stdin);
        g_saved_stdin = -1;
    }
    // NOTE: g_stdout_pipe[0] and g_stderr_pipe[0] are closed after pthread_join so the
    // read threads can drain all buffered data before exiting. Closing them here would
    // give EBADF to the threads and silently discard the last bytes of output.
    close_if_valid(g_stdin_pipe[1]);
}

static const char *signal_name(int sig)
{
    switch (sig)
    {
        case SIGSEGV:
            return "SIGSEGV (Segmentation fault)";
        case SIGABRT:
            return "SIGABRT (Aborted)";
        case SIGFPE:
            return "SIGFPE (Floating point exception)";
        case SIGILL:
            return "SIGILL (Illegal instruction)";
        case SIGBUS:
            return "SIGBUS (Bus error)";
        case SIGPIPE:
            return "SIGPIPE (Broken pipe)";
        default:
            return "Unknown signal";
    }
}

static void crash_signal_handler(int sig)
{
    restore_stdio();
    forward_to_java_fmt("\n[CRASH] Signal %d: %s\n", sig, signal_name(sig));

    // Re-raise with default handler to get proper crash dump in logcat
    signal(sig, SIG_DFL);
    raise(sig);
}

static void setup_crash_handlers()
{
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = crash_signal_handler;
    sa.sa_flags = SA_RESETHAND;
    sigaction(SIGSEGV, &sa, nullptr);
    sigaction(SIGABRT, &sa, nullptr);
    sigaction(SIGFPE, &sa, nullptr);
    sigaction(SIGILL, &sa, nullptr);
    sigaction(SIGBUS, &sa, nullptr);
}

static void setup_tmpdir(JNIEnv *env, jobject thiz)
{
    jclass clazz = env->GetObjectClass(thiz);
    jmethodID method = env->GetMethodID(clazz, "getCacheAbsolutePath", "()Ljava/lang/String;");
    if (method == nullptr)
        return;
    jstring jpath = (jstring)env->CallObjectMethod(thiz, method);
    if (jpath == nullptr)
        return;
    const char *path = env->GetStringUTFChars(jpath, nullptr);
    if (path != nullptr)
    {
        setenv("TMPDIR", path, 1);
        setenv("HOME", path, 1);
        __android_log_print(ANDROID_LOG_INFO, "__SBT_LOG_TAG__", "TMPDIR=%s", path);
        env->ReleaseStringUTFChars(jpath, path);
    }
    env->DeleteLocalRef(jpath);
}

// Returns the number of trailing bytes that form an incomplete UTF-8 sequence.
static int utf8_incomplete_tail(const char *buf, int len)
{
    if (len == 0)
        return 0;
    int i = len - 1;
    // Walk back over continuation bytes (10xxxxxx)
    while (i > 0 && ((unsigned char)buf[i] & 0xC0) == 0x80)
        i--;
    unsigned char lead = (unsigned char)buf[i];
    if (lead < 0x80)
        return 0;
    int expected;
    if ((lead & 0xE0) == 0xC0)
        expected = 2;
    else if ((lead & 0xF0) == 0xE0)
        expected = 3;
    else if ((lead & 0xF8) == 0xF0)
        expected = 4;
    else
        return 0;
    int available = len - i;
    return (available < expected) ? available : 0;
}

static void *read_pipe_thread(void *arg)
{
    int fd = *static_cast<int *>(arg);
    char buf[4096];
    int carry = 0;
    ssize_t n;
    while ((n = read(fd, buf + carry, sizeof(buf) - 1 - carry)) > 0)
    {
        int total = carry + (int)n;
        int tail = utf8_incomplete_tail(buf, total);
        int send_len = total - tail;
        if (send_len > 0)
        {
            buf[send_len] = '\0';
            forward_to_java(buf);
            __android_log_write(ANDROID_LOG_INFO, "__SBT_LOG_TAG__", buf);
        }
        if (tail > 0)
            memmove(buf, buf + send_len, tail);
        carry = tail;
    }
    if (carry > 0)
    {
        buf[carry] = '\0';
        forward_to_java(buf);
        __android_log_write(ANDROID_LOG_INFO, "__SBT_LOG_TAG__", buf);
    }
    return nullptr;
}

extern "C" JNIEXPORT void JNICALL Java___SBT_NAMESPACE_JNI___TerminalActivity_nativeMain(JNIEnv *env,
                                                                                         jobject thiz,
                                                                                         jobjectArray jargs)
{
    env->GetJavaVM(&g_jvm);
    g_activity = env->NewGlobalRef(thiz);
    jclass clazz = env->GetObjectClass(thiz);
    g_append_output = env->GetMethodID(clazz, "appendOutput", "(Ljava/lang/String;)V");
    g_set_stdin_pipe_fd = env->GetMethodID(clazz, "setStdinPipeFd", "(I)V");

    if (g_append_output == nullptr || g_set_stdin_pipe_fd == nullptr)
    {
        __android_log_print(ANDROID_LOG_ERROR,
                            "__SBT_LOG_TAG__",
                            "JNI method lookup failed: appendOutput=%p setStdinPipeFd=%p",
                            g_append_output,
                            g_set_stdin_pipe_fd);
        if (env->ExceptionCheck())
            env->ExceptionClear();
        env->DeleteGlobalRef(g_activity);
        g_activity = nullptr;
        return;
    }

    setup_tmpdir(env, thiz);
    setup_crash_handlers();

    // Build argv from Java string array
    int jargs_len = (jargs != nullptr) ? env->GetArrayLength(jargs) : 0;
    std::vector<std::string> arg_strings;
    arg_strings.reserve(jargs_len + 1);
    arg_strings.push_back("app");
    for (int i = 0; i < jargs_len; i++)
    {
        jstring jstr = (jstring)env->GetObjectArrayElement(jargs, i);
        if (jstr != nullptr)
        {
            const char *str = env->GetStringUTFChars(jstr, nullptr);
            if (str != nullptr)
            {
                arg_strings.push_back(str);
                env->ReleaseStringUTFChars(jstr, str);
            }
            env->DeleteLocalRef(jstr);
        }
    }
    std::vector<char *> argv_ptrs;
    argv_ptrs.reserve(arg_strings.size() + 1);
    for (auto & s : arg_strings)
        argv_ptrs.push_back(s.data());
    argv_ptrs.push_back(nullptr);
    int argc = static_cast<int>(arg_strings.size());

    // Setup stdout/stderr capture pipes
    pipe(g_stdout_pipe);
    pipe(g_stderr_pipe);

    g_saved_stdout = dup(STDOUT_FILENO);
    g_saved_stderr = dup(STDERR_FILENO);

    dup2(g_stdout_pipe[1], STDOUT_FILENO);
    dup2(g_stderr_pipe[1], STDERR_FILENO);
    close(g_stdout_pipe[1]);
    g_stdout_pipe[1] = -1;
    close(g_stderr_pipe[1]);
    g_stderr_pipe[1] = -1;

    setvbuf(stdout, nullptr, _IONBF, 0);
    setvbuf(stderr, nullptr, _IONBF, 0);

    // Setup stdin pipe: Java writes to [1], native reads from [0]
    if (pipe(g_stdin_pipe) == 0)
    {
        g_saved_stdin = dup(STDIN_FILENO);
        dup2(g_stdin_pipe[0], STDIN_FILENO);
        close(g_stdin_pipe[0]);
        g_stdin_pipe[0] = -1;

        // Send write-end fd to Java for stdin input
        if (g_set_stdin_pipe_fd != nullptr)
            env->CallVoidMethod(thiz, g_set_stdin_pipe_fd, g_stdin_pipe[1]);
    }
    else
    {
        __android_log_print(ANDROID_LOG_WARN, "__SBT_LOG_TAG__", "stdin pipe creation failed");
        g_stdin_pipe[0] = -1;
        g_stdin_pipe[1] = -1;
    }

    pthread_t stdout_thread;
    pthread_t stderr_thread;
    pthread_create(&stdout_thread, nullptr, read_pipe_thread, &g_stdout_pipe[0]);
    pthread_create(&stderr_thread, nullptr, read_pipe_thread, &g_stderr_pipe[0]);

    int ret = -1;
    bool crashed = false;

    try
    {
        ret = main(argc, argv_ptrs.data());
    }
    catch (const std::exception & e)
    {
        restore_stdio();
        forward_to_java_fmt("\n[CRASH] Uncaught exception: %s\n", e.what());
        __android_log_print(ANDROID_LOG_ERROR, "__SBT_LOG_TAG__", "Uncaught exception: %s", e.what());
        crashed = true;
    }
    catch (...)
    {
        restore_stdio();
        forward_to_java_fmt("\n[CRASH] Unknown exception\n");
        __android_log_write(ANDROID_LOG_ERROR, "__SBT_LOG_TAG__", "Unknown exception");
        crashed = true;
    }

    if (!crashed)
    {
        // Restores original fds: dup2 on STDOUT closes the last write-end of the
        // stdout/stderr pipes, so the read threads get natural EOF and drain all
        // remaining data. Do NOT close the read-ends yet.
        restore_stdio();
    }

    // Wait for read threads to drain all remaining pipe data before sending exit message.
    pthread_join(stdout_thread, nullptr);
    pthread_join(stderr_thread, nullptr);

    // Now safe to close the pipe read-ends (write-ends already closed above).
    close_if_valid(g_stdout_pipe[0]);
    close_if_valid(g_stderr_pipe[0]);

    if (crashed)
    {
        forward_to_java("\n[Process crashed]\n");
    }
    else
    {
        char exit_msg[64];
        snprintf(exit_msg, sizeof(exit_msg), "\n[Process exited with code %d]\n", ret);
        forward_to_java(exit_msg);
    }

    env->DeleteGlobalRef(g_activity);
    g_activity = nullptr;
}

extern "C" JNIEXPORT void JNICALL
    Java___SBT_NAMESPACE_JNI___TerminalActivity_nativeWriteStdin([[maybe_unused]] JNIEnv *env,
                                                                 [[maybe_unused]] jobject thiz,
                                                                 jint fd,
                                                                 jstring jtext)
{
    const char *text = env->GetStringUTFChars(jtext, nullptr);
    if (text != nullptr)
    {
        size_t len = strlen(text);
        size_t written = 0;
        while (written < len)
        {
            ssize_t n = write(fd, text + written, len - written);
            if (n <= 0)
                break;
            written += n;
        }
        env->ReleaseStringUTFChars(jtext, text);
    }
}

extern "C" JNIEXPORT void JNICALL
    Java___SBT_NAMESPACE_JNI___TerminalActivity_nativeCloseStdin([[maybe_unused]] JNIEnv *env,
                                                                 [[maybe_unused]] jobject thiz,
                                                                 jint fd)
{
    if (fd >= 0)
        close(fd);
}
