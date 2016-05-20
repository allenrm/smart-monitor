import yaml
import logging
import logging.handlers
import traceback
import sys
import threading

from queue import Queue
from sqlalchemy import create_engine
from distutils.util import strtobool
from services.DriveService import get_service as get_drive_service
from services.MailService import get_service as get_mail_service
from threads.DriveThread import get_thread as get_drive_thread

LOGGER = logging.getLogger()
CONFIG_FILENAME = b"config.yml"
DATABASE_FILENAME = b"sqlite:///database.db"

config = None

# Set global config variable
def __load_config():
    global config
    config = yaml.load(open(CONFIG_FILENAME.decode()))

# Set global logging
def __setup_logger():
    # Add custom debug level
    logging.FINE_DEBUG = 5
    logging.addLevelName(logging.FINE_DEBUG, "FINE_DEBUG")

    # Set logging format
    log_format = logging.Formatter("%(asctime)s [%(levelname)-6.6s] %(message)s")
    if config["logging"]["format"]:
        log_format = logging.Formatter(config["logging"]["format"])

    # Create console logger
    console_logger = logging.StreamHandler(sys.stdout)
    console_logger.setFormatter(log_format)
    
    # Add console logger to root logger
    root_logger = logging.getLogger()
    level = logging.getLevelName(config["logging"]["level"].upper())
    root_logger.setLevel(level)
    root_logger.addHandler(console_logger)

    # If file logger is specified in configuration, add file logger to root logger
    if config["logging"]["file"]:
        max_log_size = min(config["logging"]["maxsize"], 0) * 1024
        file_logger = logging.handlers.RotatingFileHandler(
            config["logging"]["file"],
            maxBytes = max_log_size,
            backupCount = 9)
        file_logger.setFormatter(log_format)
        root_logger.addHandler(file_logger)

def __to_bool(value):
    return value if isinstance(value, bool) else strtobool(value)

# Main
def main():
    # Load configuration file
    try:
        __load_config()
    except:
        print("Unexpected exception while loading configuration: {}".format(CONFIG_FILENAME.decode()))
        print(traceback.format_exc())
        sys.exit(2)

    # Setup global logging
    try:
        __setup_logger()
    except:
        print("Unexpected exception while setting up logging")
        print(traceback.format_exc())
        sys.exit(2)

    # Validate configuration file
#   try:
#       validate_config()
#   except:
#       print("Unexpected exception while validating configuration: {}".format(config_filename))
#       print(traceback.format_exc())
#       sys.exit(2)

    # Run script logic
    try:
        __run()
    except Exception:
        LOGGER.exception("Unexpected exception caused failure to properly run")

def __validate_database(database):
    with database.connect() as connection:
        drive_service = get_drive_service(connection)

        # Make sure table exists
        if not database.dialect.has_table(connection, "drives"):
            drive_service.create_table()

        # Add missing columns to table
        if database.dialect.has_table(connection, "drives"):
            columns = database.dialect.get_columns(connection, "drives")

            column_names = []
            for column in columns:
                column_names.append(column["name"])

            config_names = set().union(*(d.keys() for d in config["smart"].get("attributes")))
            missing = list(config_names.difference(set(column_names)))

            for column in missing:
                drive_service.add_table_column(column)

        connection.close()

def __get_queue_size():
    queue_size = 0

    for group in config["disks"]:
        queue_size += len(config["disks"][group])

    return queue_size

def __run():
    # Loop through configurations and spawn thread for each listed disk
    messages = []
    threads = []

    lock = threading.Lock()
    engine = create_engine(DATABASE_FILENAME.decode())
    message_queue = Queue(maxsize = __get_queue_size())

    # Ensure that database has been created properly
    __validate_database(engine)

    # Process configured disks
    LOGGER.debug("Main -> Spawning threads to process disks in configuration file...")

    for group in config["disks"]:
        for disk in config["disks"][group]:
            for key, value in disk.items():
                disk[key]["name"] = key
                disk[key]["group"] = group.upper()
                thread = get_drive_thread(disk[key], config["smart"], engine, lock, message_queue)
                threads.append(thread)
                thread.start()

    # Wait for threads to exit
    for t in threads:
        t.join()

    # Send any messages that the threads put in the queue
    if not message_queue.empty():
        LOGGER.debug("Main -> Message queue not empty; sending messages to admin...")

        # Add queue items to messages array
        lock.acquire()
        while not message_queue.empty():
            messages.append(message_queue.get())
        lock.release()

        # Send messages in bulk
        mail_service = get_mail_service(config["smtp"]["hostname"], int(config["smtp"]["port"]), __to_bool(config["smtp"]["ssl"]), config["smtp"]["username"], config["smtp"]["password"])
        mail_service.bulk_message(config["email"]["sender"], config["email"]["sender"], messages)

    LOGGER.debug("Main -> Finished processing drives; now exiting...")


#################################################################################################
# Run main application
#################################################################################################
main()