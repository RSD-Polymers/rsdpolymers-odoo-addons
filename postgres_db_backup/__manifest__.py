# -*- coding: utf-8 -*-
# Odoo 18 Module Manifest File
{
    'name': "PostgreSQL DB Automated Backup",
    'icon': '/postgres_db_backup/static/description/icon.png',
    'summary': "Automates PostgreSQL database backup and uploads it to a configured Google Drive folder.",
    'description': """
        This module provides a mechanism to:
        1. Configure Google Drive API credentials (Client ID, Secret, Refresh Token, Folder ID).
        2. Execute a full PostgreSQL database dump using the 'pg_dump' utility.
        3. Upload the resulting backup file to the specified Google Drive folder.

        Requires external Python libraries: google-api-python-client, google-auth-httplib2, google-auth-oauthlib.
    """,
    'author': "Ameya",
    'category': 'Administration',
    'version': '18.0.1.0.0',
    'depends': ['base'],
    'data': [
        'security/ir.model.access.csv',
        'views/pg_backup_views.xml',
        'data/pg_backup_cron.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'OEEL-1',
}
