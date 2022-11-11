/*
 * SPDX-License-Identifier: GPL-2.0-only
 * Copyright (c) 2022 Qualcomm Innovation Center, Inc. All rights reserved.
 * Copyright (C) 2016 Linus Walleij
 */
#include <unistd.h>
#include <stdlib.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <dirent.h>
#include <errno.h>
#include <string.h>
#include <poll.h>
#include <fcntl.h>
#include <getopt.h>
#include <inttypes.h>
#include <sys/ioctl.h>
#include <sys/types.h>
#include <linux/gpio.h>
#include <string.h>
#include <pthread.h>
#include <log/log.h>

#define GPIO_TEST_LOG_ERR             (0x1) /**< error message, represents code bugs that should be debugged and fixed.*/
#define GPIO_TEST_LOG_INFO            (0x2) /**< info message, additional info to support debug */
#define GPIO_TEST_LOG_DBG             (0x4) /**< debug message, required at minimum for debug.*/
#define GPIO_TEST_LOG_VERBOSE         (0x8) /**< verbose message, useful primarily to help developers debug low-level code */


#define GPIO_TEST_ERR(arg,...)                                          \
    if (gpio_test_log_lvl & GPIO_TEST_LOG_ERR) {                              \
        ALOGE("%s: %d: "  arg, __func__, __LINE__, ##__VA_ARGS__);\
    }
#define GPIO_TEST_DBG(arg,...)                                           \
    if (gpio_test_log_lvl & GPIO_TEST_LOG_DBG) {                               \
        ALOGD("%s: %d: "  arg, __func__, __LINE__, ##__VA_ARGS__); \
    }
#define GPIO_TEST_INFO(arg,...)                                         \
    if (gpio_test_log_lvl & GPIO_TEST_LOG_INFO) {                             \
        ALOGI("%s: %d: "  arg, __func__, __LINE__, ##__VA_ARGS__);\
    }
#define GPIO_TEST_VERBOSE(arg,...)                                      \
    if (gpio_test_log_lvl & GPIO_TEST_LOG_VERBOSE) {                          \
        ALOGV("%s: %d: "  arg, __func__, __LINE__, ##__VA_ARGS__);\
    }

#define MAX_PLAYBACK_CMD_SIZE 256
#define DELAY_AFTER_PLAYBACK_START 200000
static uint32_t gpio_test_log_lvl = GPIO_TEST_LOG_ERR|GPIO_TEST_LOG_DBG; /* TODO make this dynamic*/

struct playback_thread_params
{
   char playbackCmd[MAX_PLAYBACK_CMD_SIZE];
};
struct receiver_thread_params
{
    int fd;
    unsigned int gpio_receive_interrupt;
    unsigned int serve_edge;
};


/**
* interupt_cond[0] and interupt_lock[0] -> Used for signaling after received interrupt.
* interupt_cond[1] and interupt_lock[1] -> Used for signaling after registartion to receive interrupt.
* interupt_cond[2] and interupt_lock[2] -> Used for signaling before start of playback from playback thread.
*/
pthread_cond_t interupt_cond[3] = {PTHREAD_COND_INITIALIZER, PTHREAD_COND_INITIALIZER, PTHREAD_COND_INITIALIZER};
pthread_mutex_t interupt_lock[3] = {PTHREAD_MUTEX_INITIALIZER, PTHREAD_MUTEX_INITIALIZER,PTHREAD_MUTEX_INITIALIZER};


int open_device(const char *device_name)
{
    return open(device_name,0);
}

void send_signal(pthread_cond_t *cond, pthread_mutex_t* lock )
{
    pthread_mutex_lock(lock);
    pthread_cond_signal(cond);
    pthread_mutex_unlock(lock);
}

void wait_for_signal(pthread_cond_t *cond, pthread_mutex_t* lock)
{
    pthread_mutex_lock(lock);
    pthread_cond_wait(cond, lock);
    pthread_mutex_unlock(lock);
}

void wait_for_dsp_interrupt()
{
    pthread_cond_wait(&interupt_cond[0], &interupt_lock[0]);
}
/**
  It will toggle the gpio register value.

  @param[fd]  device handle.
  @param[gpio] gpio number.
  @param[default_value] default value to set before toggling.
  @param[set_value] value to set for gpio register.

  @return
  - Positive number -- on success
  - -1 -- Error occurred.
  @newpage
*/
int output_device(int fd, unsigned int gpio, int default_value, int set_value)
{
    struct gpiohandle_data data = {{set_value,}};
    struct gpiohandle_request req = {{gpio, }, GPIOHANDLE_REQUEST_OUTPUT, {default_value, }, "gpio-hammer", 1, fd};
    int ret;

    ret = ioctl(fd, GPIO_GET_LINEHANDLE_IOCTL, &req);
    if (ret == -1) {
            ret = -errno;
            GPIO_TEST_ERR("Failed to issue %s (%d), %s\n",
                   "GPIO_GET_LINEHANDLE_IOCTL", ret, strerror(errno));
            return ret;
    }

    ret = ioctl(req.fd, GPIOHANDLE_SET_LINE_VALUES_IOCTL, &data);
    if (ret == -1) {
            ret = -errno;
            GPIO_TEST_ERR("Failed to issue %s (%d), %s\n",
                   "GPIOHANDLE_SET_LINE_VALUES_IOCTL", ret,
                    strerror(errno));
    }
    close(req.fd);


    return ret;
}

/**
  Register for interrupts on GPIO and waits and signals after receiving interrupt.

  @return
  - Positive number -- on success
  - -1 -- Error occurred.
  @newpage
*/

int input_device(struct receiver_thread_params *params)
{
    struct gpioevent_request req = {params->gpio_receive_interrupt, GPIOHANDLE_REQUEST_INPUT, params->serve_edge,"gpio-event-mon",0};
    int ret;
    struct gpiohandle_data data;

    GPIO_TEST_INFO("input_device %d called\n",params->gpio_receive_interrupt);
    ret = ioctl(params->fd, GPIO_GET_LINEEVENT_IOCTL, &req);
    if (ret == -1) {
            ret = -errno;
            GPIO_TEST_ERR(" unsuccessful gpio_latency to issue GET EVENT "
                    "IOCTL (%d)\n", ret);
            return ret;
    }

    ret = ioctl(req.fd, GPIOHANDLE_GET_LINE_VALUES_IOCTL, &data);
    if (ret == -1) {
            ret = -errno;
            GPIO_TEST_ERR(" Fail gpio_latency to handle issue GPIOHANDLE GET LINE "
                    "VALUES IOCTL (%d)\n", ret);
            return ret;
    }
    // signal after registration done
    send_signal(&interupt_cond[1], &interupt_lock[1]);

    while (1) {
            struct gpioevent_data event;
            ret = read(req.fd, &event, sizeof(event));
            if (ret == -1) {
                    if (errno == -EAGAIN) {
                            GPIO_TEST_ERR("Unavailable\n");
                    } else {
                            ret = -errno;
                            GPIO_TEST_ERR("Not Getting gpio_latency read event (%d)\n",
                            ret);
                            break;
                    }
            }
            if (ret == sizeof(event)) {
                GPIO_TEST_INFO("Interrupt received id=%d \n", event.id);
            //signal after receiving interrupt
                send_signal(&interupt_cond[0], &interupt_lock[0]);
            }
    }

    close(req.fd);

    return ret;
}

void *interrupt_receiver(void *vargp)
{
    int ret;
    struct receiver_thread_params *rec_params = (struct receiver_thread_params*)vargp;
    ret = input_device(rec_params);
    return NULL;
}

int interrupt_dsp_and_wait(int fd, unsigned int gpio_send_interrupt, unsigned int trigger_edge)
{
    int ret;
    if(trigger_edge == GPIOEVENT_REQUEST_RISING_EDGE)
    {
        ret = output_device(fd,gpio_send_interrupt, 0, 1);
        if (ret)
        {
            GPIO_TEST_ERR("output device set to one on gpio %d Fail!! : ret %d\n",gpio_send_interrupt, ret);
            return ret;
        }
        GPIO_TEST_INFO("output device set to one on gpio %d ret %d\n",gpio_send_interrupt, ret);

        wait_for_dsp_interrupt();

        ret = output_device(fd,gpio_send_interrupt, 1, 0);
        if (ret)
        {
            GPIO_TEST_ERR("output device set to zero on gpio %d Fail!! : ret %d\n",gpio_send_interrupt, ret);
            return ret;
        }
        GPIO_TEST_INFO("output device set to zero on gpio %d ret %d\n",gpio_send_interrupt, ret);
        //usleep(1000);
    }
    else
    {
        ret = output_device(fd,gpio_send_interrupt, 1, 0);
        if (ret)
        {
            GPIO_TEST_ERR("output device set to zero on gpio %d Fail!! : ret %d\n",gpio_send_interrupt, ret);
            return ret;
        }
        GPIO_TEST_INFO("output device set to zero on gpio %d ret %d\n",gpio_send_interrupt, ret);

        wait_for_dsp_interrupt();

        ret = output_device(fd,gpio_send_interrupt, 0, 1);
        if (ret)
        {
            GPIO_TEST_ERR("output device set to one on gpio %d Fail!! : ret %d\n",gpio_send_interrupt, ret);
            return ret;
        }
        GPIO_TEST_INFO("output device set to one on gpio %d ret %d\n",gpio_send_interrupt, ret);
    }
        return ret;
}

void *Playback_fn(void *vargp)
{
    struct playback_thread_params *params = (struct playback_thread_params*)vargp;
    GPIO_TEST_INFO("playback command : %s \n", params->playbackCmd);
    send_signal(&interupt_cond[2], &interupt_lock[2]);
    system(params->playbackCmd);
    return NULL;
}


int main(int argc, char *argv[])
{
    const char *device_name = "/dev/gpiochip0";
    int fd =0;
    struct playback_thread_params play_params;
    struct receiver_thread_params rec_params;
    unsigned int gpio_send_interrupt;
    unsigned int serve_edge;
    unsigned int gpio_receive_interrupt;
    unsigned int trigger_edge;
    char playbackCmd[MAX_PLAYBACK_CMD_SIZE];
    int ret;
    pthread_t thread_id, playback_thread;

    memset(&play_params, 0, sizeof(struct playback_thread_params));
    memset(&rec_params, 0, sizeof(struct receiver_thread_params));
    if (argc > 6)
    {
        gpio_send_interrupt = atoi(argv[1]);
        gpio_receive_interrupt = atoi(argv[2]);
        trigger_edge = atoi(argv[3]);
        serve_edge = atoi(argv[4]);
        gpio_test_log_lvl = gpio_test_log_lvl | atoi(argv[5]);
        memset(playbackCmd, '\0', MAX_PLAYBACK_CMD_SIZE);
        strlcpy(playbackCmd, argv[6], (strlen(argv[6]) + 1) > MAX_PLAYBACK_CMD_SIZE ? MAX_PLAYBACK_CMD_SIZE : (strlen(argv[6]) +1));
    }
    else
    {
        GPIO_TEST_ERR("command: gpiotest <gpio>");
        return -1;
    }
    GPIO_TEST_DBG("gpio_send_interrupt : %d , gpio_receive_interrupt : %d, serve_edge :%d , trigger_edge :%d, playback cmd: %s !!\n", gpio_send_interrupt, gpio_receive_interrupt, serve_edge, trigger_edge, argv[6]);

    // serve_edge : GPIOEVENT_REQUEST_RISING_EDGE/GPIOEVENT_REQUEST_FALLING_EDGE
    if((serve_edge < 1 && serve_edge > 3 ) || (trigger_edge < 1 && trigger_edge > 2 ))
    {
        GPIO_TEST_ERR("Bad input wrong configuration of serve_edge and trigger_edge");
    }
    fd = open_device(device_name);
    rec_params.fd = fd;
    rec_params.serve_edge = serve_edge;
    rec_params.gpio_receive_interrupt = gpio_receive_interrupt;

    strlcpy(play_params.playbackCmd, playbackCmd, (strlen(playbackCmd) + 1) > MAX_PLAYBACK_CMD_SIZE ? MAX_PLAYBACK_CMD_SIZE : (strlen(playbackCmd) +1));


    //interrupt receiver thread crated for receiving interrupt.
    pthread_create(&thread_id, NULL, interrupt_receiver, &rec_params);
    wait_for_signal(&interupt_cond[1], &interupt_lock[1]);

    //playback thread creation
    pthread_create(&playback_thread, NULL, Playback_fn, &play_params);
    wait_for_signal(&interupt_cond[2], &interupt_lock[2]);

    usleep(DELAY_AFTER_PLAYBACK_START);

    pthread_mutex_lock(&interupt_lock[0]);

    //setting the gpio to default value before interrupting dsp
    if(trigger_edge == GPIOEVENT_REQUEST_RISING_EDGE)
    {
        output_device(fd, gpio_send_interrupt, 0, 0);
    }
    else
    {
        output_device(fd, gpio_send_interrupt, 1, 1);
    }

    while (fd > 0)
    {
        ret = interrupt_dsp_and_wait(fd, gpio_send_interrupt, trigger_edge);
        if (ret)
        {
            GPIO_TEST_ERR("sending interrupt on gpio %d Fail!! : ret %d\n",gpio_send_interrupt, ret);
        }
    }
    pthread_mutex_unlock(&interupt_lock[0]);

    pthread_join(thread_id, NULL);
    pthread_join(playback_thread, NULL);

    return 0;
}
