# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class ProductionRequestAcceptWizard(models.TransientModel):
    _name = 'production.request.accept.wizard'
    _description = 'Accept Production Request'

    request_id = fields.Many2one(
        'production.request',
        string='Production Request',
        required=True,
        readonly=True,
    )
    material_ready_date = fields.Date(
        string='Material Ready Date',
        required=True,
        help='Date on which Production commits that the finished material will be ready for Store/Sales.',
    )

    def action_accept(self):
        self.ensure_one()
        if not self.request_id:
            raise UserError(_('Production Request is missing.'))
        self.request_id._action_accept_with_date(self.material_ready_date)
        return {'type': 'ir.actions.client', 'tag': 'reload'}
