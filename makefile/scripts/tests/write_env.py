"""Write <build>/test/.env from SBT_ENV_JSON and print the test path.

Usage: write_env.py SBT_ENV_JSON
Fixed paths, then platform facts, then the app/addon test env (later export wins).
"""
import json
import os
import shlex
import sys


def main():
    with open(sys.argv[1]) as f:
        d = json.load(f)

    b = d["build_path"]
    p = d["paths"]
    test_path = b + "/" + p["test"]
    os.makedirs(test_path, exist_ok=True)

    lines = []

    def ex(key, value):
        lines.append("export {}={}".format(key, shlex.quote(str(value))))

    ex("APP_NAME", d["app_name"])
    ex("PROJECT_ROOT_PATH", d["root_path"])
    ex("MODULES_PATH", d["modules_path"])
    ex("BUILD_PATH", b)
    ex("LIB_PATH", b + "/" + p["lib"])
    ex("BIN_PATH", b + "/" + p["bin"])
    ex("ETC_PATH", b + "/" + p["etc"])
    ex("SHARE_PATH", b + "/" + p["share"])
    ex("EXTLIB_PATH", b + "/" + p["extlib"])
    ex("EXTLIB_LIB_PATH", b + "/" + p["extlib_lib"])
    ex("TEST_PATH", test_path)
    ex("TEST_BIN_PATH", b + "/" + p["test_bin"])
    ex("EXPORT_PATH", b + "/" + p["export"])
    ex("TEST_RUNNER", d["test"]["runner"])
    ex("TEST_BIN_EXT", d["test"]["bin_ext"])
    bld = d["build"]
    ex("SBT_PLATFORM", bld["platform"])
    ex("SBT_MACHINE", bld["machine"])
    ex("SBT_LIBC", bld["libc"])
    ex("SBT_MODE", bld["mode"])
    ex("SBT_COMPILER", bld["compiler"])
    ex("SBT_TRIPLET", bld["triplet"])
    ex("SBT_LIBS_TYPE", bld["libs_type"])
    ex("SBT_CROSS", 1 if bld["cross"] else 0)
    ex("PYTHON_BIN", sys.executable)
    ex("TEST_MODULE_REPORTS", 1 if d["test"].get("module_reports", True) else 0)
    app_timeout = d["test"].get("timeout")
    ex("TEST_APP_TIMEOUT", "" if app_timeout is None else app_timeout)
    for mapping in ("env", "command"):
        for key, value in (d["test"].get(mapping) or {}).items():
            ex(key, value)

    with open(os.path.join(test_path, ".env"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print(test_path)


if __name__ == "__main__":
    main()
