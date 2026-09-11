# -*- coding: utf-8 -*-
from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError


class ProductionRequestPlanWizard(models.TransientModel):
    _name = 'production.request.plan.wizard'
    _description = 'Production Request Planning Wizard'

    request_ids = fields.Many2many('production.request', string='Production Requests', readonly=True)
    line_ids = fields.One2many('production.request.plan.wizard.line', 'wizard_id', string='Planning Lines')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        request_ids = self.env.context.get('default_request_ids', [Command.set([])])
        if isinstance(request_ids, list) and request_ids and isinstance(request_ids[0], (list, tuple)):
            ids = request_ids[0][2] if request_ids[0][0] == 6 else []
        else:
            ids = []
        requests = self.env['production.request'].browse(ids).exists().filtered(lambda r: r.state == 'accepted' and not r.mo_id)
        vals['request_ids'] = [Command.set(requests.ids)]
        grouped = {}
        for req in requests:
            key = (req.product_id.id, req.product_uom_id.id, req.company_id.id)
            grouped.setdefault(key, 0.0)
            grouped[key] += req.shortage_qty
        vals['line_ids'] = [Command.create({
            'product_id': self.env['product.product'].browse(product_id).id,
            'uom_id': self.env['uom.uom'].browse(uom_id).id,
            'company_id': self.env['res.company'].browse(company_id).id,
            'shortage_qty': qty,
            'planned_qty': qty,
        }) for (product_id, uom_id, company_id), qty in grouped.items()]
        return vals

    def action_create_mo(self):
        self.ensure_one()
        self.env['production.request']._check_production_user()
        requests = self.request_ids.filtered(lambda r: r.state == 'accepted' and not r.mo_id)
        if not requests:
            raise UserError(_('There are no Accepted Production Requests left to plan.'))
        if not self.line_ids:
            raise UserError(_('No production planning lines were created.'))

        created_mos = self.env['mrp.production']
        for line in self.line_ids:
            if line.planned_qty <= 0:
                raise UserError(_('Planned quantity must be greater than zero for %s.') % line.product_id.display_name)
            if line.planned_qty < line.shortage_qty:
                raise UserError(_(
                    'Planned quantity for %s cannot be less than the total shortage (%s %s).'
                ) % (line.product_id.display_name, line.shortage_qty, line.uom_id.name))

            product_requests = requests.filtered(lambda r: r.product_id == line.product_id and r.product_uom_id == line.uom_id and r.company_id == line.company_id)
            if not product_requests:
                continue

            bom = self.env['mrp.bom']._bom_find(
                products=line.product_id,
                company_id=line.company_id.id,
            )[line.product_id]
            if not bom:
                raise UserError(_('No Bill of Materials found for %s.') % line.product_id.display_name)

            mo = self.env['mrp.production'].create({
                'product_id': line.product_id.id,
                'product_qty': line.planned_qty,
                'product_uom_id': line.uom_id.id,
                'bom_id': bom.id,
                'origin': ', '.join(product_requests.mapped('sale_id.name')),
                'origin_sale_id': product_requests[0].sale_id.id if product_requests[0].sale_id else False,
                'company_id': line.company_id.id,
            })
            mo.production_request_ids = [Command.set(product_requests.ids)]
            product_requests.write({
                'mo_id': mo.id,
                'planned_qty': line.planned_qty,
                'planned_by': self.env.user.id,
                'state': 'planned',
            })
            created_mos |= mo

        if not created_mos:
            raise UserError(_('No Manufacturing Order was created.'))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Manufacturing Orders'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created_mos.ids)],
            'target': 'current',
        }


class ProductionRequestPlanWizardLine(models.TransientModel):
    _name = 'production.request.plan.wizard.line'
    _description = 'Production Request Planning Line'

    wizard_id = fields.Many2one('production.request.plan.wizard', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True, readonly=True)
    uom_id = fields.Many2one('uom.uom', required=True, readonly=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True)
    shortage_qty = fields.Float(string='Total Shortage', readonly=True)
    planned_qty = fields.Float(string='Production Qty', required=True)
