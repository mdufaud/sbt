"""Write the test-run summary as JSON on stdout.

Usage: summary.py TEST_PATH APP_NAME [module ...]
Exit codes come from TEST_PATH/logs/<module>/exit_code; the gtest xml report
path is included only when the file exists.
"""
import json
import os
import sys


def main():
    test_path, app_name = sys.argv[1], sys.argv[2]
    summary = {"app": app_name, "modules": {}}
    for module in sys.argv[3:]:
        log_dir = os.path.join(test_path, "logs", module)
        exit_code = None
        exit_log = os.path.join(log_dir, "exit_code")
        if os.path.isfile(exit_log):
            try:
                with open(exit_log) as f:
                    exit_code = int(f.read().strip())
            except (ValueError, OSError):
                exit_code = None
        report = os.path.join(test_path, "reports", "{}_{}.xml".format(app_name, module))
        summary["modules"][module] = {
            "exit_code": exit_code,
            "report": report if os.path.isfile(report) else None,
            "log": os.path.join(log_dir, "output.log"),
        }
    json.dump(summary, sys.stdout, indent=4)
    print()


if __name__ == "__main__":
    main()
