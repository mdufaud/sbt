#pragma once

#include <jni.h>

#include <cstddef>
#include <string>
#include <string_view>
#include <vector>

namespace sbt::jni
{

namespace detail
{

inline std::vector<jchar> utf8_to_utf16(std::string_view in)
{
    std::vector<jchar> out;
    out.reserve(in.size());
    std::size_t i = 0;
    while (i < in.size())
    {
        const auto lead = static_cast<unsigned char>(in[i]);
        std::size_t len = 0;
        char32_t cp = 0;
        char32_t min = 0;
        if (lead < 0x80)
        {
            len = 1;
            cp = lead;
        }
        else if ((lead & 0xE0) == 0xC0)
        {
            len = 2;
            cp = lead & 0x1Fu;
            min = 0x80;
        }
        else if ((lead & 0xF0) == 0xE0)
        {
            len = 3;
            cp = lead & 0x0Fu;
            min = 0x800;
        }
        else if ((lead & 0xF8) == 0xF0)
        {
            len = 4;
            cp = lead & 0x07u;
            min = 0x10000;
        }
        bool valid = len > 0 && i + len <= in.size();
        for (std::size_t k = 1; valid && k < len; ++k)
        {
            const auto cont = static_cast<unsigned char>(in[i + k]);
            valid = (cont & 0xC0) == 0x80;
            cp = (cp << 6) | (cont & 0x3Fu);
        }
        valid = valid && cp >= min && cp <= 0x10FFFF && (cp < 0xD800 || cp > 0xDFFF);
        if (!valid)
        {
            out.push_back(0xFFFD);
            ++i;
            continue;
        }
        if (cp >= 0x10000)
        {
            cp -= 0x10000;
            out.push_back(static_cast<jchar>(0xD800 + (cp >> 10)));
            out.push_back(static_cast<jchar>(0xDC00 + (cp & 0x3FF)));
        }
        else
        {
            out.push_back(static_cast<jchar>(cp));
        }
        i += len;
    }
    return out;
}

inline void append_utf8(std::string & out, char32_t cp)
{
    if (cp < 0x80)
    {
        out.push_back(static_cast<char>(cp));
    }
    else if (cp < 0x800)
    {
        out.push_back(static_cast<char>(0xC0 | (cp >> 6)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    }
    else if (cp < 0x10000)
    {
        out.push_back(static_cast<char>(0xE0 | (cp >> 12)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    }
    else
    {
        out.push_back(static_cast<char>(0xF0 | (cp >> 18)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    }
}

inline std::string utf16_to_utf8(const std::vector<jchar> & in)
{
    std::string out;
    out.reserve(in.size());
    for (std::size_t i = 0; i < in.size(); ++i)
    {
        char32_t cp = in[i];
        if (cp >= 0xD800 && cp <= 0xDBFF && i + 1 < in.size() && in[i + 1] >= 0xDC00 && in[i + 1] <= 0xDFFF)
        {
            cp = 0x10000 + ((cp - 0xD800) << 10) + (in[i + 1] - 0xDC00u);
            ++i;
        }
        else if (cp >= 0xD800 && cp <= 0xDFFF)
        {
            cp = 0xFFFD;
        }
        append_utf8(out, cp);
    }
    return out;
}

} // namespace detail

class ScopedEnv
{
    public:
        explicit ScopedEnv(JavaVM *vm): _vm(vm)
        {
            if (_vm == nullptr)
                return;
            void *env = nullptr;
            const jint status = _vm->GetEnv(&env, JNI_VERSION_1_6);
            if (status == JNI_OK)
            {
                _env = static_cast<JNIEnv *>(env);
            }
            else if (status == JNI_EDETACHED)
            {
                JNIEnv *attached = nullptr;
                if (_vm->AttachCurrentThread(&attached, nullptr) == JNI_OK)
                {
                    _env = attached;
                    _attached = true;
                }
            }
        }

        ~ScopedEnv()
        {
            if (_attached)
                _vm->DetachCurrentThread();
        }

        ScopedEnv(const ScopedEnv &) = delete;
        ScopedEnv & operator=(const ScopedEnv &) = delete;

        [[nodiscard]] JNIEnv *get() const { return _env; }
        explicit operator bool() const { return _env != nullptr; }

    private:
        JavaVM *_vm;
        JNIEnv *_env = nullptr;
        bool _attached = false;
};

[[nodiscard]] inline jstring to_jstring(JNIEnv *env, std::string_view utf8)
{
    const std::vector<jchar> utf16 = detail::utf8_to_utf16(utf8);
    return env->NewString(utf16.data(), static_cast<jsize>(utf16.size()));
}

[[nodiscard]] inline std::string to_string(JNIEnv *env, jstring str)
{
    if (str == nullptr)
        return {};
    std::vector<jchar> utf16(static_cast<std::size_t>(env->GetStringLength(str)));
    env->GetStringRegion(str, 0, static_cast<jsize>(utf16.size()), utf16.data());
    return detail::utf16_to_utf8(utf16);
}

[[nodiscard]] inline bool clear_exception(JNIEnv *env)
{
    if (!env->ExceptionCheck())
        return false;
    env->ExceptionDescribe();
    env->ExceptionClear();
    return true;
}

} // namespace sbt::jni
