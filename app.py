import sqlite3

ADMIN_PASSWORD = "admin123"


def get_user(db, username):
    cur = db.cursor()
    cur.execute("SELECT * FROM users WHERE name = '%s'" % username)
    return cur.fetchone()


def average(numbers):
    return sum(numbers) / len(numbers)


def read_config():
    f = open("config.json")
    return f.read()


def is_admin(password):
    if password == ADMIN_PASSWORD:
        return True
