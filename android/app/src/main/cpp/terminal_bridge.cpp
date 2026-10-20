// Default Android terminal bridge for sbt.
// Redirects stdout/stderr to a scrolling terminal view via JNI.
// Provides stdin pipe, TMPDIR, crash reporting, and signal handling.
// The user's program provides: int main(int argc, char** argv);

#include <jni.h>
#include <pthread.h>
#include <setjmp.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include <atomic>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <exception>
#include <mutex>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

#include <android/log.h>

#include <sbt/jni.hpp>

extern int main(int argc, char **argv);

extern "C" [[noreturn]] void __real_exit(int code);

namespace
{

constexpr const char *LOG_TAG = "__SBT_LOG_TAG__";
constexpr const char *PROGRAM_NAME = "__SBT_PROJECT_NAME__";
constexpr auto DRAIN_TIMEOUT = std::chrono::seconds(2);

JavaVM *g_jvm = nullptr;
jobject g_activity = nullptr;
jmethodID g_append_output = nullptr;

int g_saved_stdout = -1;
int g_saved_stderr = -1;
int g_saved_stdin = -1;

std::mutex g_readers_mutex;
std::condition_variable g_readers_cv;
int g_readers_running = 0;

pthread_t g_main_thread {};
std::atomic<bool> g_main_running {false};
jmp_buf g_exit_jmp;
int g_exit_code = 0;

void forward_to_java(JNIEnv *env, std::string_view text)
{
    if (env == nullptr || g_activity == nullptr || g_append_output == nullptr)
        return;
    jstring jstr = sbt::jni::to_jstring(env, text);
    env->CallVoidMethod(g_activity, g_append_output, jstr);
    env->DeleteLocalRef(jstr);
    (void)sbt::jni::clear_exception(env);
}

void restore_fd(int & saved, int target)
{
    if (saved < 0)
        return;
    dup2(saved, target);
    close(saved);
    saved = -1;
}

// Restoring fd 1/2 drops the last pipe write-ends, so readers drain and hit EOF.
void restore_stdio()
{
    restore_fd(g_saved_stdout, STDOUT_FILENO);
    restore_fd(g_saved_stderr, STDERR_FILENO);
    restore_fd(g_saved_stdin, STDIN_FILENO);
}

void write_all(int fd, std::string_view text)
{
    while (!text.empty())
    {
        const ssize_t n = write(fd, text.data(), text.size());
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            return;
        text.remove_prefix(static_cast<std::size_t>(n));
    }
}

const char *signal_name(int sig)
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
        default:
            return "Unknown signal";
    }
}

// Async-signal-safe only: the message goes through the stderr pipe, readers forward it.
void crash_signal_handler(int sig)
{
    write_all(STDERR_FILENO, "\n[CRASH] ");
    write_all(STDERR_FILENO, signal_name(sig));
    write_all(STDERR_FILENO, "\n");
    const timespec delay {0, 200'000'000};
    nanosleep(&delay, nullptr);
    signal(sig, SIG_DFL);
    raise(sig);
}

void setup_crash_handlers()
{
    struct sigaction sa {};
    sa.sa_handler = crash_signal_handler;
    sa.sa_flags = static_cast<int>(SA_RESETHAND);
    for (int sig : {SIGSEGV, SIGABRT, SIGFPE, SIGILL, SIGBUS})
        sigaction(sig, &sa, nullptr);
}

void setup_tmpdir(JNIEnv *env, jobject thiz)
{
    jclass clazz = env->GetObjectClass(thiz);
    jmethodID method = env->GetMethodID(clazz, "getCacheAbsolutePath", "()Ljava/lang/String;");
    env->DeleteLocalRef(clazz);
    if (method == nullptr)
    {
        (void)sbt::jni::clear_exception(env);
        return;
    }
    jstring jpath = (jstring)env->CallObjectMethod(thiz, method);
    const std::string path = sbt::jni::to_string(env, jpath);
    env->DeleteLocalRef(jpath);
    if (path.empty())
        return;
    setenv("TMPDIR", path.c_str(), 1);
    setenv("HOME", path.c_str(), 1);
    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "TMPDIR=%s", path.c_str());
}

// Number of trailing bytes that form an incomplete UTF-8 sequence.
std::size_t utf8_incomplete_tail(const char *buf, std::size_t len)
{
    if (len == 0)
        return 0;
    std::size_t i = len - 1;
    while (i > 0 && (static_cast<unsigned char>(buf[i]) & 0xC0) == 0x80)
        --i;
    const auto lead = static_cast<unsigned char>(buf[i]);
    std::size_t expected = 0;
    if ((lead & 0xE0) == 0xC0)
        expected = 2;
    else if ((lead & 0xF0) == 0xE0)
        expected = 3;
    else if ((lead & 0xF8) == 0xF0)
        expected = 4;
    const std::size_t available = len - i;
    return available < expected ? available : 0;
}

void log_chunk(char *buf, std::size_t len)
{
    const char saved = buf[len];
    buf[len] = '\0';
    __android_log_write(ANDROID_LOG_INFO, LOG_TAG, buf);
    buf[len] = saved;
}

void read_pipe(int fd)
{
    sbt::jni::ScopedEnv scoped(g_jvm);
    char buf[4096];
    std::size_t carry = 0;
    while (true)
    {
        const ssize_t n = read(fd, buf + carry, sizeof(buf) - 1 - carry);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            break;
        const std::size_t total = carry + static_cast<std::size_t>(n);
        const std::size_t tail = utf8_incomplete_tail(buf, total);
        const std::size_t send_len = total - tail;
        if (send_len > 0)
        {
            forward_to_java(scoped.get(), {buf, send_len});
            log_chunk(buf, send_len);
        }
        memmove(buf, buf + send_len, tail);
        carry = tail;
    }
    if (carry > 0)
    {
        forward_to_java(scoped.get(), {buf, carry});
        log_chunk(buf, carry);
    }
    close(fd);
    {
        std::scoped_lock lock(g_readers_mutex);
        --g_readers_running;
    }
    g_readers_cv.notify_all();
}

bool capture_fd(int target, int & saved)
{
    int fds[2] = {-1, -1};
    if (pipe(fds) != 0)
        return false;
    saved = dup(target);
    dup2(fds[1], target);
    close(fds[1]);
    {
        std::scoped_lock lock(g_readers_mutex);
        ++g_readers_running;
    }
    std::thread(read_pipe, fds[0]).detach();
    return true;
}

int setup_stdin(JNIEnv *env, jobject thiz)
{
    int fds[2] = {-1, -1};
    if (pipe(fds) != 0)
    {
        __android_log_print(ANDROID_LOG_WARN, LOG_TAG, "stdin pipe creation failed: %s", strerror(errno));
        return -1;
    }
    g_saved_stdin = dup(STDIN_FILENO);
    dup2(fds[0], STDIN_FILENO);
    close(fds[0]);
    jclass clazz = env->GetObjectClass(thiz);
    jmethodID set_fd = env->GetMethodID(clazz, "setStdinPipeFd", "(I)V");
    env->DeleteLocalRef(clazz);
    if (set_fd == nullptr)
    {
        (void)sbt::jni::clear_exception(env);
        close(fds[1]);
        return -1;
    }
    env->CallVoidMethod(thiz, set_fd, fds[1]);
    return fds[1];
}

// exit() from main's thread unwinds back here instead of killing the app, so the
// output stays on screen; like exit(), it runs no destructors of main's frames.
int run_main(int argc, char **argv)
{
    g_main_thread = pthread_self();
    g_main_running = true;
    if (setjmp(g_exit_jmp) != 0)
        return g_exit_code;
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wmain"
    const int ret = main(argc, argv);
#pragma clang diagnostic pop
    g_main_running = false;
    return ret;
}

} // namespace

extern "C" [[noreturn]] void __wrap_exit(int code)
{
    fflush(nullptr);
    if (g_main_running && pthread_equal(pthread_self(), g_main_thread))
    {
        g_main_running = false;
        g_exit_code = code;
        longjmp(g_exit_jmp, 1);
    }
    __real_exit(code);
}

extern "C" JNIEXPORT void JNICALL Java___SBT_NAMESPACE_JNI___TerminalActivity_nativeMain(JNIEnv *env,
                                                                                         jobject thiz,
                                                                                         jobjectArray jargs)
{
    env->GetJavaVM(&g_jvm);
    jclass clazz = env->GetObjectClass(thiz);
    g_append_output = env->GetMethodID(clazz, "appendOutput", "(Ljava/lang/String;)V");
    env->DeleteLocalRef(clazz);
    if (g_append_output == nullptr)
    {
        __android_log_write(ANDROID_LOG_ERROR, LOG_TAG, "JNI method lookup failed: appendOutput(String)");
        (void)sbt::jni::clear_exception(env);
        return;
    }
    // Kept for the process lifetime: readers may outlive nativeMain when writers linger.
    g_activity = env->NewGlobalRef(thiz);

    setup_tmpdir(env, thiz);

    const jsize jargs_len = jargs != nullptr ? env->GetArrayLength(jargs) : 0;
    std::vector<std::string> arg_strings;
    arg_strings.reserve(static_cast<std::size_t>(jargs_len) + 1);
    arg_strings.emplace_back(PROGRAM_NAME);
    for (jsize i = 0; i < jargs_len; ++i)
    {
        jstring jstr = (jstring)env->GetObjectArrayElement(jargs, i);
        if (jstr == nullptr)
            continue;
        arg_strings.push_back(sbt::jni::to_string(env, jstr));
        env->DeleteLocalRef(jstr);
    }
    std::vector<char *> argv_ptrs;
    argv_ptrs.reserve(arg_strings.size() + 1);
    for (auto & s : arg_strings)
        argv_ptrs.push_back(s.data());
    argv_ptrs.push_back(nullptr);

    if (!capture_fd(STDOUT_FILENO, g_saved_stdout) || !capture_fd(STDERR_FILENO, g_saved_stderr))
    {
        const std::string msg = std::string("[bridge] cannot capture output: ") + strerror(errno) + "\n";
        restore_stdio();
        forward_to_java(env, msg);
        __android_log_write(ANDROID_LOG_ERROR, LOG_TAG, msg.c_str());
        return;
    }
    setvbuf(stdout, nullptr, _IONBF, 0);
    setvbuf(stderr, nullptr, _IONBF, 0);
    (void)setup_stdin(env, thiz);
    setup_crash_handlers();

    std::string status;
    try
    {
        const int ret = run_main(static_cast<int>(arg_strings.size()), argv_ptrs.data());
        status = "\n[Process exited with code " + std::to_string(ret) + "]\n";
    }
    catch (const std::exception & e)
    {
        status = std::string("\n[CRASH] Uncaught exception: ") + e.what() + "\n\n[Process crashed]\n";
    }
    catch (...)
    {
        status = "\n[CRASH] Unknown exception\n\n[Process crashed]\n";
    }
    g_main_running = false;

    fflush(nullptr);
    restore_stdio();
    {
        std::unique_lock lock(g_readers_mutex);
        if (!g_readers_cv.wait_for(lock, DRAIN_TIMEOUT, [] { return g_readers_running == 0; }))
            status += "[stdout/stderr still held open by a background writer]\n";
    }
    forward_to_java(env, status);
    __android_log_write(ANDROID_LOG_INFO, LOG_TAG, status.c_str());
}

extern "C" JNIEXPORT void JNICALL Java___SBT_NAMESPACE_JNI___TerminalActivity_nativeWriteStdin(JNIEnv *env,
                                                                                               [[maybe_unused]] jobject thiz,
                                                                                               jint fd,
                                                                                               jstring jtext)
{
    if (fd < 0)
        return;
    // The app does not ignore SIGPIPE: writing after the program closed stdin would kill it.
    sigset_t pipe_set;
    sigset_t old_set;
    sigemptyset(&pipe_set);
    sigaddset(&pipe_set, SIGPIPE);
    pthread_sigmask(SIG_BLOCK, &pipe_set, &old_set);
    write_all(fd, sbt::jni::to_string(env, jtext));
    const timespec no_wait {0, 0};
    while (sigtimedwait(&pipe_set, nullptr, &no_wait) == SIGPIPE)
    {
    }
    pthread_sigmask(SIG_SETMASK, &old_set, nullptr);
}

extern "C" JNIEXPORT void JNICALL Java___SBT_NAMESPACE_JNI___TerminalActivity_nativeCloseStdin([[maybe_unused]] JNIEnv *env,
                                                                                               [[maybe_unused]] jobject thiz,
                                                                                               jint fd)
{
    if (fd >= 0)
        close(fd);
}
