# -*- coding: utf-8 -*-
from odoo import fields, models, _, Command
from odoo.exceptions import UserError


class ProductionRequestRejectWizard(models.TransientModel):
    _name = 'production.request.reject.wizard'
    _description = 'Reject Production Request'

    request_id = fields.Many2one('production.request', required=True, readonly=True)
    reason = fields.Text(string='Rejection Reason', required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise UserError(_('Please provide a rejection reason.'))
        self.request_id._action_reject(self.reason.strip())
        return {'type': 'ir.actions.client', 'tag': 'reload'}
