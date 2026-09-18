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

        # A Delivery Order has one active Production Request. This keeps all
        # shortage products together on one requirement document. If an older
        # request exists without the new line structure, do not mix the old
        # record into the new structure; a new request will be created.
        request = ProductionRequest.search([
            ('picking_id', '=', self.id),
            ('state', 'not in', ('done', 'cancelled')),
        ], order='id desc', limit=1)
        if request and not request.line_ids:
            request = ProductionRequest.browse()
        if not request:
            sale_move = self.move_ids.filtered(lambda m: m.sale_line_id)[:1]
            if not sale_move or not sale_move.sale_line_id.order_id:
                raise UserError(_('This Delivery Order is not linked to a Sales Order.'))
            request = ProductionRequest.create({
                'sale_id': sale_move.sale_line_id.order_id.id,
                'picking_id': self.id,
                'company_id': self.company_id.id,
            })

        created_lines = ProductionRequestLine.browse()
        moves = self.move_ids.filtered(
            lambda m:
                m.state not in ('done', 'cancel')
                and m.product_id
                and m.sale_line_id
                and m.product_id.is_storable
        )

        for move in moves:
            existing_line = request.line_ids.filtered(
                lambda line: line.sale_line_id == move.sale_line_id
            )[:1]
            if existing_line:
                continue

            required_qty = move.product_uom_qty
            available_qty = self.env['stock.quant']._get_available_quantity(
                move.product_id,
                fg_location,
            )
            available_qty = move.product_id.uom_id._compute_quantity(
                available_qty,
                move.product_uom,
                round=False,
            )
            shortage_qty = max(required_qty - available_qty, 0.0)

            if shortage_qty <= 0:
                continue

            created_lines |= ProductionRequestLine.create({
                'request_id': request.id,
                'sale_line_id': move.sale_line_id.id,
                'product_id': move.product_id.id,
                'product_uom_id': move.product_uom.id,
                'required_qty': required_qty,
                'fg_available_qty': available_qty,
                'shortage_qty': shortage_qty,
            })

        if not created_lines:
            # Do not leave an empty header behind. It can happen when the
            # button is clicked after all shortages have already been covered.
            if not request.line_ids:
                request.unlink()
            raise UserError(
                _('There are no new Packed - FG shortages requiring a Production Request.')
            )

        self.message_post(
            body=_(
                'Production Request <b>%s</b> created/updated with %d shortage line(s).'
            ) % (request.name, len(created_lines))
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Production Request'),
            'res_model': 'production.request',
            'view_mode': 'form',
            'res_id': request.id,
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
