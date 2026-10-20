import os

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import ROLE_ADMIN, ROLE_STAFF, Account, Profile


# role -> prefix of the .env variables that describe that account
DEFAULT_ACCOUNTS = (
    (ROLE_ADMIN, 'DEFAULT_ADMIN'),
    (ROLE_STAFF, 'DEFAULT_STAFF'),
)


class Command(BaseCommand):
    help = (
        'Create the default admin and staff accounts from the .env file if they do not exist yet. '
        'Safe to run on every startup: existing accounts are never changed.'
    )

    @transaction.atomic
    def handle(self, *args, **options):
        for role, prefix in DEFAULT_ACCOUNTS:
            #login lowercases usernames, so store them lowercase too
            username = os.environ.get(f'{prefix}_USERNAME', '').strip().lower()
            password = os.environ.get(f'{prefix}_PASSWORD', '')
            email = os.environ.get(f'{prefix}_EMAIL', '').strip() or f'{username}@example.test'

            if not username or not password:
                self.stdout.write(
                    f'Skipping default {role} account: set {prefix}_USERNAME and {prefix}_PASSWORD in .env.'
                )
                continue

            account, was_created = Account.objects.get_or_create(
                username=username,
                defaults={
                    'password_hash': make_password(password),
                    'account_type': role,
                },
            )

            if not was_created:
                if account.account_type != role:
                    self.stdout.write(self.style.WARNING(
                        f'Account "{username}" already exists as "{account.account_type}", '
                        f'not "{role}". Left unchanged.'
                    ))
                else:
                    self.stdout.write(f'Default {role} account "{username}" already exists.')
                continue

            #profile email is unique, so don't fail startup if it is already taken
            if Profile.objects.filter(email=email).exists():
                self.stdout.write(self.style.WARNING(
                    f'Email {email} is already used by another profile; '
                    f'"{username}" was created without a profile.'
                ))
            else:
                Profile.objects.create(
                    account=account,
                    first_name=os.environ.get(f'{prefix}_FIRST_NAME', '').strip() or role.capitalize(),
                    last_name='Account',
                    email=email,
                )

            self.stdout.write(self.style.SUCCESS(f'Created default {role} account "{username}".'))
