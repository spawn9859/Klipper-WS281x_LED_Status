#!/usr/bin/python3 -u
# pylint: disable=C0326
'''
Script to take info from Klipper and light up WS281x LED strip based on current status
'''

import sys
import json
import math
import time
import requests
from rpi_ws281x import Adafruit_NeoPixel

LED_COUNT      = 10      # Number of LED pixels.
LED_PIN        = 10      # GPIO pin connected to the pixels (18 uses PWM, 10 uses SPI).
LED_FREQ_HZ    = 800000  # LED signal frequency in hertz (usually 800khz)
LED_DMA        = 10      # DMA channel to use for generating signal (try 10)
LED_BRIGHTNESS = 255     # Set to 0 for darkest and 255 for brightest
LED_INVERT     = False   # True to invert the signal (when using NPN transistor level shift)
LED_CHANNEL    = 0       # set to '1' for GPIOs 13, 19, 41, 45 or 53

## Colors to use                 R    G    B
BED_HEATING_BASE_COLOR        = (0  , 0  , 255)
BED_HEATING_PROGRESS_COLOR    = (238, 130, 238)
HOTEND_HEATING_BASE_COLOR     = (238, 130, 238)
HOTEND_HEATING_PROGRESS_COLOR = (255, 0  , 0  )
PRINT_BASE_COLOR              = (0  , 0  , 0  )
PRINT_PROGRESS_COLOR          = (0  , 255, 0  )
STANDBY_COLOR                 = (255, 0  , 255)
COMPLETE_COLOR                = (235, 227, 9  )
PAUSED_COLOR                  = (0  , 255, 0  )
ERROR_COLOR                   = (255, 0  , 0  )

## Reverses the direction of progress and chase
REVERSE = False

SHUTDOWN_WHEN_COMPLETE = True
BED_TEMP_FOR_OFF       = 50
HOTEND_TEMP_FOR_OFF    = 40

## Time in seconds before LEDs turn off when on same state
IDLE_TIMEOUT = 300


def printer_state():
    ''' Get printer status '''
    url = 'http://localhost:7125/printer/objects/query?print_stats'
    ret = requests.get(url)
    try:
        return json.loads(ret.text)['result']['status']['print_stats']['state']
    except KeyError:
        return False


def power_status():
    url = 'http://localhost:7125/machine/device_power/devices?device=printer'
    ret = requests.get(url)
    return json.loads(ret.text)['result']['devices'][0]['status']



def printing_stats(base_temps):
    ''' Get stats for bed heater, hotend, and printing percent '''
    url = f'http://localhost:7125/printer/objects/query?heater_bed&extruder&display_status'
    data = json.loads(requests.get(url).text)

    bed_temp = data['result']['status']['heater_bed']['temperature']
    bed_target = data['result']['status']['heater_bed']['target']
    bed_base_temp = base_temps[0] if base_temps else 0

    extruder_temp = data['result']['status']['extruder']['temperature']
    extruder_target = data['result']['status']['extruder']['target']
    extruder_base_temp = base_temps[1] if base_temps else 0

    return {
        'bed': {
            'temp': float(bed_temp),
            'heating_percent': heating_percent(bed_temp, bed_target, bed_base_temp),
            'power_percent': round(data['result']['status']['heater_bed']['power'] * 100)
        },
        'extruder': {
            'temp': float(extruder_temp),
            'heating_percent': heating_percent(extruder_temp, extruder_target, extruder_base_temp),
            'power_percent': round(data['result']['status']['extruder']['power'] * 100)
        },
        'printing': {
            'done_percent': round(data['result']['status']['display_status']['progress'] * 100)
        }
    }


def heating_percent(temp, target, base_temp):
    ''' Get heating percent for given component '''
    if target == 0.0:
        return 0
    return math.floor(((temp - base_temp) * 100) / (target - base_temp))


def power_off():
    ''' Power off the printer '''
    url = 'http://localhost:7125/machine/device_power/off?printer'
    return requests.post(url).text


def average(num_a, num_b):
    ''' Average two given numbers '''
    return round((num_a + num_b) / 2)


def mix_color(colour1, colour2, percent_of_c1=None):
    ''' Mix two colors to a given percentage '''
    if percent_of_c1:
        colour1 = [x * percent_of_c1 for x in colour1]
        percent_of_c2 = 1 - percent_of_c1
        colour2 = [x * percent_of_c2 for x in colour2]

    col_r = average(colour1[0], colour2[0])
    col_g = average(colour1[1], colour2[1])
    col_b = average(colour1[2], colour2[2])
    return tuple([int(col_r), int(col_g), int(col_b)])


def color_brightness_correction(color, brightness):
    ''' Adjust given color to set brightness '''
    brightness_correction = brightness / 255
    return (
        int(color[0] * brightness_correction),
        int(color[1] * brightness_correction),
        int(color[2] * brightness_correction)
    )


def static_color(strip, color, brightness=LED_BRIGHTNESS):
    for pixel in range(strip.numPixels()):
        strip.setPixelColorRGB(pixel, *color_brightness_correction(color, brightness))
    strip.show()


def progress(strip, percent, base_color, progress_color):
    ''' Set LED strip to given progress with base and progress colors '''
    strip.setBrightness(LED_BRIGHTNESS)
    num_pixels = strip.numPixels()
    upper_bar = (percent / 100) * num_pixels
    upper_remainder, upper_whole = math.modf(upper_bar)
    pixels_remaining = num_pixels

    for i in range(int(upper_whole)):
        pixel = ((num_pixels - 1) - i) if REVERSE else i
        strip.setPixelColorRGB(pixel, *color_brightness_correction(progress_color, LED_BRIGHTNESS))
        pixels_remaining -= 1

    if upper_remainder > 0.0:
        tween_color = mix_color(progress_color, base_color, upper_remainder)
        pixel = ((num_pixels - int(upper_whole)) - 1) if REVERSE else int(upper_whole)
        strip.setPixelColorRGB(pixel, *color_brightness_correction(tween_color, LED_BRIGHTNESS))
        pixels_remaining -= 1

    for i in range(pixels_remaining):
        pixel = (
            ((pixels_remaining - 1) - i)
            if REVERSE
            else ((num_pixels - pixels_remaining) + i)
        )
        strip.setPixelColorRGB(pixel, *color_brightness_correction(base_color, LED_BRIGHTNESS))

    strip.show()


def fade(strip, color, speed='slow'):
    ''' Fade entire strip with given color and speed '''
    speed = 0.05 if speed == 'slow' else 0.005
    for pixel in range(strip.numPixels()):
        strip.setPixelColorRGB(pixel, *color)
    strip.show()

    for i in range(LED_BRIGHTNESS):
        strip.setBrightness(i)
        strip.show()
        time.sleep(speed)

    time.sleep(speed * 5)

    for i in range(LED_BRIGHTNESS, -1, -1):
        strip.setBrightness(i)
        strip.show()
        time.sleep(speed)


def chase(strip, color, reverse=False):
    ''' Light one LED from one ond of the strip to the other, optionally reversed '''
    strip.setBrightness(LED_BRIGHTNESS)
    for i in reversed(range(strip.numPixels()+1)) if reverse else range(strip.numPixels()+1):
        for pixel in range(strip.numPixels()):
#            print(i, pixel)
            if i == pixel:
                strip.setPixelColorRGB(pixel, *color_brightness_correction(color, LED_BRIGHTNESS))
            else:
                strip.setPixelColorRGB(pixel, 0, 0, 0)
            strip.show()
            time.sleep(0.01)
    if reverse:
        clear_strip(strip)


def bounce(strip, color):
    ''' Bounce one LED back and forth '''
    chase(strip, color, False)
    chase(strip, color, True)


def chase_ghost(strip, color, reverse=False):
    ''' Light one LED from one ond of the strip to the other, optionally reversed '''
    strip.setBrightness(LED_BRIGHTNESS)
    for i in reversed(range(strip.numPixels()+5)) if reverse else range(strip.numPixels()+5):
        for pixel in range(strip.numPixels()):
            if i == pixel:
                brightness = LED_BRIGHTNESS/4 if reverse else LED_BRIGHTNESS
                strip.setPixelColorRGB(pixel, *color_brightness_correction(color, brightness))
            elif i - 1 == pixel:
                brightness = (LED_BRIGHTNESS/4)*2 if reverse else (LED_BRIGHTNESS/4)*3
                strip.setPixelColorRGB(pixel, *color_brightness_correction(color, brightness))
            elif i - 2 == pixel:
                brightness = (LED_BRIGHTNESS/4)*3 if reverse else (LED_BRIGHTNESS/4)*2
                strip.setPixelColorRGB(pixel, *color_brightness_correction(color, brightness))
            elif i - 3 == pixel:
                brightness = LED_BRIGHTNESS if reverse else LED_BRIGHTNESS/4
                strip.setPixelColorRGB(pixel, *color_brightness_correction(color, brightness))
            else:
                strip.setPixelColorRGB(pixel, 0, 0, 0)
            strip.show()
            time.sleep(0.01)
    if reverse:
        clear_strip(strip)


def ghost_bounce(strip, color):
    ''' Bounce one LED back and forth '''
    chase_ghost(strip, color, False)
    chase_ghost(strip, color, True)


def clear_strip(strip):
    ''' Turn all pixels of LED strip off '''
    for i in range(strip.numPixels()):
        strip.setPixelColorRGB(i, 0, 0, 0)
    strip.show()


def run():
    ''' Do work son '''
    strip = Adafruit_NeoPixel(LED_COUNT,
                              LED_PIN,
                              LED_FREQ_HZ,
                              LED_DMA,
                              LED_INVERT,
                              LED_BRIGHTNESS,
                              LED_CHANNEL)
    strip.begin()

    shutdown_counter = 0
    idle_timer = 0
    old_state = ''
    base_temps = []
    try:
        while True:
            printer_state_ = printer_state()
            # print(printer_state_)
            if printer_state_ == 'printing':
                printing_stats_ = printing_stats(base_temps)
                printing_percent_ = printing_stats_['printing']['done_percent']
                ## Get base temperatures to make heating progress start from the bottom
                if not base_temps:
                    base_temps = [
                        printing_stats_['bed']['temp'],
                        printing_stats_['extruder']['temp']
                    ]

                if printing_percent_ < 1 and printing_stats_['bed']['heating_percent'] < 100:
                    # print(f'Bed heating: {bed_heating_percent}%')
                    progress(strip,
                             printing_stats_['bed']['heating_percent'],
                             BED_HEATING_BASE_COLOR,
                             BED_HEATING_PROGRESS_COLOR)

                if (printing_percent_ < 1 and
                    printing_stats_['extruder']['heating_percent'] < 100 and
                    printing_stats_['bed']['heating_percent'] >= 99):

                    # print(f'Extruder heating: {extruder_heating_percent}%')
                    progress(strip,
                             printing_stats_['extruder']['heating_percent'],
                             HOTEND_HEATING_BASE_COLOR,
                             HOTEND_HEATING_PROGRESS_COLOR)

                if (printing_percent_ == 0 and
                    printing_stats_['extruder']['heating_percent'] >= 100 and
                    printing_stats_['bed']['heating_percent'] >= 100):

                    clear_strip(strip)

                if 0 < printing_percent_ < 100:
                    # print(f'Print progress: {printing_percent_}%')
                    progress(strip,
                             printing_percent_,
                             PRINT_BASE_COLOR,
                             PRINT_PROGRESS_COLOR)


            if printer_state_ == 'standby' and idle_timer < IDLE_TIMEOUT:
                fade(strip, STANDBY_COLOR, 'fast')

            if printer_state_ == 'paused' and idle_timer < IDLE_TIMEOUT:
                bounce(strip, PAUSED_COLOR)

            if printer_state_ == 'error' and idle_timer < IDLE_TIMEOUT:
                fade(strip, ERROR_COLOR, 'fast')

            if printer_state_ == 'complete':
                base_temps = []
                if power_status() == 'on':
                    ghost_bounce(strip, COMPLETE_COLOR)
                    shutdown_counter += 1
                    if SHUTDOWN_WHEN_COMPLETE and shutdown_counter > 9:
                        shutdown_counter = 0
                        printing_stats_ = printing_stats(base_temps)
                        bed_temp = printing_stats_['bed']['temp']
                        extruder_temp = printing_stats_['extruder']['temp']
                        print(f'\nBed temp: {round(bed_temp, 2)}\nExtruder temp: {round(extruder_temp, 2)}\n')
                        if bed_temp < BED_TEMP_FOR_OFF and extruder_temp < HOTEND_TEMP_FOR_OFF:
                            clear_strip(strip)
                            print(power_off())

            if printer_state_ not in ['printing', 'complete'] and old_state == printer_state_:
                idle_timer += 2
                if idle_timer > IDLE_TIMEOUT:
                    clear_strip(strip)
            else:
                idle_timer = 0

            old_state = printer_state_
            time.sleep(2)

    except KeyboardInterrupt:
        clear_strip(strip)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        strip = Adafruit_NeoPixel(LED_COUNT,
                              LED_PIN,
                              LED_FREQ_HZ,
                              LED_DMA,
                              LED_INVERT,
                              LED_BRIGHTNESS,
                              LED_CHANNEL)
        strip.begin()
        color = (int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]))
        brightness = int(sys.argv[4]) if len(sys.argv) > 4 else LED_BRIGHTNESS
        static_color(strip, color, brightness)
    else:
        run()
