from __future__ import annotations

import secrets
import sqlite3
import string
from collections.abc import Iterable


CDK_ALPHABET = string.ascii_uppercase + string.digits


def normalize_cdk(code: str) -> str:
    return code.strip().upper().replace(" ", "")


class CdkRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def generate_batch(self, *, count: int, batch_name: str) -> list[str]:
        if count < 1 or count > 1000:
            raise ValueError("生成数量必须在 1 到 1000 之间")

        codes: list[str] = []
        while len(codes) < count:
            code = self._new_code()
            try:
                self.connection.execute(
                    "insert into cdks (code, batch_name) values (?, ?)",
                    (code, batch_name.strip()),
                )
            except sqlite3.IntegrityError:
                continue
            codes.append(code)
        self.connection.commit()
        return codes

    def get_available_by_code(self, code: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "select * from cdks where code = ? and status = 'available'",
            (normalize_cdk(code),),
        ).fetchone()

    def get_by_code(self, code: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "select * from cdks where code = ?",
            (normalize_cdk(code),),
        ).fetchone()

    def mark_used(self, cdk_id: int, *, order_id: int) -> None:
        cursor = self.connection.execute(
            """
            update cdks
               set status = 'used',
                   redeemed_at = current_timestamp,
                   order_id = ?
             where id = ?
               and status = 'available'
            """,
            (order_id, cdk_id),
        )
        if cursor.rowcount != 1:
            raise sqlite3.IntegrityError("CDK 已被使用或不可用")

    def release(self, cdk_id: int) -> None:
        self.connection.execute(
            """
            update cdks
               set status = 'available',
                   redeemed_at = null,
                   order_id = null
             where id = ?
               and status = 'used'
            """,
            (cdk_id,),
        )
        self.connection.commit()

    def revoke(self, cdk_id: int) -> None:
        self.connection.execute(
            """
            update cdks
               set status = 'revoked',
                   revoked_at = current_timestamp
             where id = ?
               and status = 'available'
            """,
            (cdk_id,),
        )
        self.connection.commit()

    def list_recent(self, *, limit: int = 100, status: str | None = None) -> list[sqlite3.Row]:
        params: list[object] = []
        where = ""
        if status:
            where = "where status = ?"
            params.append(status)
        params.append(limit)
        return list(
            self.connection.execute(
                f"select * from cdks {where} order by id desc limit ?",
                params,
            )
        )

    def count_by_status(self) -> dict[str, int]:
        rows = self.connection.execute(
            "select status, count(*) as total from cdks group by status"
        ).fetchall()
        counts = {"available": 0, "used": 0, "revoked": 0}
        counts.update({row["status"]: row["total"] for row in rows})
        return counts

    def export_available_codes(self) -> Iterable[str]:
        rows = self.connection.execute(
            "select code from cdks where status = 'available' order by id"
        )
        for row in rows:
            yield row["code"]

    @staticmethod
    def _new_code() -> str:
        chunks = [
            "".join(secrets.choice(CDK_ALPHABET) for _ in range(4))
            for _ in range(4)
        ]
        return "CDK-" + "-".join(chunks)


class OrderRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def create_pending(
        self,
        *,
        cdk_id: int,
        requested_number: str,
        expires_at: str,
    ) -> sqlite3.Row:
        cursor = self.connection.execute(
            """
            insert into orders (cdk_id, requested_number, status, expires_at)
            values (?, ?, 'pending_api', ?)
            """,
            (cdk_id, requested_number, expires_at),
        )
        return self.get(cursor.lastrowid)

    def attach_platform_order(
        self,
        order_id: int,
        *,
        platform_order_id: str,
        phone: str,
    ) -> sqlite3.Row:
        self.connection.execute(
            """
            update orders
               set platform_order_id = ?,
                   phone = ?,
                   status = 'waiting_sms',
                   updated_at = current_timestamp
             where id = ?
            """,
            (platform_order_id, phone, order_id),
        )
        self.connection.commit()
        return self.get(order_id)

    def mark_completed(self, order_id: int, *, sms_code: str) -> sqlite3.Row:
        self.connection.execute(
            """
            update orders
               set sms_code = ?,
                   status = 'completed',
                   error_message = null,
                   updated_at = current_timestamp
             where id = ?
            """,
            (sms_code, order_id),
        )
        self.connection.commit()
        return self.get(order_id)

    def mark_manual_review(self, order_id: int, *, error_message: str) -> sqlite3.Row:
        self.connection.execute(
            """
            update orders
               set status = 'manual_review',
                   error_message = ?,
                   updated_at = current_timestamp
             where id = ?
            """,
            (error_message, order_id),
        )
        self.connection.commit()
        return self.get(order_id)

    def mark_failed(self, order_id: int, *, error_message: str) -> sqlite3.Row:
        self.connection.execute(
            """
            update orders
               set status = 'failed',
                   error_message = ?,
                   updated_at = current_timestamp
             where id = ?
            """,
            (error_message, order_id),
        )
        self.connection.commit()
        return self.get(order_id)

    def get(self, order_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "select * from orders where id = ?",
            (order_id,),
        ).fetchone()

    def list_recent(self, *, limit: int = 100) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "select * from orders order by id desc limit ?",
                (limit,),
            )
        )

    def count_by_status(self) -> dict[str, int]:
        rows = self.connection.execute(
            "select status, count(*) as total from orders group by status"
        ).fetchall()
        counts = {
            "pending_api": 0,
            "waiting_sms": 0,
            "completed": 0,
            "manual_review": 0,
            "failed": 0,
        }
        counts.update({row["status"]: row["total"] for row in rows})
        return counts


class NumberAllocatorRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def allocate(self, *, prefixes: list[str], suffix_width: int = 6) -> str:
        clean_prefixes = [prefix.strip() for prefix in prefixes if prefix.strip()]
        if not clean_prefixes:
            raise RuntimeError("未配置可用号段")
        invalid_prefixes = [prefix for prefix in clean_prefixes if not prefix.isdigit()]
        if invalid_prefixes:
            raise RuntimeError("号段只能包含数字")

        row = self.connection.execute(
            "select next_index from number_allocator_state where id = 1"
        ).fetchone()
        next_index = int(row["next_index"] if row else 0)
        prefix = clean_prefixes[next_index % len(clean_prefixes)]
        candidate = self._new_random_number(prefix=prefix, suffix_width=suffix_width)

        self.connection.execute(
            "update number_allocator_state set next_index = ? where id = 1",
            (next_index + 1,),
        )
        return candidate

    def _new_random_number(self, *, prefix: str, suffix_width: int) -> str:
        lower_bound = 10 ** (suffix_width - 1)
        upper_bound = 10**suffix_width
        for _ in range(100):
            suffix_number = secrets.randbelow(upper_bound - lower_bound) + lower_bound
            candidate = prefix + str(suffix_number)
            exists = self.connection.execute(
                "select 1 from orders where requested_number = ? limit 1",
                (candidate,),
            ).fetchone()
            if exists is None:
                return candidate
        raise RuntimeError("号段号码池随机分配失败，请稍后重试")
