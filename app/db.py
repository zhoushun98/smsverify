from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
create table if not exists cdks (
    id integer primary key autoincrement,
    code text not null unique,
    status text not null default 'available'
        check (status in ('available', 'used', 'revoked')),
    batch_name text not null default '',
    created_at text not null default current_timestamp,
    redeemed_at text,
    revoked_at text,
    order_id integer
);

create table if not exists orders (
    id integer primary key autoincrement,
    platform_order_id text unique,
    cdk_id integer not null references cdks(id),
    requested_number text,
    phone text,
    sms_code text,
    status text not null
        check (status in ('pending_api', 'waiting_sms', 'completed', 'manual_review', 'failed')),
    error_message text,
    created_at text not null default current_timestamp,
    updated_at text not null default current_timestamp,
    expires_at text not null
);

create index if not exists idx_cdks_status on cdks(status);
create index if not exists idx_orders_status on orders(status);
create index if not exists idx_orders_cdk_id on orders(cdk_id);

create table if not exists number_allocator_state (
    id integer primary key check (id = 1),
    next_index integer not null default 0
);

insert or ignore into number_allocator_state (id, next_index) values (1, 0);
"""


def create_connection(database_path: str) -> sqlite3.Connection:
    if database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("pragma foreign_keys = on")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    _add_column_if_missing(
        connection,
        table_name="orders",
        column_name="requested_number",
        definition="requested_number text",
    )
    connection.commit()


def _add_column_if_missing(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"pragma table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        connection.execute(f"alter table {table_name} add column {definition}")
