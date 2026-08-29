"""Secret-safe tenant-member password setup command."""

import click
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy import select

from app.auth import (
    PasswordPolicyError,
    TenantMemberNotFound,
    normalize_china_phone,
    set_tenant_member_password,
)
from app.control.models import TenantMember


def _password_from_stdin():
    password = click.get_text_stream("stdin").read()
    if password.endswith("\r\n"):
        return password[:-2]
    if password.endswith("\n"):
        return password[:-1]
    return password


@click.command("set-tenant-password")
@click.option("--phone", required=True, help="Tenant member phone number.")
@click.option(
    "--password-stdin",
    is_flag=True,
    help="Read the password from standard input for non-TTY automation.",
)
@with_appcontext
def set_tenant_password(phone, password_stdin):
    store = current_app.extensions.get("control_store")
    if store is None:
        raise click.ClickException("Control database is not configured.")
    try:
        normalized_phone = normalize_china_phone(phone)
    except ValueError as exc:
        raise click.ClickException("Phone number is invalid.") from exc

    with store.session() as session:
        member_exists = session.scalar(
            select(TenantMember.id).where(
                TenantMember.phone == normalized_phone
            )
        )
    if member_exists is None:
        raise click.ClickException("Tenant member was not found.")

    password = (
        _password_from_stdin()
        if password_stdin
        else click.prompt(
            "Password",
            hide_input=True,
            confirmation_prompt=True,
        )
    )
    try:
        set_tenant_member_password(store, normalized_phone, password)
    except PasswordPolicyError as exc:
        raise click.ClickException(str(exc)) from exc
    except TenantMemberNotFound as exc:
        raise click.ClickException("Tenant member was not found.") from exc
    click.echo("Tenant member password updated; existing sessions revoked.")


def register_tenant_password_command(app):
    app.cli.add_command(set_tenant_password)
