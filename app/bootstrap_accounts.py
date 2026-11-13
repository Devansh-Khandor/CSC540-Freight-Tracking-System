
from getpass import getpass

from app.db import get_connection
from werkzeug.security import generate_password_hash

PASSWORD_MARKER = "BOOTSTRAP_REQUIRED"
PASSWORD_METHOD = "scrypt:32768:8:1"

EXPECTED_ACCOUNTS = {
    1: "CARRIER",
    2: "CARRIER",
    3: "CARRIER",
    4: "SHIPPER",
    5: "SHIPPER",
    6: "SHIPPER",
    7: "SHIPPER",
    8: "VIEWER",
}


def main():
    password = getpass("Enter the shared demo account password: ")
    confirmation = getpass("Confirm password: ")

    if not password or password != confirmation:
        raise ValueError("Passwords are empty or do not match.")

    connection = get_connection()
    cursor = connection.cursor()

    try:
        # Verify all eight accounts before making changes.
        for account_id, expected_role in EXPECTED_ACCOUNTS.items():
            cursor.execute(
                """
                SELECT role, password
                FROM account
                WHERE account_id = %s
                """,
                (account_id,),
            )

            row = cursor.fetchone()

            if row is None:
                raise RuntimeError(
                    f"Account {account_id} is missing."
                )

            role, stored_password = row

            if role != expected_role:
                raise RuntimeError(
                    f"Unexpected role for account {account_id}."
                )

            if stored_password != PASSWORD_MARKER:
                raise RuntimeError(
                    f"Account {account_id} is not awaiting initialization. "
                    "No passwords were changed."
                )

        # Generate a separate salted hash for every account.
        for account_id in EXPECTED_ACCOUNTS:
            password_hash = generate_password_hash(
                password,
                method=PASSWORD_METHOD,
            )

            cursor.execute(
                """
                UPDATE account
                SET password = %s
                WHERE account_id = %s
                  AND password = %s
                """,
                (password_hash, account_id, PASSWORD_MARKER),
            )

            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"Failed to initialize account {account_id}."
                )

        connection.commit()
        print("Successfully initialized all 8 account passwords.")

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    main()
