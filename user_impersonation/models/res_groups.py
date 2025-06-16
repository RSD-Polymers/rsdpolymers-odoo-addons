from odoo import fields, models


class ResGroups(models.Model):
    """class to inherit a new field to res groups"""
    _inherit = 'res.groups'

    user_id = fields.Many2one('user.selection', string="User",
                              help="Select User")
