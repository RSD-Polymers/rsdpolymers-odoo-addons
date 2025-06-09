from odoo import models, fields, api


class ResGroups(models.Model):
    _inherit = 'res.groups'

    hide_menu_ids = fields.Many2many(
        'ir.ui.menu', string="Hidden Menu",
        help='Select menu items to hide for users in this group.')

    is_admin = fields.Boolean(
        compute='_get_is_admin', string="Is Admin Group",
        help='Check if this is the Administrator group.')

    def write(self, vals):
        old_hide_menu_map = {record.id: record.hide_menu_ids for record in self}
        res = super().write(vals)
        for record in self:
            old_hide_menu_ids = old_hide_menu_map.get(record.id, self.env['ir.ui.menu'])
            added = record.hide_menu_ids - old_hide_menu_ids
            removed = old_hide_menu_ids - record.hide_menu_ids

            for menu in added:
                menu.sudo().write({'restrict_user_group_ids': [(4, record.id)]})
            for menu in removed:
                menu.sudo().write({'restrict_user_group_ids': [(3, record.id)]})
        return res

    def _get_is_admin(self):
        admin_group = self.env.ref('base.group_system')
        for rec in self:
            rec.is_admin = (rec == admin_group)


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    restrict_user_group_ids = fields.Many2many(
        'res.groups', string="Restricted User Groups",
        help='Groups restricted from seeing this menu.')

    @api.returns('self')
    def _filter_visible_menus(self):
        menus = super()._filter_visible_menus()
        if self.env.user.has_group('base.group_system'):
            return menus
        user_group_ids = set(self.env.user.groups_id.ids)
        return menus.filtered(
            lambda m: not (set(m.restrict_user_group_ids.ids) & user_group_ids)
        )
