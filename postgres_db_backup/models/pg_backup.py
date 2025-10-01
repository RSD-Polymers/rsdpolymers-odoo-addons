# -*- coding: utf-8 -*-
import os
import tempfile
import logging
import subprocess
from datetime import datetime, timezone, timedelta

import requests

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import config

_logger = logging.getLogger(__name__)

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    GOOGLE_DRIVE_INSTALLED = True
except ImportError:
    _logger.warning(
        "The required Google Drive libraries (google-api-python-client, etc.) are not installed. Backup to Google Drive functionality will be disabled.")
    GOOGLE_DRIVE_INSTALLED = False


# =================================================================================
# Google Drive Service Class (Internal Helper)
# This class handles the API interaction using credentials stored in Odoo.
# =================================================================================
class GoogleDriveService(object):
    """Handles communication with the Google Drive API."""

    def cleanup_old_backups(self, folder_id, days=7):
        """Delete backups older than 'days' in the given folder."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        try:
            # List all files in the folder
            results = self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="files(id, name, createdTime)"
            ).execute()
            files = results.get('files', [])

            for f in files:
                created_time = datetime.fromisoformat(f['createdTime'].replace('Z', '+00:00'))
                if created_time < cutoff_date:
                    self.service.files().delete(fileId=f['id']).execute()
                    _logger.info("Deleted old backup from Drive: %s", f['name'])
        except Exception as e:
            _logger.warning("Failed to clean old backups: %s", e)

    def __init__(self, client_id, client_secret, refresh_token):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.service = self._get_drive_service()

    def _get_drive_service(self):
        if not GOOGLE_DRIVE_INSTALLED:
            raise UserError(
                _("Google Drive libraries are missing. Please install: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")
            )

        creds = Credentials(
            token=None,
            client_id=self.client_id,
            client_secret=self.client_secret,
            refresh_token=self.refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            scopes=['https://www.googleapis.com/auth/drive.file']
        )

        # Refresh token if expired
        if creds.expired and creds.refresh_token:
            creds.refresh(requests.Request())

        return build('drive', 'v3', credentials=creds)

    def upload_file(self, filename, filepath, folder_id):
        """Uploads a local file to the specified Google Drive folder."""
        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }

        try:
            media = MediaFileUpload(filepath, resumable=True)
            try:
                file = self.service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id'
                ).execute()
            finally:
                # Close the file handle to release it on Windows
                media.stream().close()

            _logger.info("File uploaded successfully. Drive File ID: %s", file.get('id'))
            return file.get('id')

        except Exception as e:
            raise UserError(_("Google Drive Upload Failed: Check credentials and folder ID. Error: %s") % str(e))


# =================================================================================
# Odoo Backup Configuration Model
# =================================================================================
class OdooGoogleDriveBackupConfig(models.Model):
    _name = 'gdrive.backup.config'
    _description = 'Google Drive Backup Configuration'

    name = fields.Char(string="Configuration Name", required=True, default="Daily PostgreSQL DB Backup")

    # Google Drive API Fields
    client_id = fields.Char(string="Google Client ID", required=True,
                            help="OAuth2 Client ID from Google Cloud Console.")
    client_secret = fields.Char(string="Google Client Secret", required=True, help="OAuth2 Client Secret.")
    refresh_token = fields.Char(string="Google Refresh Token", required=False, # <-- FIX: Changed to False
                                help="The long-lived Refresh Token obtained after first authorization.")
    folder_id = fields.Char(string="Drive Folder ID", required=True,
                            help="The ID of the destination folder in Google Drive.")

    # Status and Logging
    last_backup_time = fields.Datetime(string="Last Backup Time", readonly=True)
    last_backup_status = fields.Selection([
        ('success', 'Success'),
        ('failure', 'Failure'),
        ('pending', 'Pending'),
    ], string="Last Status", default='pending', readonly=True)

    show_authorize_button = fields.Boolean(
        string="Show Authorize Button",
        compute='_compute_show_authorize_button',
        store=True
    )

    @api.depends('refresh_token')
    def _compute_show_authorize_button(self):
        for record in self:
            record.show_authorize_button = not bool(record.refresh_token)

    @api.model
    def run_cron_backup(self):
        """Run backup for all configured records and log results."""
        records = self.search([])
        for record in records:
            try:
                result = record.action_run_backup()
                _logger.info("Backup successful for config: %s", record.name)
            except UserError as e:
                _logger.error("Backup failed for config: %s. Error: %s", record.name, e)
                # Send email on failure
                self.env['mail.mail'].sudo().create({
                    'subject': f"Google Drive Backup Failed for {record.name}",
                    'body_html': f"<p>Backup failed for configuration: <b>{record.name}</b></p><p>Error: {e}</p>",
                    'email_to': 'ameyav123@example.com',
                }).send()

    def action_open_auth_url(self):
        """
        Generates the Google OAuth authorization URL and returns an action
        that redirects the user's browser to that URL to start the OAuth flow.
        """
        self.ensure_one()  # Ensure only one record is used

        if not self.client_id or not self.client_secret:
            raise UserError(_("Please enter and save your Google Client ID and Secret before authorizing."))

        # Redirect URI must exactly match Google Cloud Console
        redirect_uri = f"{self.env['ir.config_parameter'].sudo().get_param('web.base.url')}/odoo_gdrive_token"

        # Construct the Google OAuth 2.0 URL
        auth_url = (
            "https://accounts.google.com/o/oauth2/auth?"
            f"client_id={self.client_id}"
            f"&redirect_uri={redirect_uri}"
            "&scope=https://www.googleapis.com/auth/drive.file"
            "&access_type=offline"  # Required for refresh token
            "&response_type=code"
            "&prompt=consent"  # 👈 Force consent so refresh_token is returned
        )

        return {
            'type': 'ir.actions.act_url',
            'url': auth_url,
            'target': 'self',
        }

    def _get_db_connection_params(self):
        db_name = self.env.cr.dbname
        db_host = config['db_host'] or 'localhost'
        db_port = config['db_port'] or 5432
        db_user = config['db_user']
        db_password = config['db_password']

        pg_bin_dir = config.get('pg_path')  # Read directly from odoo.conf
        if not pg_bin_dir:
            raise UserError(_("PostgreSQL bin path (pg_path) is not set in odoo.conf"))

        if not all([db_user, db_password]):
            raise UserError(_("Database user and password must be configured in odoo.conf"))

        return db_name, db_host, str(db_port), db_user, db_password, pg_bin_dir

    def action_run_backup(self):
        """Run PostgreSQL backup and upload to Google Drive."""
        self.ensure_one()

        if not self.client_id or not self.client_secret or not self.refresh_token or not self.folder_id:
            raise UserError(_("Google Drive credentials and Folder ID must be set on the configuration record."))

        db_name, db_host, db_port, db_user, db_password, pg_bin_dir = self._get_db_connection_params()

        backup_filename = f"{db_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.dump"
        temp_dir = tempfile.gettempdir()
        temp_file_path = os.path.join(temp_dir, backup_filename)

        _logger.info("Starting PostgreSQL dump to temporary file: %s", temp_file_path)

        try:
            env = os.environ.copy()
            env['PGPASSWORD'] = db_password

            command = [
                os.path.join(config.get('pg_path', ''), 'pg_dump'),  # Use pg_path from odoo.conf
                '--host', db_host,
                '--port', str(db_port),
                '--username', db_user,
                '--format', 'c',
                '--file', temp_file_path,
                db_name
            ]

            process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate()

            if process.returncode != 0:
                self.write({
                    'last_backup_status': 'failure',
                    'last_backup_time': fields.Datetime.now()
                })
                raise UserError(_("PostgreSQL dump failed!\nError:\n%s") % stderr.decode('utf-8'))

            _logger.info("PostgreSQL dump successful. File size: %s bytes", os.path.getsize(temp_file_path))

            # Upload to Google Drive
            gdrive_service = GoogleDriveService(self.client_id, self.client_secret, self.refresh_token)
            gdrive_service.upload_file(backup_filename, temp_file_path, self.folder_id)

            # Cleanup old backups
            gdrive_service.cleanup_old_backups(self.folder_id, days=7)

            # Update status
            self.write({
                'last_backup_status': 'success',
                'last_backup_time': fields.Datetime.now()
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Backup Successful"),
                    'message': _(
                        "Database backup '%s' successfully created and uploaded to Google Drive.") % backup_filename,
                    'sticky': False,
                }
            }

        except Exception as e:
            self.write({
                'last_backup_status': 'failure',
                'last_backup_time': fields.Datetime.now()
            })
            _logger.error("Backup and upload failed: %s", e)
            raise UserError(_("Backup and Upload Failed: %s") % str(e))

        finally:
            # Cleanup temp file safely
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                    _logger.info("Temporary backup file deleted: %s", temp_file_path)
                except Exception as cleanup_error:
                    _logger.warning("Could not delete temp file: %s. Error: %s", temp_file_path, cleanup_error)




