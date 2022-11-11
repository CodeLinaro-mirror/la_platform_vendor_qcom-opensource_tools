LOCAL_PATH:= $(call my-dir)
include $(CLEAR_VARS)
LOCAL_SRC_FILES := \
                gpio_latency.c \

LOCAL_MODULE:= gpio_latency
LOCAL_SHARED_LIBRARIES:= liblog
LOCAL_MODULE_TAGS := optional
include $(BUILD_EXECUTABLE)
