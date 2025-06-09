from odoo import models

class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def load_menus(self, debug=False):
        # Get original result
        res = super(IrUiMenu, self).load_menus(debug=debug)

        # Get user and their restricted menus
        user = self.env.user
        restricted_menu_ids = []

        for restriction in user.menu_restriction_ids:
            if restriction.group_id.id in user.groups_id.ids:
                restricted_menu_ids.append(restriction.menu_id.id)

        if not restricted_menu_ids:
            return res

        def filter_menus(menu_list):
            """Recursively remove restricted menu items"""
            return [
                {
                    **menu,
                    'children': filter_menus(menu.get('children', []))
                }
                for menu in menu_list
                if menu['id'] not in restricted_menu_ids
            ]

        res['children'] = filter_menus(res['children'])
        return res