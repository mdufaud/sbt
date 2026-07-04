ifneq ($(shell which nproc),)
	UTILS_LOGICAL_CORE_NUMBER := $(shell nproc --all)
endif

ifeq ($(UTILS_LOGICAL_CORE_NUMBER),)
ifneq ($(shell which getconf),)
	UTILS_LOGICAL_CORE_NUMBER := $(shell getconf _NPROCESSORS_ONLN)
endif
endif

ifeq ($(UTILS_LOGICAL_CORE_NUMBER),)
ifneq ($(shell which lscpu),)
	UTILS_LOGICAL_CORE_NUMBER := $(shell lscpu | grep "^CPU(s):" | awk '{print $2}')
endif
endif