# -*- coding: utf-8 -*-
from odoo import api, models, fields, _
from odoo.exceptions import UserError, ValidationError


class RmIssueLine(models.Model):
    _name = 'rm.issue.line'
    _description = 'RM Issue Line'

    rm_issue_id = fields.Many2one('rm.issue', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    qty = fields.Float(required=True)
    uom_id = fields.Many2one('uom.uom', required=True)

    def _check_editable_and_category(self, issue, product):
        if issue.state != 'draft' or issue.internal_transfer_ref:
            raise UserError(_('RM Issue lines can only be changed while the request is in Draft.'))
        category = self.env['product.category'].search([('complete_name', '=', 'All / Sales / Finished Goods (Un-Pack)')], limit=1)
        if category and product.categ_id and product.categ_id.id in self.env['product.category'].search([('id', 'child_of', category.id)]).ids:
            raise ValidationError(_('Finished Goods (Un-Pack) products cannot be added to an RM Issue.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            issue = self.env['rm.issue'].browse(vals.get('rm_issue_id'))
            product = self.env['product.product'].browse(vals.get('product_id'))
            if issue and product:
                self._check_editable_and_category(issue, product)
            if vals.get('qty', 0) <= 0:
                raise ValidationError(_('Requested quantity must be greater than zero.'))
        return super().create(vals_list)

    def write(self, vals):
        for line in self:
            issue = line.rm_issue_id
            product = self.env['product.product'].browse(vals.get('product_id')) if vals.get('product_id') else line.product_id
            self._check_editable_and_category(issue, product)
            if 'qty' in vals and vals['qty'] <= 0:
                raise ValidationError(_('Requested quantity must be greater than zero.'))
        return super().write(vals)

    def unlink(self):
        for line in self:
            self._check_editable_and_category(line.rm_issue_id, line.product_id)
        return super().unlink()
