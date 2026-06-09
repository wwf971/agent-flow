from __future__ import annotations

from contextlib import closing

from psycopg import connect, sql
from psycopg.rows import dict_row

from config import get_dir_base, load_database_config

database_config = load_database_config()


def get_runtime_db_config():
    return {
        "host": database_config["host"],
        "port": database_config["port"],
        "dbname": database_config["databaseName"],
        "user": database_config["username"],
        "password": database_config["password"],
    }


def ensure_database_exists():
    admin_config = {
        "host": database_config["host"],
        "port": database_config["port"],
        "dbname": "postgres",
        "user": database_config["username"],
        "password": database_config["password"],
    }
    database_name = str(database_config["databaseName"])
    with connect(**admin_config, autocommit=True) as db:
        with closing(db.cursor()) as cursor:
            cursor.execute("select 1 from pg_database where datname = %s", (database_name,))
            if cursor.fetchone():
                return
            cursor.execute(sql.SQL("create database {}").format(sql.Identifier(database_name)))


def run_in_transaction(action):
    db = None
    try:
        db = connect(**get_runtime_db_config())
        db.autocommit = False
        result = action(db)
        db.commit()
        return result
    except Exception:
        if db is not None:
            db.rollback()
        raise
    finally:
        if db is not None:
            db.close()


def run_sql_script_file(file_name: str):
    sql_path = get_dir_base() / "database" / file_name
    sql_text = sql_path.read_text(encoding="utf-8")

    def action(db):
        with closing(db.cursor()) as cursor:
            cursor.execute(sql_text)
        return True

    return run_in_transaction(action)


def ensure_schema_exists():
    def action(db):
        with closing(db.cursor()) as cursor:
            cursor.execute(
                """
                select table_name
                from information_schema.tables
                where table_schema = current_schema()
                  and table_name in ('conversation', 'event')
                """
            )
            table_name_set = {str(row[0]) for row in (cursor.fetchall() or [])}
        return table_name_set

    table_name_set = run_in_transaction(action)
    if "conversation" in table_name_set and "event" in table_name_set:
        return {"isSchemaInitialized": True, "isSchemaCreated": False}
    run_sql_script_file("init_table.sql")
    return {"isSchemaInitialized": True, "isSchemaCreated": True}


def reinit_database():
    ensure_database_exists()
    run_sql_script_file("init_table.sql")
    return {"isReinitialized": True}


def row_to_dict(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    return dict(row)


def dict_cursor(db):
    return db.cursor(row_factory=dict_row)
