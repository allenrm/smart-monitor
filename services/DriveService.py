import logging

LOGGER = logging.getLogger()

def get_service(connection):
    return DriveService(connection)

class DriveService():
    def __init__(self, connection):
        self.connection = connection

    def get_drive(self, uuid, variables):
        result = self.connection.execute(self.__build_select(uuid, variables))
        return result.first()

    def add_drive(self, uuid, name, group, variables):
        self.connection.execute(self.__build_insert(uuid, name, group, variables))

    def update_drive(self, uuid, variables):
        self.connection.execute(self.__build_update(uuid, variables))

    def create_table(self):
        self.connection.execute(self.__build_create())

    def add_table_column(self, column):
        self.connection.execute(self.__add_column(column))
        self.connection.execute(self.__initialize_column(column))


    def __build_create(self):
        return "CREATE TABLE drives (id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT, name TEXT, code_group TEXT, last_updated TEXT)"

    def __add_column(self, column):
        return "ALTER TABLE drives ADD COLUMN " + column + " INTEGER"

    def __initialize_column(self, column):
        return "UPDATE drives SET " + column + " = 0"

    def __build_select(self, uuid, variables):
        statement = "SELECT "

        for i, key in enumerate(variables):
            statement += key + (", " if i < len(variables) - 1 else "")

        statement += " FROM drives WHERE uuid = '{}'".format(uuid)

        return statement

    def __build_update(self, uuid, variables):
        statement = "UPDATE drives SET last_updated = date('now'), "

        column = "{} = {}"

        for i, key in enumerate(variables):
            statement += column.format(key, str(variables[key])) + (", " if i < len(variables) - 1 else "")

        statement += " WHERE uuid = '{}'".format(uuid)

        return statement

    def __build_insert(self, uuid, name, group, variables):
        statement = "INSERT INTO drives (uuid, name, code_group, last_updated, "
        values = "VALUES ('{}', '{}', '{}', date('now'), ".format(uuid, name, group)
            
        for i, key in enumerate(variables):
            statement += key + (", " if i < len(variables) - 1 else ") ")
            values += str(variables[key]) + (", " if i < len(variables) - 1 else ")")
    
        statement += values

        return statement