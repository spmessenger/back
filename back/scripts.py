import os


def init_tables():
    os.environ['DB_TYPE'] = 'postgresql'
    from db.misc.tables import create_tables
    create_tables()
