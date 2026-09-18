# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class SaleOrder(models.Model):
    """
    Production Request visibility on Sales Orders.

    Production Requests are created from Delivery Orders. This model only
    exposes the resulting requests back to Sales for reference.
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
    material_ready_date = fields.Date(
        string='Material Ready Date',
        compute='_compute_material_ready_date',
        readonly=True,
        help='Earliest Material Ready Date among active Production Requests. '
             'The source of truth remains production.request.material_ready_date.',
    )

    @api.depends('production_request_ids.state', 'production_request_ids.material_ready_date')
    def _compute_material_ready_date(self):
        for order in self:
            dates = order.production_request_ids.filtered(
                lambda r: r.state not in ('done', 'cancelled') and r.material_ready_date
            ).mapped('material_ready_date')
            order.material_ready_date = min(dates) if dates else False

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
