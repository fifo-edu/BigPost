#!/usr/bin/env python3
"""Migra os dados do protótipo antigo (SQLite, "Gestão Financeira Master")
para o schema novo do BigPost (Postgres).

Não escreve direto no Postgres — gera um arquivo .sql com os INSERTs, que
você revisa e aplica com:

    psql "$DATABASE_URL" -f migration_data.sql

Rode isso DEPOIS de aplicar as migrations (alembic upgrade head ou
scripts/schema.sql) num banco novo e vazio.

Uso:
    python3 scripts/migrate_from_sqlite.py /caminho/para/master.db > migration_data.sql
"""
import base64
import hashlib
import json
import sqlite3
import sys
from pathlib import Path


def sql_str(value) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def sql_num(value) -> str:
    if value is None:
        return "NULL"
    return str(value)


def sql_json(value: dict) -> str:
    return sql_str(json.dumps(value or {}, ensure_ascii=False))


def convert_password_hash(old_hash: str) -> str:
    """Converte 'base64(salt):base64(digest)' (protótipo antigo) para o novo
    formato 'pbkdf2_sha256$180000$salt$digest'. Mesmo algoritmo (PBKDF2-HMAC-
    SHA256, 180k iterações) e mesmos bytes de salt/digest — só muda a forma
    como é serializado — então a senha original do usuário continua válida,
    sem precisar resetar nada."""
    try:
        salt_b64, digest_b64 = old_hash.split(":")
        base64.b64decode(salt_b64)  # valida que é base64 válido
        base64.b64decode(digest_b64)
        return f"pbkdf2_sha256$180000${salt_b64}${digest_b64}"
    except Exception:
        # Formato inesperado: gera um hash novo para uma senha aleatória —
        # o usuário vai precisar redefinir a senha manualmente.
        import secrets

        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", secrets.token_hex(16).encode(), salt, 180000)
        return f"pbkdf2_sha256$180000${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def main(sqlite_path: str) -> None:
    con = sqlite3.connect(sqlite_path)
    con.row_factory = sqlite3.Row
    out = []
    out.append("-- Gerado por scripts/migrate_from_sqlite.py a partir de: " + sqlite_path)
    out.append("BEGIN;")

    # --- users ---
    out.append("\n-- users")
    for row in con.execute("select * from users"):
        new_hash = convert_password_hash(row["password_hash"])
        out.append(
            "INSERT INTO users (id, username, role, password_hash, active) VALUES "
            f"({row['id']}, {sql_str(row['username'])}, {sql_str(row['role'])}, "
            f"{sql_str(new_hash)}, {'true' if row['active'] else 'false'});"
        )

    # --- licensees ---
    out.append("\n-- licensees")
    for row in con.execute("select * from licensees"):
        out.append(
            "INSERT INTO licensees (id, legal_name, trade_name, tax_id, billing_email, billing_phone, "
            "contracted_users, reported_active_users, monthly_fee, billing_day, status, "
            "created_at, notes, created_by) VALUES ("
            f"{row['id']}, {sql_str(row['legal_name'])}, {sql_str(row['trade_name'])}, {sql_str(row['tax_id'])}, "
            f"{sql_str(row['email_billing'])}, {sql_str(row['phone_billing'])}, "
            f"{sql_num(row['contracted_users'])}, {sql_num(row['reported_active_users'])}, "
            f"{sql_num(row['monthly_fee'])}, {sql_num(row['billing_day'])}, {sql_str(row['status'])}, "
            f"{sql_str(row['created_at'])}, {sql_str(row['notes'])}, 'migracao'); "
        )
    out.append(
        "-- Endereço, contato e MCU não existiam no protótipo antigo — complete pela tela "
        "'Cadastrar Licenciado' (edição) após a migração. Credenciais do Correios Atende e "
        "usuários da agência (Master/Administrador/Financeiro/Operador de Caixa/Expedição) "
        "também são novos — cadastre pela tela 'Agência: Usuários & Correios'."
    )

    # --- licenses (mantém o token assinado original; o verificador aceita o prefixo legado FAGF1.) ---
    out.append("\n-- licenses (tokens antigos continuam válidos: mesma chave Ed25519 + prefixo legado aceito)")
    for row in con.execute("select * from licenses"):
        out.append(
            "INSERT INTO licenses (id, licensee_id, license_code, license_uid, expires_at, "
            "max_users, status, created_at, created_by) VALUES ("
            f"{row['id']}, {row['licensee_id']}, "
            f"{sql_str(row['license_code'])}, {sql_str(row['license_uid'])}, {sql_str(row['expires_at'])}, "
            f"{sql_num(row['max_users'])}, {sql_str(row['status'])}, {sql_str(row['created_at'])}, "
            f"{sql_str(row['created_by'])});"
        )

    # --- charges ---
    out.append("\n-- charges")
    for row in con.execute("select * from charges"):
        out.append(
            "INSERT INTO charges (id, licensee_id, reference_month, due_date, amount, status, paid_at, created_at) "
            f"VALUES ({row['id']}, {row['licensee_id']}, {sql_str(row['reference_month'])}, "
            f"{sql_str(row['due_date'])}, {sql_num(row['amount'])}, {sql_str(row['status'])}, "
            f"{sql_str(row['paid_at'])}, {sql_str(row['created_at'])});"
        )

    # --- bank_config (singleton) ---
    out.append("\n-- bank_config")
    bc = con.execute("select * from bank_config where id=1").fetchone()
    if bc:
        out.append(
            "UPDATE bank_config SET bank_name={}, agreement={}, wallet={}, agency={}, account_no={}, "
            "account_digit={}, cnab_layout={}, beneficiary_name={}, beneficiary_tax_id={}, updated_at={} "
            "WHERE id=1;".format(
                sql_str(bc["bank_name"]), sql_str(bc["agreement"]), sql_str(bc["wallet"]), sql_str(bc["agency"]),
                sql_str(bc["account_no"]), sql_str(bc["account_digit"]), sql_str(bc["cnab_layout"]),
                sql_str(bc["beneficiary_name"]), sql_str(bc["beneficiary_tax_id"]), sql_str(bc["updated_at"]),
            )
        )

    # --- bank_imports / bank_entries / remittances ---
    out.append("\n-- bank_imports")
    for row in con.execute("select * from bank_imports"):
        out.append(
            "INSERT INTO bank_imports (id, file_name, imported_at, imported_by, total_rows, matched_rows, pending_rows) "
            f"VALUES ({row['id']}, {sql_str(row['file_name'])}, {sql_str(row['imported_at'])}, "
            f"{sql_str(row['imported_by'])}, {sql_num(row['total_rows'])}, {sql_num(row['matched_rows'])}, "
            f"{sql_num(row['pending_rows'])});"
        )

    out.append("\n-- bank_entries")
    for row in con.execute("select * from bank_entries"):
        out.append(
            "INSERT INTO bank_entries (id, import_id, entry_date, document, payer, amount, raw_line, status, "
            "charge_id, matched_at, matched_by) VALUES ("
            f"{row['id']}, {sql_num(row['import_id'])}, {sql_str(row['entry_date'])}, {sql_str(row['document'])}, "
            f"{sql_str(row['payer'])}, {sql_num(row['amount'])}, {sql_str(row['raw_line'])}, {sql_str(row['status'])}, "
            f"{sql_num(row['charge_id'])}, {sql_str(row['matched_at'])}, {sql_str(row['matched_by'])});"
        )

    out.append("\n-- remittances")
    for row in con.execute("select * from remittances"):
        out.append(
            "INSERT INTO remittances (id, reference_month, due_date, layout, file_name, total_titles, total_amount, "
            "status, created_at, created_by, content) VALUES ("
            f"{row['id']}, {sql_str(row['reference_month'])}, {sql_str(row['due_date'])}, {sql_str(row['layout'])}, "
            f"{sql_str(row['file_name'])}, {sql_num(row['total_titles'])}, {sql_num(row['total_amount'])}, "
            f"{sql_str(row['status'])}, {sql_str(row['created_at'])}, {sql_str(row['created_by'])}, "
            f"{sql_str(row['content'])});"
        )

    # --- corrige as sequences (SERIAL) depois de inserir IDs explícitos ---
    out.append("\n-- ajusta as sequences dos IDs inseridos manualmente")
    for table in ("users", "licensees", "licenses", "charges", "bank_imports", "bank_entries", "remittances"):
        out.append(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1));"
        )

    out.append("\nCOMMIT;")
    print("\n".join(out))

    print(
        "-- LEMBRETE: copie também data/license_private.pem e data/license_public.pem "
        "do protótipo antigo para o DATA_DIR do BigPost novo, para que as "
        "licenças já emitidas continuem validando com a mesma chave.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    if not Path(sys.argv[1]).exists():
        print(f"Arquivo não encontrado: {sys.argv[1]}", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
