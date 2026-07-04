from datetime import datetime
from os import getenv
from sys import stderr

###############################################################################
# Term colors
###############################################################################

_term_color_prefix = "\033["
class TermColors(object):

    def __init__(self):
        if getenv("TERM"):
            self.red = f"{_term_color_prefix}0;31m"
            self.green = f"{_term_color_prefix}0;32m"
            self.orange = f"{_term_color_prefix}0;33m"
            self.blue = f"{_term_color_prefix}0;34m"
            self.bold_red = f"{_term_color_prefix}1;31m"
            self.bold_green = f"{_term_color_prefix}1;32m"
            self.bold_orange = f"{_term_color_prefix}1;33m"
            self.bold_blue = f"{_term_color_prefix}1;34m"
            self.reset = f"{_term_color_prefix}0m"
        else:
            self.red = ""
            self.green = ""
            self.orange = ""
            self.blue = ""
            self.bold_red = ""
            self.bold_green = ""
            self.bold_orange = ""
            self.bold_blue = ""
            self.reset = ""

term_colors = TermColors()

###############################################################################
# Build log
###############################################################################

_verbose = False

def set_verbose(v: bool):
    global _verbose
    _verbose = v

def __log(color, level, *msg, file=stderr):
    datestr = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{color}[{datestr}] builder [{level}]:", *msg, term_colors.reset, file=file)

def debug(*msg):
    if _verbose:
        __log(term_colors.blue, "debug", *msg)

def info(*msg):
    __log(term_colors.green, "info", *msg)

def warning(*msg):
    __log(term_colors.orange, "warning", *msg)

def error(*msg):
    __log(term_colors.red, "error", *msg, )