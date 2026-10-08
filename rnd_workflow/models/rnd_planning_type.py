from odoo import fields, models


class RndPlanningType(models.Model):
    _name = 'rnd.planning.type'
    _description = 'R&D Planning Type (Proposal / BMP / RM & Equipment Planning)'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    color = fields.Integer(string='Color')
    active = fields.Boolean(default=True)
