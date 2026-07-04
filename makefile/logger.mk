ifneq (${TERM},)
_color_red = \033[0;31m
_color_green = \033[0;32m
_color_yellow = \033[0;33m
_color_reset = \033[0m
_mk_color_red := $(shell echo -e "\033[0;31m")
_mk_color_green := $(shell echo -e "\033[0;32m")
_mk_color_yellow := $(shell echo -e "\033[0;33m")
_mk_color_reset := $(shell echo -e "\033[0m")
else
_color_red =
_color_green =
_color_yellow =
_color_reset =
_mk_color_red =
_mk_color_green =
_mk_color_yellow =
_mk_color_reset =
endif

echo_log = `date "+[%Y-%m-%d %H:%M:%S] $2 [$1]: $3"`
echo_log_info = echo -e "$(_color_green)$(call echo_log,info,$1,$2)$(_color_reset)"
echo_log_warning = echo -e "$(_color_yellow)$(call echo_log,warning,$1,$2)$(_color_reset)"
echo_log_error = echo -e "$(_color_red)$(call echo_log,error,$1,$2)$(_color_reset)"

mk_log = $(shell date "+[%Y-%m-%d %H:%M:%S] $2 [$1]: $3")
mk_log_info = $(info $(_mk_color_green)$(call mk_log,info,$1,$2)$(_mk_color_reset))
mk_log_warning = $(info $(_mk_color_yellow)$(call mk_log,warning,$1,$2)$(_mk_color_reset))
mk_log_error = $(info $(_mk_color_red)$(call mk_log,error,$1,$2)$(_mk_color_reset))
