# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request
import requests
import logging

_logger = logging.getLogger(__name__)

class GoogleDriveOAuthController(http.Controller):

    @http.route('/odoo_gdrive_token', type='http', auth='user')
    def oauth_callback(self, **kwargs):
        """
        Receives the Google OAuth 2.0 code and exchanges it for a refresh token.
        Redirects back to the config form with a notification.
        """
        config_record = request.env['gdrive.backup.config'].sudo().search([], limit=1)
        base_url = request.env['ir.config_parameter'].sudo().get_param("web.base.url")
        redirect_url = f"/web#id={config_record.id}&model=gdrive.backup.config&view_type=form"

        code = kwargs.get("code")
        error = kwargs.get("error")

        # --- Handle Google errors ---
        if error:
            return request.redirect(f"{redirect_url}&message=Google+OAuth+Error:+{error}")

        if not code:
            return request.redirect(f"{redirect_url}&message=No+authorization+code+returned+from+Google")

        # --- Exchange code for tokens ---
        data = {
            "code": code,
            "client_id": config_record.client_id,
            "client_secret": config_record.client_secret,
            "redirect_uri": f"{base_url}/odoo_gdrive_token",
            "grant_type": "authorization_code",
        }

        try:
            resp = requests.post("https://oauth2.googleapis.com/token", data=data)
            token_data = resp.json()

            if resp.status_code != 200 or "error" in token_data:
                msg = token_data.get("error_description") or token_data.get("error", resp.text)
                return request.redirect(f"{redirect_url}&message=Google+Token+Error:+{msg}")

            refresh_token = token_data.get("refresh_token")
            if not refresh_token:
                return request.redirect(f"{redirect_url}&message=No+refresh+token+received.+Please+authorize+again+with+consent.")

            # Save refresh token
            config_record.write({"refresh_token": refresh_token})
            _logger.info("Google OAuth successful. Refresh token stored.")

            return request.redirect(f"{redirect_url}&message=Authorization+successful")

        except Exception as e:
            _logger.error("OAuth token exchange failed: %s", e)
            return request.redirect(f"{redirect_url}&message=OAuth+flow+failed:+{str(e)}")
