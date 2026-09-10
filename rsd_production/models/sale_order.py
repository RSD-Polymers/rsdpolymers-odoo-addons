# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    """
    This extension exists in rsd_production (not rsd_sales) on purpose:
    the `production.request` model lives in this module, and rsd_production
    already depends on rsd_sales. Putting this logic here avoids a circular
    module dependency (rsd_sales would otherwise need to depend on
    rsd_production, which depends on rsd_sales).
    """
    _inherit = 'sale.order'

    production_request_ids = fields.One2many(
        'production.request',
        'sale_id',
        string='Production Requests',
        readonly=True,
    )

    production_request_count = fields.Integer(
        string="Production Request Count",
        compute='_compute_production_request_counts',
    )
    pending_production_request_count = fields.Integer(
        string="Pending Production Request Count",
        compute='_compute_production_request_counts',
    )

    def _compute_production_request_counts(self):
        all_counts = dict(self.env['production.request']._read_group(
            domain=[('sale_id', 'in', self.ids)],
            groupby=['sale_id'],
            aggregates=['__count'],
        ))
        pending_counts = dict(self.env['production.request']._read_group(
            domain=[('sale_id', 'in', self.ids), ('state', 'not in', ('done', 'cancelled'))],
            groupby=['sale_id'],
            aggregates=['__count'],
        ))
        for order in self:
            order.production_request_count = all_counts.get(order, 0)
            order.pending_production_request_count = pending_counts.get(order, 0)

    def action_view_production_requests(self):
        self.ensure_one()
        requests = self.env['production.request'].search([('sale_id', '=', self.id)])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Production Requests'),
            'res_model': 'production.request',
            'view_mode': 'list,form',
            'domain': [('id', 'in', requests.ids)],
            'context': {'default_sale_id': self.id, 'create': False},
        }

    def action_create_production_requests(self):
        """
        Create a Finished Goods Production Request for every out-of-stock line
        on this order that doesn't already have an open (not done/cancelled)
        request. Lines that are already fully covered by Packed FG stock, or
        that already have a pending request, are skipped.
        """
        ProductionRequest = self.env['production.request']

        for order in self:
            shortage_lines = order.order_line.filtered(
                lambda l: not l.display_type
                and l.product_id.type in ('product', 'consu')
                and l.is_out_of_stock
            )
            if not shortage_lines:
                raise UserError(_("There are no out-of-stock lines on %s to request production for.") % order.name)

            created = ProductionRequest
            for line in shortage_lines:
                existing = ProductionRequest.search([
                    ('sale_line_id', '=', line.id),
                    ('state', 'not in', ('done', 'cancelled')),
                ], limit=1)
                if existing:
                    continue

                required_qty = line.product_uom_qty
                available_qty = line.qty_packed_inventory
                shortage_qty = max(required_qty - available_qty, 0.0)
                if shortage_qty <= 0:
                    continue

                created |= ProductionRequest.create({
                    'sale_id': order.id,
                    'sale_line_id': line.id,
                    'product_id': line.product_id.id,
                    'product_uom_id': line.product_uom.id,
                    'required_qty': required_qty,
                    'fg_available_qty': available_qty,
                    'shortage_qty': shortage_qty,
                })

            if created:
                order.message_post(
                    body=_("%d Production Request(s) created for shortage line(s).") % len(created)
                )
            else:
                order.message_post(
                    body=_("No new Production Requests were needed (existing open requests already cover the shortage).")
                )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Production Requests'),
            'res_model': 'production.request',
            'view_mode': 'list,form',
            'domain': [('sale_id', 'in', self.ids)],
            'context': {'create': False},
        }
