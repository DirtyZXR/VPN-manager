"""encrypt_awg_private_keys

Encrypts WireGuard/AmneziaWG private keys and PSKs stored in the database
using Fernet (same key as other encrypted fields).

Revision ID: b2f3a4c5d6e7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-15 11:00:00.000000

"""
import sqlalchemy as sa

from alembic import op

revision = "b2f3a4c5d6e7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def _get_cipher():
    """Return Fernet cipher using the app's encryption key."""
    from cryptography.fernet import Fernet

    from app.config import get_settings

    settings = get_settings()
    return Fernet(settings.encryption_key.encode())


def _is_encrypted(value: str, cipher) -> bool:
    """Return True if the value is already Fernet-encrypted."""
    try:
        cipher.decrypt(value.encode())
        return True
    except Exception:
        return False


def upgrade() -> None:
    cipher = _get_cipher()
    bind = op.get_bind()

    # -- awg_inbound_connections: private_key, psk -------------------------
    rows = bind.execute(
        sa.text("SELECT id, private_key, psk FROM awg_inbound_connections")
    ).fetchall()

    for row in rows:
        row_id, pk, psk = row[0], row[1], row[2]
        new_pk = pk
        new_psk = psk

        if pk and not _is_encrypted(pk, cipher):
            new_pk = cipher.encrypt(pk.encode()).decode()

        if psk and not _is_encrypted(psk, cipher):
            new_psk = cipher.encrypt(psk.encode()).decode()

        if new_pk != pk or new_psk != psk:
            bind.execute(
                sa.text(
                    "UPDATE awg_inbound_connections "
                    "SET private_key = :pk, psk = :psk "
                    "WHERE id = :id"
                ),
                {"pk": new_pk, "psk": new_psk, "id": row_id},
            )

    # -- awg_services: server_private_key ----------------------------------
    rows = bind.execute(
        sa.text("SELECT id, server_private_key FROM awg_services")
    ).fetchall()

    for row in rows:
        row_id, spk = row[0], row[1]

        if spk and not _is_encrypted(spk, cipher):
            new_spk = cipher.encrypt(spk.encode()).decode()
            bind.execute(
                sa.text(
                    "UPDATE awg_services "
                    "SET server_private_key = :spk "
                    "WHERE id = :id"
                ),
                {"spk": new_spk, "id": row_id},
            )


def downgrade() -> None:
    cipher = _get_cipher()
    bind = op.get_bind()

    # -- awg_inbound_connections: private_key, psk -------------------------
    rows = bind.execute(
        sa.text("SELECT id, private_key, psk FROM awg_inbound_connections")
    ).fetchall()

    for row in rows:
        row_id, pk, psk = row[0], row[1], row[2]
        new_pk = pk
        new_psk = psk

        if pk and _is_encrypted(pk, cipher):
            new_pk = cipher.decrypt(pk.encode()).decode()

        if psk and _is_encrypted(psk, cipher):
            new_psk = cipher.decrypt(psk.encode()).decode()

        if new_pk != pk or new_psk != psk:
            bind.execute(
                sa.text(
                    "UPDATE awg_inbound_connections "
                    "SET private_key = :pk, psk = :psk "
                    "WHERE id = :id"
                ),
                {"pk": new_pk, "psk": new_psk, "id": row_id},
            )

    # -- awg_services: server_private_key ----------------------------------
    rows = bind.execute(
        sa.text("SELECT id, server_private_key FROM awg_services")
    ).fetchall()

    for row in rows:
        row_id, spk = row[0], row[1]

        if spk and _is_encrypted(spk, cipher):
            new_spk = cipher.decrypt(spk.encode()).decode()
            bind.execute(
                sa.text(
                    "UPDATE awg_services "
                    "SET server_private_key = :spk "
                    "WHERE id = :id"
                ),
                {"spk": new_spk, "id": row_id},
            )
