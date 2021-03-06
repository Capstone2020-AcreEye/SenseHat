#!/usr/bin/python
# **************************************************************************************************************
#
#    This is a Raspberry Pi project that measures weather values (temperature, humidity and pressure) using
#    the Astro Pi Sense HAT then uploads the data to a Weather Underground weather station.
#***************************************************************************************************************

from __future__ import print_function

import datetime
import logging
import os
import sys
import time
import traceback
from urllib import urlencode

import urllib2
from sense_hat import SenseHat

from config import Config

# ============================================================================
# Constants
# ============================================================================
DEBUG_MODE = True
# specifies how often to measure values from the Sense HAT (in minutes)
MEASUREMENT_INTERVAL = 10  # minutes
# Set to False when testing the code and/or hardware
# Set to True to enable upload of weather data to Weather Underground
WEATHER_UPLOAD = True
# the weather underground URL used to upload weather data
WU_URL = 'https://weatherstation.wunderground.com/weatherstation/updateweatherstation.php'
# some string constants
SINGLE_HASH = '#'
HASHES = '############################################'

# constants used to display an up and down arrows plus bars
# modified from https://www.raspberrypi.org/learning/getting-started-with-the-sense-hat/worksheet/
# set up the colours (blue, red, empty)
b = [0, 0, 255]  # blue
r = [255, 0, 0]  # red
e = [0, 0, 0]  # empty
# create images for up and down arrows
arrow_up = [
    e, e, e, r, r, e, e, e,
    e, e, r, r, r, r, e, e,
    e, r, e, r, r, e, r, e,
    r, e, e, r, r, e, e, r,
    e, e, e, r, r, e, e, e,
    e, e, e, r, r, e, e, e,
    e, e, e, r, r, e, e, e,
    e, e, e, r, r, e, e, e
]
arrow_down = [
    e, e, e, b, b, e, e, e,
    e, e, e, b, b, e, e, e,
    e, e, e, b, b, e, e, e,
    e, e, e, b, b, e, e, e,
    b, e, e, b, b, e, e, b,
    e, b, e, b, b, e, b, e,
    e, e, b, b, b, b, e, e,
    e, e, e, b, b, e, e, e
]
bars = [
    e, e, e, e, e, e, e, e,
    e, e, e, e, e, e, e, e,
    r, r, r, r, r, r, r, r,
    r, r, r, r, r, r, r, r,
    b, b, b, b, b, b, b, b,
    b, b, b, b, b, b, b, b,
    e, e, e, e, e, e, e, e,
    e, e, e, e, e, e, e, e
]

# Initialize some global variables
# last_temp = 0
wu_station_id = ''
wu_station_key = ''
sense = None


def c_to_f(input_temp):
    # convert input_temp from Celsius to Fahrenheit
    return (input_temp * 1.8) + 32


def get_cpu_temp():
    # 'borrowed' from https://www.raspberrypi.org/forums/viewtopic.php?f=104&t=111457
    # executes a command at the OS to pull in the CPU temperature
    res = os.popen('vcgencmd measure_temp').readline()
    return float(res.replace("temp=", "").replace("'C\n", ""))


# use moving average to smooth readings
def get_smooth(x):
    # do we have the t object?
    if not hasattr(get_smooth, 't'):
        # then create it
        get_smooth.t = [x, x, x]
    # manage the rolling previous values
    get_smooth.t[2] = get_smooth.t[1]
    get_smooth.t[1] = get_smooth.t[0]
    get_smooth.t[0] = x
    # average the three last temperatures
    xs = (get_smooth.t[0] + get_smooth.t[1] + get_smooth.t[2]) / 3
    return xs


def get_temp():
    # ====================================================================
    # Unfortunately, getting an accurate temperature reading from the
    # Sense HAT is improbable, see here:
    # https://www.raspberrypi.org/forums/viewtopic.php?f=104&t=111457
    # so we'll have to do some approximation of the actual temp
    # taking CPU temp into account. The Pi foundation recommended
    # using the following:
    # http://yaab-arduino.blogspot.co.uk/2016/08/accurate-temperature-reading-sensehat.html
    # ====================================================================
    # First, get temp readings from both sensors
    t1 = sense.get_temperature_from_humidity()
    t2 = sense.get_temperature_from_pressure()
    # t becomes the average of the temperatures from both sensors
    t = (t1 + t2) / 2
    # Now, grab the CPU temperature
    t_cpu = get_cpu_temp()
    # Calculate the 'real' temperature compensating for CPU heating
    t_corr = t - ((t_cpu - t) / 1.5)
    # Finally, average out that value across the last three readings
    t_corr = get_smooth(t_corr)
    # convoluted, right?
    # Return the calculated temperature
    return t_corr


def processing_loop():
    global sense, wu_station_id, wu_station_key

    # get the current temp to use when checking the previous measurement
    last_temp = round(c_to_f(get_temp()), 1)
    logging.info('Initial temperature reading: {}'.format(last_temp))

    # initialize the lastMinute variable to the current time to start
    last_minute = datetime.datetime.now().minute
    # on init, just use the previous minute as lastMinute
    last_minute -= 1
    if last_minute == 0:
        last_minute = 59
    logging.debug('Last Minute: {}'.format(last_minute))

    # infinite loop to continuously check weather values
    while 1:
        # The temp measurement smoothing algorithm's accuracy is based
        # on frequent measurements, so we'll take measurements every 5 seconds
        # but only upload on measurement_interval
        current_second = datetime.datetime.now().second
        # logging.debug('Current Second: {}'.format(current_second))
        # are we at the top of the minute or at a 5 second interval?
        if (current_second == 0) or ((current_second % 5) == 0):
            # ========================================================
            # read values from the Sense HAT
            # ========================================================
            # Calculate the temperature. The get_temp function 'adjusts' the recorded temperature adjusted for the
            # current processor temp in order to accommodate any temperature leakage from the processor to
            # the Sense HAT's sensor. This happens when the Sense HAT is mounted on the Pi in a case.
            # If you've mounted the Sense HAT outside of the Raspberry Pi case, then you don't need that
            # calculation. So, when the Sense HAT is external, replace the following line (comment it out  with a #)
            calc_temp = get_temp()
            # with the following line (uncomment it, remove the # at the line start)
            # calc_temp = sense.get_temperature_from_pressure()
            # or the following line (each will work)
            # calc_temp = sense.get_temperature_from_humidity()
            # ========================================================
            # At this point, we should have an accurate temperature, so lets use the recorded (or calculated)
            # temp for our purposes
            temp_c = round(calc_temp, 1)
            temp_f = round(c_to_f(calc_temp), 1)
            humidity = round(sense.get_humidity(), 0)
            # convert pressure from millibars to inHg before posting
            pressure = round(sense.get_pressure() * 0.0295300, 1)
            logging.info("Temp: %sF (%sC), Pressure: %s inHg, Humidity: %s%%" % (temp_f, temp_c, pressure, humidity))

            # get the current minute
            current_minute = datetime.datetime.now().minute
            # logging.debug('Current minute: {}'.format(current_minute))
            # is it the same minute as the last time we checked?
            # this will always be true the first time through this loop
            if current_minute != last_minute:
                # reset last_minute to the current_minute
                last_minute = current_minute
                # is minute zero, or divisible by 10?
                # we're only going to use measurements every MEASUREMENT_INTERVAL minutes
                if (current_minute == 0) or ((current_minute % MEASUREMENT_INTERVAL) == 0):
                    # get the reading timestamp
                    now = datetime.datetime.now()
                    logging.info("%d minute mark (%d @ %s)" % (MEASUREMENT_INTERVAL, current_minute, str(now)))
                    # did the temperature go up or down?
                    if last_temp != temp_f:
                        if last_temp > temp_f:
                            # display a blue, down arrow
                            sense.set_pixels(arrow_down)
                        else:
                            # display a red, up arrow
                            sense.set_pixels(arrow_up)
                    else:
                        # temperature stayed the same
                        # display red and blue bars
                        sense.set_pixels(bars)
                    # set last_temp to the current temperature before we measure again
                    last_temp = temp_f

                    logging.debug('ID: {}'.format(wu_station_id))
                    logging.debug('PASSWORD: {}'.format(wu_station_key))
                    logging.debug('tempf: {}'.format(str(temp_f)))
                    logging.debug('humidity: {}'.format(str(humidity)))
                    logging.debug('baromin: {}'.format(str(pressure)))

                    # ========================================================
                    # Upload the weather data to Weather Underground
                    # ========================================================
                    # is weather upload enabled (True)?
                    if WEATHER_UPLOAD:
                        # From http://wiki.wunderground.com/index.php/PWS_-_Upload_Protocol
                        logging.info('Uploading data to Weather Underground')
                        # build a weather data object
                        weather_data = {
                            'action': 'updateraw',
                            'ID': wu_station_id,
                            'PASSWORD': wu_station_key,
                            'dateutc': "now",
                            'tempf': str(temp_f),
                            'humidity': str(humidity),
                            'baromin': str(pressure),
                        }
                        try:
                            upload_url = WU_URL + "?" + urlencode(weather_data)
                            response = urllib2.urlopen(upload_url)
                            html = response.read()
                            logging.info('Server response: {}'.format(html))
                            # best practice to close the file
                            response.close()
                        except:
                            logging.error('Exception type: {}'.format(type(e)))
                            logging.error('Error: {}'.format(sys.exc_info()[0]))
                            traceback.print_exc(file=sys.stdout)
                    else:
                        logging.info('Skipping Weather Underground upload')

        # wait a second then check again
        # You can always increase the sleep value below to check less often
        time.sleep(1)  # this should never happen since the above is an infinite loop


def main():
    global sense, wu_station_id, wu_station_key

    # Setup the basic console logger
    format_str = '%(asctime)s %(levelname)s %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    logging.basicConfig(format=format_str, level=logging.INFO, datefmt=date_format)
    # When debugging, uncomment the following two lines
    # logger = logging.getLogger()
    # logger.setLevel(logging.DEBUG)

    print('\n' + HASHES)
    print(SINGLE_HASH, 'Pi Weather Station (Sense HAT)          ', SINGLE_HASH)
    print(SINGLE_HASH, '', SINGLE_HASH)
    print(HASHES)

    # make sure we don't have a MEASUREMENT_INTERVAL > 60
    if (MEASUREMENT_INTERVAL is None) or (MEASUREMENT_INTERVAL > 60):
        logging.info("The application's 'MEASUREMENT_INTERVAL' cannot be empty or greater than 60")
        sys.exit(1)

    # ============================================================================
    #  Read Weather Underground Configuration
    # ============================================================================
    logging.info('Initializing Weather Underground configuration')
    wu_station_id = Config.STATION_ID
    wu_station_key = Config.STATION_KEY
    if (wu_station_id is None) or (wu_station_key is None):
        logging.info('Missing values from the Weather Underground configuration file')
        sys.exit(1)

    # we made it this far, so it must have worked...
    logging.info('Successfully read Weather Underground configuration')
    logging.info('Station ID: {}'.format(wu_station_id))
    logging.debug('Station key: {}'.format(wu_station_key))

    # ============================================================================
    # initialize the Sense HAT object
    # ============================================================================
    try:
        logging.info('Initializing the Sense HAT client')
        sense = SenseHat()
        # sense.set_rotation(180)
        # then write some text to the Sense HAT
        sense.show_message('Init', text_colour=[255, 255, 0], back_colour=[0, 0, 255])
        # clear the screen
        sense.clear()
    except:
        logging.info('Unable to initialize the Sense HAT library')
        logging.error('Exception type: {}'.format(type(e)))
        logging.error('Error: {}'.format(sys.exc_info()[0]))
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)

    logging.info('Initialization complete!')
    processing_loop()


# Now see what we're supposed to do next
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting application\n")
        sys.exit(0)
