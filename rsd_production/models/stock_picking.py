# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    production_request_ids = fields.One2many(
        'production.request',
        'picking_id',
        string='Production Requests',
        readonly=True,
    )
    production_request_count = fields.Integer(
        string='Production Request Count',
        compute='_compute_production_request_count',
    )
    has_production_shortage = fields.Boolean(
        string='Has Production Shortage',
        compute='_compute_production_shortage',
    )
    is_store_user = fields.Boolean(
        string='Is Store User',
        compute='_compute_is_store_user',
        store=False,
    )

    def _compute_production_request_count(self):
        for picking in self:
            picking.production_request_count = len(picking.production_request_ids)

    @api.depends_context('uid')
    def _compute_is_store_user(self):
        user = self.env.user
        privileged = (
            user.has_group('base.group_system')
            or user.has_group('stock.group_stock_manager')
        )
        employee = user.employee_id
        department = (
            employee.department_id.name.strip().lower()
            if employee and employee.department_id
            else ''
        )
        is_store = privileged or department == 'store'
        for picking in self:
            picking.is_store_user = is_store

    def _get_packed_fg_location(self):
        self.ensure_one()
        location = self.env['stock.location'].search([
            ('name', '=', 'Packed - FG'),
            ('id', 'child_of', self.location_id.id),
        ], limit=1)
        if not location:
            location = self.env['stock.location'].search([
                ('name', '=', 'Packed - FG'),
            ], limit=1)
        return location

    @api.depends(
        'state',
        'move_ids.product_uom_qty',
        'move_ids.product_id',
        'move_ids.sale_line_id',
        'move_ids.state',
    )
    def _compute_production_shortage(self):
        Quant = self.env['stock.quant']
        for picking in self:
            picking.has_production_shortage = False

            if (
                picking.picking_type_id.code != 'outgoing'
                or picking.state in ('done', 'cancel')
            ):
                continue

            fg_location = picking._get_packed_fg_location()
            if not fg_location:
                continue

            for move in picking.move_ids.filtered(
                lambda m:
                    m.state not in ('done', 'cancel')
                    and m.product_id
                    and m.sale_line_id
                    and m.product_id.is_storable
            ):
                available = Quant._get_available_quantity(
                    move.product_id,
                    fg_location,
                )
                available = move.product_id.uom_id._compute_quantity(
                    available,
                    move.product_uom,
                    round=False,
                )
                if available < move.product_uom_qty:
                    picking.has_production_shortage = True
                    break

    def _check_store_user(self):
        self.ensure_one()
        if not self.is_store_user:
            raise UserError(
                _('Only Store users can create Production Requests from a Delivery Order.')
            )

    def action_create_production_requests(self):
        self.ensure_one()
        self._check_store_user()

        if self.picking_type_id.code != 'outgoing':
            raise UserError(
                _('Production Requests can only be created from an outgoing Delivery Order.')
            )
        if self.state in ('done', 'cancel'):
            raise UserError(
                _('This Delivery Order is already completed or cancelled.')
            )

        fg_location = self._get_packed_fg_location()
        if not fg_location:
            raise UserError(_('Packed - FG location was not found.'))

        ProductionRequest = self.env['production.request']
        ProductionRequestLine = self.env['production.request.line']
        Quant = self.env['stock.quant']

        moves = self.move_ids.filtered(
            lambda m:
                m.state not in ('done', 'cancel')
                and m.product_id
                and m.sale_line_id
                and m.product_id.is_storable
        )
        if not moves:
            raise UserError(
                _('No eligible product lines were found on this Delivery Order.')
            )

        # One Production Request belongs to exactly one product. If the same
        # product occurs on more than one stock move, combine those moves into
        # one request and one request line.
        product_moves = {}
        for move in moves:
            product_moves.setdefault(move.product_id.id, self.env['stock.move'])
            product_moves[move.product_id.id] |= move

        created_requests = ProductionRequest.browse()
        existing_requests = ProductionRequest.search([
            ('picking_id', '=', self.id),
            ('state', '!=', 'cancelled'),
        ])

        for product_id, product_move_set in product_moves.items():
            existing_request = existing_requests.filtered(
                lambda request: request.line_ids
                and any(line.product_id.id == product_id for line in request.line_ids)
            )[:1]
            if existing_request:
                continue

            product = self.env['product.product'].browse(product_id)
            required_qty = 0.0
            packaging_qty = 0.0
            packaging = self.env['product.packaging'].browse()
            sale_line = self.env['sale.order.line'].browse()

            for move in product_move_set:
                qty = move.product_uom_qty
                qty = move.product_uom._compute_quantity(
                    qty, product.uom_id, round=False
                )
                required_qty += qty

                if move.sale_line_id:
                    if not sale_line:
                        sale_line = move.sale_line_id
                    if not packaging and move.sale_line_id.product_packaging_id:
                        packaging = move.sale_line_id.product_packaging_id
                    packaging_qty += move.sale_line_id.product_packaging_qty or 0.0

            available_qty = Quant._get_available_quantity(
                product,
                fg_location,
            )
            available_qty = product.uom_id._compute_quantity(
                available_qty,
                product.uom_id,
                round=False,
            )
            shortage_qty = max(required_qty - available_qty, 0.0)

            source_sale = sale_line.order_id if sale_line else self.env['sale.order']
            if not source_sale:
                raise UserError(
                    _('Delivery Order %s is not linked to a Sales Order for product %s.')
                    % (self.name, product.display_name)
                )

            request = ProductionRequest.create({
                'sale_id': source_sale.id,
                'picking_id': self.id,
                'company_id': self.company_id.id,
            })

            ProductionRequestLine.create({
                'request_id': request.id,
                'sale_line_id': sale_line.id if sale_line else False,
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'required_qty': required_qty,
                'fg_available_qty': available_qty,
                'shortage_qty': shortage_qty,
                'product_packaging_id': packaging.id if packaging else False,
                'product_packaging_qty': packaging_qty,
            })

            created_requests |= request
            existing_requests |= request

        if not created_requests:
            raise UserError(
                _('Production Requests already exist for all eligible products on this Delivery Order.')
            )

        self.message_post(
            body=_(
                '%d Production Request(s) created for %d product(s).'
            ) % (len(created_requests), len(created_requests))
        )

        if len(created_requests) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Production Request'),
                'res_model': 'production.request',
                'view_mode': 'form',
                'res_id': created_requests.id,
                'target': 'current',
            }

        return {
            'type': 'ir.actions.act_window',
            'name': _('Production Requests'),
            'res_model': 'production.request',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created_requests.ids)],
            'target': 'current',
        }

    def action_view_production_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Production Requests'),
            'res_model': 'production.request',
            'view_mode': 'list,form',
            'domain': [('picking_id', '=', self.id)],
            'context': {'create': False},
        }
