# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class ProductionRequestExecutionWizard(models.TransientModel):
    _name = 'production.request.execution.wizard'
    _description = 'Production Request Execution'

    request_line_id = fields.Many2one(
        'production.request.line',
        string='Production Request Line',
        required=True,
        readonly=True,
    )
    execution_type = fields.Selection([
        ('mo', 'Manufacturing Order'),
        ('pi', 'Packing Instruction'),
    ], string='Document Type', required=True, readonly=True)
    quantity = fields.Float(string='Quantity', required=True)

    def action_create(self):
        self.ensure_one()
        line = self.request_line_id
        line.request_id._check_production_user()
        line._check_execution_allowed()

        if self.quantity <= 0:
            raise UserError(_('Quantity must be greater than zero.'))
        if self.quantity > line.remaining_qty:
            raise UserError(_(
                'Quantity cannot exceed the remaining quantity of %s (%s %s).'
            ) % (line.product_id.display_name, line.remaining_qty, line.product_uom_id.name))

        bom = self.env['mrp.bom']._bom_find(
            products=line.product_id,
            company_id=line.request_id.company_id.id,
        )[line.product_id]
        if not bom:
            raise UserError(_('No Bill of Materials found for %s.') % line.product_id.display_name)

        is_packing_order = self.execution_type == 'pi'
        vals = {
            'product_id': line.product_id.id,
            'product_qty': self.quantity,
            'product_uom_id': line.product_uom_id.id,
            'bom_id': bom.id,
            'origin': line.request_id.name,
            'company_id': line.request_id.company_id.id,
            'is_packing_order': is_packing_order,
            'production_request_line_id': line.id,
        }

        # These fields belong to rsd_sales. Keep this module loosely coupled
        # to their exact availability while rsd_production already depends on it.
        mo_model = self.env['mrp.production']
        if 'production_request_type' in mo_model._fields:
            vals['production_request_type'] = 'order'
        if 'origin_sale_id' in mo_model._fields and line.request_id.sale_id:
            vals['origin_sale_id'] = line.request_id.sale_id.id

        execution = mo_model.create(vals)
        line.request_id._sync_state_from_lines()

        line.request_id.message_post(
            body=_('%s <b>%s</b> created for <b>%s</b>, quantity <b>%s %s</b>.') % (
                'Packing Instruction' if is_packing_order else 'Manufacturing Order',
                execution.name,
                line.product_id.display_name,
                self.quantity,
                line.product_uom_id.name,
            ),
            subtype_xmlid='mail.mt_note',
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Packing Instruction') if is_packing_order else _('Manufacturing Order'),
            'res_model': 'mrp.production',
            'view_mode': 'form',
            'res_id': execution.id,
            'target': 'current',
        }
