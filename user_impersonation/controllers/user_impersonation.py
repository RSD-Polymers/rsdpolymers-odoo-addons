from odoo import http
from odoo.http import request


class UserSwitch(http.Controller):
    """This is a controller to switch user and switch back to admin
        user_switch:
            this function is to check weather the user is admin or not
        switch_admin:
            function to switch back to admin
    """

    @http.route('/switch/user', type='json', auth='public')
    def user_switch(self):
        """
            Summary:
                function to check weather the user is admin
            Return:
                weather the current user is admin or not
        """
        return request.env.user._is_admin()

    @http.route('/switch/admin', type='json', auth='public')
    def switch_admin(self):
        """
            Summary:
                function to move back to admin
            Return:
                the home page to be loaded
                """
        session = request.session
        pre_user = request.env['res.users'].browse(session.previous_user)
        if pre_user and pre_user._is_admin:
            session.authenticate_without_password(request.env.cr.dbname,
                                                  pre_user.login, request.env)
            return {
                'type': 'ir.actions.act_url',
                'url': '/',
                'target': 'self'
            }
        return True
