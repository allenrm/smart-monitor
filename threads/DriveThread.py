import subprocess
import threading
import logging

from os.path import exists as check_path_exists
from distutils.util import strtobool
from services.DriveService import get_service as get_drive_service

LOGGER = logging.getLogger()
FINE_DEBUG = 5

FAILING_NOW = 0
UPDATED_VALUE = 1
EXCEEDS_THRESHOLD = 2
REPORT = 3
DATABASE = 4
THRESHOLDS = 5

def get_thread(device, smart, database, lock, queue):
    return DriveThread(device, smart, database, lock, queue)

class DriveThread(threading.Thread):
    def __init__(self, device, smart, database, lock, queue):
        threading.Thread.__init__(self)
        self.device = device
        self.smart = smart
        self.database = database
        self.lock = lock
        self.queue = queue

    def __to_bool(self, value):
        return value if isinstance(value, bool) else strtobool(value)

    def __update_needed(self, database_attributes, report_attributes):
        # Compare report values to database
        for key in report_attributes:
            if int(report_attributes[key]) > int(database_attributes[key]):
                return True

        return False

    def __get_thresholds(self):
        # Build list of thresholds from configuration file
        thresholds = {}

        for attribute in self.smart["attributes"]:
            for key in attribute.keys():
                thresholds[key] = attribute[key]["threshold"]

        return thresholds

    def __message_needed(self, report_attributes, thresholds):
        # Compare report values to thresholds
        for key in report_attributes:
            if int(report_attributes[key]) > int(thresholds[key]):
                return True

        return False

    def __get_failing_attributes(self, report):
        report_attributes = {}

        for line in report.split("\n"):
            if (len(line.split()) > self.smart["when_failed"] + 1) and ("FAILING_NOW" in line.split()[self.smart["when_failed"]].upper()):
                key = line.split()[self.smart["attribute_name"]].lower()
                value = int(line.split()[self.smart["raw_value"]])
                report_attributes[key] = value

        return report_attributes

    def __get_watched_attributes(self, report):
        report_attributes = {}
        watch_list = set().union(*(d.keys() for d in self.smart["attributes"]))

        for line in report.split("\n"):
            if any(attribute.upper() in line.upper() for attribute in list(watch_list)):
                key = line.split()[self.smart["attribute_name"]].lower()
                value = int(line.split()[self.smart["raw_value"]])
                report_attributes[key] = value

        return report_attributes

    def __get_smart_report(self, device_location):
        command = "smartctl -A {}".format(device_location)
        output, error = subprocess.Popen(
            command.split(),
            stdout=subprocess.PIPE,
            stderr = subprocess.PIPE).communicate()
        return output.decode()

    def __get_smart_information(self, device_location):
        command = "smartctl -i {}".format(device_location)
        output, error = subprocess.Popen(
            command.split(),
            stdout=subprocess.PIPE,
            stderr = subprocess.PIPE).communicate()

        # Decode byte stream
        output = output.decode()

        # Replace serial number information with device location for safety
        formatted = ""
        for line in output.split("\n"):
            if "SERIAL NUMBER" in line.upper():
                formatted += "Device Location:  {}\n".format(device_location)
                formatted += "Mount Location:   {}\n".format(self.device["mount_point"])
            else:
                formatted += line + "\n"

        return formatted

    def __send_message(self, subject, body):
        LOGGER.log(FINE_DEBUG, "Thread {} -> Acquiring thread lock; adding message to queue...".format(self.device["name"]))
        self.lock.acquire()

        try:
            LOGGER.log(FINE_DEBUG, "Thread {} -> Subject:\n{}".format(self.device["name"], subject))
            LOGGER.log(FINE_DEBUG, "Thread {} -> \n{}".format(self.device["name"], body))
            self.queue.put({"subject" : subject, "body" : body}, timeout = 3)
        finally:
            LOGGER.log(FINE_DEBUG, "Thread {} -> Releasing thread lock...".format(self.device["name"]))
            self.lock.release()

    def __send_initial_report(self, information, report, organized_attributes):
        threshold_attributes = organized_attributes[THRESHOLDS]

        subject = "INITIAL REPORT! SMART Monitor Report: {}".format(self.device["name"])

        if len(organized_attributes[EXCEEDS_THRESHOLD]) > 0:
            subject = "WARNING! INITIAL REPORT! SMART Monitor Report: {}".format(self.device["name"])
        if len(organized_attributes[FAILING_NOW]) > 0:
            subject = "FAILING! INITIAL REPORT! SMART Monitor Report: {}".format(self.device["name"])

        body = ""
        failing_attributes = organized_attributes[FAILING_NOW]
        if len(failing_attributes) > 0:
            body += "The following attributes are currently marked as FAILING_NOW:\n"
            body += (" " * 4) + "ATTRIBUTE_NAME"
            body += (" " * (32 - len("ATTRIBUTE_NAME"))) + "CURRENT_VALUE"
            body += (" " * (20 - len("CURRENT_VALUE"))) + "CONFIGURED_THRESHOLD"
            body += "\n"

            for key in failing_attributes:
                body += (" " * 4) + str(key)
                body += (" " * (32 - len(key))) + str(failing_attributes[key])
                body += (" " * (20 - len(str(failing_attributes[key])))) + (str(threshold_attributes[key]) if key in threshold_attributes else "-")
                body += "\n"

            body += "\n\n"

        exceeded_attributes = organized_attributes[EXCEEDS_THRESHOLD]
        if len(exceeded_attributes) > 0:
            body += "The following attributes currently exceed their configured threshold:\n"
            body += (" " * 4) + "ATTRIBUTE_NAME"
            body += (" " * (32 - len("ATTRIBUTE_NAME"))) + "CURRENT_VALUE"
            body += (" " * (20 - len("CURRENT_VALUE"))) + "CONFIGURED_THRESHOLD"
            body += "\n"
        
            for key in exceeded_attributes:
                body += (" " * 4) + str(key)
                body += (" " * (32 - len(key))) + str(exceeded_attributes[key])
                body += (" " * (20 - len(str(exceeded_attributes[key])))) + (str(threshold_attributes[key]) if key in threshold_attributes else "-")
                body += "\n"

            body += "\n\n"

        report_attributes = organized_attributes[REPORT]
        if len(report_attributes) > 0:
            body += "The following attributes are being monitored and will generate a report whenever their value changes and the new value exceeds their configured threshold:\n"
            body += (" " * 4) + "ATTRIBUTE_NAME"
            body += (" " * (32 - len("ATTRIBUTE_NAME"))) + "CURRENT_VALUE"
            body += (" " * (20 - len("CURRENT_VALUE"))) + "CONFIGURED_THRESHOLD"
            body += "\n"
        
            for key in report_attributes:
                body += (" " * 4) + str(key)
                body += (" " * (32 - len(key))) + str(report_attributes[key])
                body += (" " * (20 - len(str(report_attributes[key])))) + (str(threshold_attributes[key]) if key in threshold_attributes else "-")
                body += "\n"

            body += "\n\n"

        body += "\n{}\n".format("*" * 80)
        body += information
        body += report.split("\n", 2)[2];

        self.__send_message(subject, body)

    def __send_update_report(self, information, report, organized_attributes):
        database_attributes = organized_attributes[DATABASE]
        threshold_attributes = organized_attributes[THRESHOLDS]

        subject = "WARNING! SMART Monitor Report: {}".format(self.device["name"])

        if len(organized_attributes[FAILING_NOW]) > 0:
            subject = "FAILING! SMART Monitor Report: {}".format(self.device["name"])

        body = ""
        failing_attributes = organized_attributes[FAILING_NOW]
        if len(failing_attributes) > 0:
            body += "The following attributes are currently marked as FAILING_NOW:\n"
            body += (" " * 4) + "ATTRIBUTE_NAME"
            body += (" " * (32 - len("ATTRIBUTE_NAME"))) + "CURRENT_VALUE"
            body += (" " * (20 - len("CURRENT_VALUE"))) + "PREVIOUS_VALUE"
            body += (" " * (20 - len("PREVIOUS_VALUE"))) + "CONFIGURED_THRESHOLD"
            body += "\n"

            for key in failing_attributes:
                body += (" " * 4) + str(key)
                body += (" " * (32 - len(key))) + str(failing_attributes[key])
                body += (" " * (20 - len(str(failing_attributes[key])))) + (str(database_attributes[key]) if key in database_attributes else "-")
                body += (" " * (20 - len(str(database_attributes[key])))) + (str(threshold_attributes[key]) if key in threshold_attributes else "-")
                body += "\n"

            body += "\n\n"

        updated_attributes = organized_attributes[UPDATED_VALUE]
        if len(updated_attributes) > 0:
            body += "After comparing against their previously stored value, it has been determinted that the following attributes have changed/been updated:\n"
            body += (" " * 4) + "ATTRIBUTE_NAME"
            body += (" " * (32 - len("ATTRIBUTE_NAME"))) + "CURRENT_VALUE"
            body += (" " * (20 - len("CURRENT_VALUE"))) + "PREVIOUS_VALUE"
            body += (" " * (20 - len("PREVIOUS_VALUE"))) + "CONFIGURED_THRESHOLD"
            body += "\n"

            for key in updated_attributes:
                body += (" " * 4) + str(key)
                body += (" " * (32 - len(key))) + str(updated_attributes[key])
                body += (" " * (20 - len(str(updated_attributes[key])))) + (str(database_attributes[key]) if key in database_attributes else "-")
                body += (" " * (20 - len(str(database_attributes[key])))) + (str(threshold_attributes[key]) if key in threshold_attributes else "-")
                body += "\n"

            body += "\n\n"

        exceeded_attributes = organized_attributes[EXCEEDS_THRESHOLD]
        if len(exceeded_attributes) > 0:
            body += "The following attributes currently exceed their configured threshold:\n"
            body += (" " * 4) + "ATTRIBUTE_NAME"
            body += (" " * (32 - len("ATTRIBUTE_NAME"))) + "CURRENT_VALUE"
            body += (" " * (20 - len("CURRENT_VALUE"))) + "PREVIOUS_VALUE"
            body += (" " * (20 - len("PREVIOUS_VALUE"))) + "CONFIGURED_THRESHOLD"
            body += "\n"
        
            for key in exceeded_attributes:
                body += (" " * 4) + str(key)
                body += (" " * (32 - len(key))) + str(exceeded_attributes[key])
                body += (" " * (20 - len(str(exceeded_attributes[key])))) + (str(database_attributes[key]) if key in database_attributes else "-")
                body += (" " * (20 - len(str(database_attributes[key])))) + (str(threshold_attributes[key]) if key in threshold_attributes else "-")
                body += "\n"

            body += "\n\n"

        body += "\n{}\n".format("*" * 80)
        body += information
        body += report.split("\n", 2)[2];

        self.__send_message(subject, body)

    def __send_missing_drive_report(self, device_location):
        subject = "ISSUE! Missing Drive Report: {}".format(self.device["name"])

        body = "Device could not be found using the following UUID path: {}\n\n".format(device_location)
        body += "The following list are possibly reasons this event may have occurred:\n"
        body += (" " * 4) + "~  UUID was not properly listed in configuration file. Please check the configuration file to guarantee the UUID for this device is correct.\n"
        body += (" " * 4) + "~  Device has been ejected from machine, therefore it is no longer accessibly. This may have occurred through an user manually ejecting the device or the machine no longer recognizes the device because something is wrong with either the machine or the device hardware.\n"
        body += (" " * 4) + "~  Per Python documentation, the os.path.exists() function may not have permission to execute an os.stat() call on the requested path."

        self.__send_message(subject, body)

    def __organize_attributes(self, watched_attributes, database_attributes, threshold_attributes, failing_attributes):
        updated_attributes = {}
        exceeded_attributes = {}

        for key in watched_attributes:
            if key in database_attributes and int(watched_attributes[key]) > int(database_attributes[key]):
                updated_attributes[key] = watched_attributes[key]

            if key in threshold_attributes and int(watched_attributes[key]) > int(threshold_attributes[key]):
                exceeded_attributes[key] = watched_attributes[key]

        return {FAILING_NOW : failing_attributes, UPDATED_VALUE : updated_attributes, EXCEEDS_THRESHOLD : exceeded_attributes, REPORT : watched_attributes, DATABASE : database_attributes, THRESHOLDS : threshold_attributes}

    def run(self):
        # Establish device uuid and location
        uuid = self.device["uuid"].lower()
        device_location = "/dev/disk/by-uuid/" + uuid

        # Check if device exists
        if not check_path_exists(device_location):
            LOGGER.warning("Thread {} -> Drive location cannot be found using the following path: {}; adding message to queue...".format(self.device["name"], device_location))

            # Add message to queue for later processing
            self.__send_missing_drive_report(device_location)
        else:
            # Get SMART report
            information = self.__get_smart_information(device_location)
            report = self.__get_smart_report(device_location)
            watched_attributes = self.__get_watched_attributes(report)
            failing_attributes = self.__get_failing_attributes(report)
            thresholds = self.__get_thresholds()
        
            # Process drive
            with self.database.connect() as connection:
                drive_service = get_drive_service(connection)

                # Get drive's database stats
                database_attributes = drive_service.get_drive(uuid, watched_attributes)

                # Check if entry already exists for drive in database
                if database_attributes:
                    LOGGER.debug("Thread {} -> Drive currently exists in database; checking if drive needs updating...".format(self.device["name"]))

                    # Check if update to database is needed
                    if self.__update_needed(database_attributes, watched_attributes):
                        LOGGER.debug("Thread {} -> Drive report attributes differ from database; updating database entry for drive...".format(self.device["name"]))

                        #Update database entry for drive
                        drive_service.update_drive(uuid, watched_attributes)

                        # Check if email to admin is needed
                        if self.__to_bool(self.smart["report_values"]) and self.__to_bool(self.smart["report_updated_values"]) and self.__message_needed(watched_attributes, thresholds):
                            LOGGER.debug("Thread {} -> Mail requested by admin for updated values of drive; adding message to queue...".format(self.device["name"]))

                            # Add message to queue for later processing
                            self.__send_update_report(information, report, self.__organize_attributes(watched_attributes, database_attributes, thresholds, failing_attributes))
                else:
                    LOGGER.debug("Thread {} -> Drive does not currently exist in database; adding drive to database...".format(self.device["name"]))

                    # Insert new entry for drive since it doesn't currently exist in database
                    drive_service.add_drive(uuid, self.device["name"], self.device["group"], watched_attributes)

                    # Check if email with initally values for drive is wanted
                    if self.__to_bool(self.smart["report_values"]) and self.__to_bool(self.smart["report_initial_values"]):
                        LOGGER.debug("Thread {} -> Mail requested by admin for initial values of drive; adding message to queue...".format(self.device["name"]))

                        # Add message to queue for later processing
                        self.__send_initial_report(information, report, self.__organize_attributes(watched_attributes, {}, thresholds, failing_attributes))

                # Close connection
                connection.close()
