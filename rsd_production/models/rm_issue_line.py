# -*- coding: utf-8 -*-
from odoo import api, models, fields, _
from odoo.exceptions import UserError


class RmIssueLine(models.Model):
    _name = 'rm.issue.line'
    _description = 'RM Issue Line'

    rm_issue_id = fields.Many2one(
        'rm.issue',
        required=True,
        ondelete='cascade',
    )
    product_id = fields.Many2one('product.product', required=True)
    qty = fields.Float(required=True)
    uom_id = fields.Many2one('uom.uom', required=True)

    @api.model_create_multi
    def create(self, vals_list):
        issue_ids = {
            vals.get('rm_issue_id')
            for vals in vals_list
            if vals.get('rm_issue_id')
        }
        issues = self.env['rm.issue'].browse(list(issue_ids))
        if any(
            issue.internal_transfer_ref or issue.state in ('issued', 'cancelled')
            for issue in issues
        ):
            raise UserError(_(
                'RM Issue lines cannot be changed after stock processing has started.'
            ))
        return super().create(vals_list)

    def write(self, vals):
        for line in self:
            if (
                line.rm_issue_id.internal_transfer_ref
                or line.rm_issue_id.state in ('issued', 'cancelled')
            ):
                raise UserError(_(
                    'RM Issue lines cannot be changed after stock processing has started.'
                ))
        return super().write(vals)

    def unlink(self):
        for line in self:
            if (
                line.rm_issue_id.internal_transfer_ref
                or line.rm_issue_id.state in ('issued', 'cancelled')
            ):
                raise UserError(_(
                    'RM Issue lines cannot be deleted after stock processing has started.'
                ))
        return super().unlink()
