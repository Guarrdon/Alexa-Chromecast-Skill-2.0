import os
import sys
import threading
import time
import logging
import logging.handlers
from datetime import datetime, timedelta
import pychromecast
from pychromecast import Chromecast
import subprocess
import requests
from enum import Enum

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class ChromecastWrapper:
    @property
    def cast(self) -> Chromecast:
        return self.__cc

    @property
    def media_controller(self):
        return self.cast.media_controller

    @property
    def name(self):
        return self.__cc.cast_info.friendly_name

    def __init__(self, cc):
        self.__cc = cc
        cc.media_controller.register_status_listener(self)
        cc.register_status_listener(self)

    def new_media_status(self, status:pychromecast.controllers.media.MediaStatus):
        pass

    def new_cast_status(self, status):
        pass

class ChromecastState:

    @property
    def count(self):
        return len(self.__chromecasts)

    def stop(self):
        self.running = False
        self.thread.join(10)

    def __set_chromecasts(self):
        with self.lock:
            self.__chromecasts = {}
            casts, browser = pychromecast.get_chromecasts()
            # Shut down discovery as we don't care about updates
            # browser.stop_discovery()
            # commented out above as it might have caused an asertion error
            for cc in casts:
                logger.info("Found %s" % cc.cast_info.friendly_name)
                cc.wait()
                self.__chromecasts[cc.cast_info.friendly_name] = ChromecastWrapper(cc)
            self.expiry = datetime.now()

    def expire_chromecasts(self):
        while self.running:
            time.sleep(1)
            refresh_period = timedelta(minutes=120)
            if (self.expiry + refresh_period) < datetime.now():
                self.__set_chromecasts()

    def __init__(self):
        self.running = True
        self.expiry = datetime.now()
        self.lock = threading.Lock()
        self.__set_chromecasts()
        self.thread = threading.Thread(target=self.expire_chromecasts)
        self.thread.start()

    def match_chromecast(self, room) -> ChromecastWrapper:
        with self.lock:
            result = next((x for x in self.__chromecasts.values() if str.lower(room.strip()) in str.lower(x.name).replace(' the ', '')), False)
            if result:
                result.cast.wait()
            return result

    def get_chromecast(self, name):
        result = self.__chromecasts[name]
        result.cast.wait()
        return result

class Skill():

    def __init__(self):
        logger.info("Finding Chromecasts...")
        self.chromecast_controller = ChromecastState()
        if self.chromecast_controller.count == 0:
            logger.info("No Chromecasts found")
            exit(1)
        logger.info("%i Chromecasts found" % self.chromecast_controller.count)

    def get_chromecast(self, name) -> ChromecastWrapper:
        return self.chromecast_controller.get_chromecast(name)

    def handle_command(self, room, command, data):
        try:
            chromecast = self.chromecast_controller.match_chromecast(room)
            if not chromecast:
                logger.warn('No Chromecast found matching: %s' % room)
                return
            func = command.replace('-','_')
            logger.info('Sending %s command to Chromecast: %s' % (func, chromecast.name))

            getattr(self, func)(data, chromecast.name)
        except Exception:
            logger.exception('Unexpected error')

    def resume(self, data, name):
        self.play(data, name)

    def play(self, data, name):
        self.get_chromecast(name).media_controller.play()
    
    def pause(self, data, name):
        cc = self.get_chromecast(name)
        cc.media_controller.pause()

    def stop(self, data, name):
        self.get_chromecast(name).cast.quit_app()

    def set_volume(self, data, name):
        volume = data['volume'] # volume as 0-10
        volume_normalized = float(volume) / 10.0 # volume as 0-1
        self.get_chromecast(name).cast.set_volume(volume_normalized)

    def play_next(self, data, name):
        #mc.queue_next() didn't work
        self.get_chromecast(name).media_controller.skip()

    def play_previous(self, data, name):
        cc = self.get_chromecast(name)
        current_id = cc.media_controller.status.content_id
        # cc.youtube_controller.play_previous(current_id)

    def restart(self, data, name):
        self.get_chromecast(name).cast.reboot()

