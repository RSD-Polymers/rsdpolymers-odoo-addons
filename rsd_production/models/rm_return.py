# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare

WIP_LOCATION = 'WH/WIP'
RM_LOCATION = 'WH/Main Stock/Raw Materials'


class RmReturn(models.Model):
    _name = 'rm.return'
    _description = 'Raw Material Return'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(default='New', readonly=True, copy=False, tracking=True)
    mo_id = fields.Many2one('mrp.production', required=True, index=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    original_rm_issue_id = fields.Many2one(
        'rm.issue', string='Original RM Issue', required=True,
        domain="[('mo_id', '=', mo_id), ('state', '=', 'issued')]",
    )
    source_location_id = fields.Many2one('stock.location', required=True, readonly=True)
    destination_location_id = fields.Many2one('stock.location', required=True, readonly=True)
    picking_id = fields.Many2one('stock.picking', string='Return Transfer', readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Draft'), ('submitted', 'Submitted to Store'),
        ('received', 'Received'), ('cancelled', 'Cancelled')
    ], default='draft', tracking=True, copy=False)
    requested_by = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    received_by = fields.Many2one('res.users', readonly=True)
    line_ids = fields.One2many('rm.return.line', 'return_id', string='Return Lines')

    @api.model_create_multi
    def create(self, vals_list):
        user = self.env.user
        for vals in vals_list:
            # Workflow fields are server-managed; do not trust RPC-supplied values.
            vals['state'] = 'draft'
            vals['picking_id'] = False
            vals['received_by'] = False
            vals['requested_by'] = user.id
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('rm.return') or 'New'
            company_id = vals.get('company_id') or self.env.company.id
            for field_name, complete_name in (
                ('source_location_id', WIP_LOCATION),
                ('destination_location_id', RM_LOCATION),
            ):
                location = self.env['stock.location'].search([
                    ('complete_name', '=', complete_name),
                    ('company_id', 'in', [company_id, False]),
                ], limit=1)
                if not location:
                    raise UserError(_('Required stock location "%s" was not found.') % complete_name)
                vals[field_name] = location.id
        records = super().create(vals_list)
        for rec in records:
            rec._check_production_user()
            rec._check_mo_state()
            if rec.company_id != rec.mo_id.company_id:
                raise UserError(_('The RM Return company must match the Manufacturing Order company.'))
        return records

    @api.onchange('mo_id', 'original_rm_issue_id')
    def _onchange_issue_locations_and_lines(self):
        for rec in self:
            if rec.state != 'draft' or not rec.original_rm_issue_id:
                continue
            rec._set_default_locations()
            rec.line_ids = [(5, 0, 0)] + [
                (0, 0, {'product_id': line.product_id.id, 'qty': 0.0, 'uom_id': line.uom_id.id})
                for line in rec.original_rm_issue_id.line_ids
            ]

    def _find_location(self, complete_name):
        self.ensure_one()
        location = self.env['stock.location'].search([
            ('complete_name', '=', complete_name),
            ('company_id', 'in', [self.company_id.id, False]),
        ], limit=1)
        if not location:
            raise UserError(_('Required stock location "%s" was not found.') % complete_name)
        return location

    def _set_default_locations(self):
        self.ensure_one()
        self.source_location_id = self._find_location(WIP_LOCATION)
        self.destination_location_id = self._find_location(RM_LOCATION)

    def _check_mo_state(self):
        self.ensure_one()
        if self.mo_id.state not in ('confirmed', 'progress', 'to_close'):
            raise UserError(_('RM Return is available only when the MO is Confirmed, In Progress or To Close.'))
        if self.mo_id.is_packing_order:
            raise UserError(_('RM Return is not available for Packing Orders.'))

    def _check_production_user(self):
        user = self.env.user
        if user.has_group('base.group_system'):
            return
        employee = user.employee_id
        department = employee.department_id.name.strip().lower() if employee and employee.department_id else ''
        if not user.has_group('mrp.group_mrp_user') or department != 'production':
            raise UserError(_('Only Production department users can create or submit RM Return requests.'))

    def _check_store_user(self):
        user = self.env.user
        if user.has_group('base.group_system') or user.has_group('stock.group_stock_manager'):
            return
        employee = user.employee_id
        department = employee.department_id.name.strip().lower() if employee and employee.department_id else ''
        if not user.has_group('stock.group_stock_user') or department != 'store':
            raise UserError(_('Only Store department users can process RM Returns.'))

    def _workflow_write(self, vals):
        """Internal workflow write that bypasses this model's public write guard."""
        return super(RmReturn, self).write(vals)

    def _get_issue_qty(self, product, uom):
        """Quantity actually transferred by the selected, completed RM Issue."""
        self.ensure_one()
        transfer = self.original_rm_issue_id.internal_transfer_ref
        qty = 0.0
        if transfer and transfer.state == 'done':
            for move in transfer.move_ids.filtered(lambda m: m.state == 'done' and m.product_id == product):
                qty += move.product_uom._compute_quantity(move.quantity, uom, round=False)
        return qty

    def _get_previously_returned_qty(self, product, uom):
        self.ensure_one()
        returns = self.env['rm.return'].search([
            ('id', '!=', self.id),
            ('original_rm_issue_id', '=', self.original_rm_issue_id.id),
            ('state', 'in', ['submitted', 'received']),
        ])
        qty = 0.0
        for ret in returns:
            for line in ret.line_ids.filtered(lambda ln: ln.product_id == product and ln.qty > 0):
                qty += line.uom_id._compute_quantity(line.qty, uom, round=False)
        return qty

    def _validate_return_lines(self):
        self.ensure_one()
        issue = self.original_rm_issue_id
        if issue.mo_id != self.mo_id:
            raise UserError(_('The selected RM Issue must belong to this Manufacturing Order.'))
        if issue.state != 'issued':
            raise UserError(_('Only completed and issued RM Issue requests can be returned.'))
        transfer = issue.internal_transfer_ref
        if not transfer or transfer.state != 'done':
            raise UserError(_('The original RM Issue transfer must be completed.'))

        source = self._find_location(WIP_LOCATION)
        destination = self._find_location(RM_LOCATION)
        self.source_location_id = source
        self.destination_location_id = destination
        lines = self.line_ids.filtered(lambda line: line.qty > 0)
        if not lines:
            raise UserError(_('Enter a return quantity greater than zero on at least one line.'))

        issued_products = set(issue.line_ids.mapped('product_id').ids)
        Quant = self.env['stock.quant']
        for line in lines:
            if line.product_id.id not in issued_products:
                raise UserError(_('%s was not included in the selected RM Issue.') % line.product_id.display_name)
            if line.uom_id.category_id != line.product_id.uom_id.category_id:
                raise UserError(_('The return unit of measure is incompatible with %s.') % line.product_id.display_name)

            issue_qty = self._get_issue_qty(line.product_id, line.uom_id)
            already_returned = self._get_previously_returned_qty(line.product_id, line.uom_id)
            max_by_issue = max(issue_qty - already_returned, 0.0)
            if float_compare(line.qty, max_by_issue, precision_rounding=line.uom_id.rounding) > 0:
                raise UserError(_(
                    'Return quantity for %(product)s exceeds the remaining quantity issued: %(qty)s %(uom)s.'
                ) % {
                    'product': line.product_id.display_name,
                    'qty': max_by_issue,
                    'uom': line.uom_id.name,
                })

            available = Quant._get_available_quantity(line.product_id, source, strict=True)
            available = line.product_id.uom_id._compute_quantity(available, line.uom_id, round=False)
            if float_compare(line.qty, available, precision_rounding=line.uom_id.rounding) > 0:
                raise UserError(_(
                    'Only %(available)s %(uom)s of %(product)s is available at %(location)s; requested return is %(requested)s.'
                ) % {
                    'available': available, 'uom': line.uom_id.name,
                    'product': line.product_id.display_name,
                    'location': source.complete_name, 'requested': line.qty,
                })

    def action_submit(self):
        self.ensure_one()
        self._check_production_user()
        self._check_mo_state()
        if self.state != 'draft':
            raise UserError(_('Only Draft RM Returns can be submitted.'))
        self._validate_return_lines()

        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'), ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not picking_type:
            raise UserError(_('No Internal Transfer operation type was found for this company.'))

        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'origin': self.name,
            'company_id': self.company_id.id,
            'location_id': self.source_location_id.id,
            'location_dest_id': self.destination_location_id.id,
        })
        for line in self.line_ids.filtered(lambda ln: ln.qty > 0):
            self.env['stock.move'].create({
                'name': line.product_id.display_name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty,
                'product_uom': line.uom_id.id,
                'location_id': self.source_location_id.id,
                'location_dest_id': self.destination_location_id.id,
                'picking_id': picking.id,
                'company_id': self.company_id.id,
            })

        # Establish the unique request/picking link before confirming the picking.
        self._workflow_write({'picking_id': picking.id})
        picking._link_rm_return_workflow(self)
        picking.action_confirm()
        picking.action_assign()
        self._workflow_write({'state': 'submitted'})
        self.message_post(body=_('Return submitted to Store. Transfer: %s') % picking.name)
        return {
            'type': 'ir.actions.act_window', 'name': _('Return Transfer'),
            'res_model': 'stock.picking', 'view_mode': 'form',
            'res_id': picking.id, 'target': 'current',
        }

    def action_mark_received(self):
        self._check_store_user()
        for rec in self:
            if rec.state != 'submitted' or not rec.picking_id or rec.picking_id.state != 'done':
                raise UserError(_('The return transfer must be validated by Store before marking the return as received.'))
            rec._workflow_write({'state': 'received', 'received_by': self.env.user.id})
        return True

    def write(self, vals):
        workflow_fields = {'state', 'picking_id', 'requested_by', 'received_by'}
        if workflow_fields.intersection(vals):
            raise UserError(_('Workflow fields can only be changed through RM Return workflow buttons.'))
        protected = {'mo_id', 'company_id', 'original_rm_issue_id', 'source_location_id',
                     'destination_location_id', 'line_ids'}
        if any(rec.state != 'draft' for rec in self) and protected.intersection(vals):
            raise UserError(_('Submitted RM Return requests cannot be modified.'))
        return super().write(vals)

    def action_cancel(self):
        for rec in self:
            if rec.state == 'draft':
                rec._check_production_user()
            else:
                rec._check_store_user()
            if rec.state in ('received', 'cancelled'):
                raise UserError(_('A received or cancelled return cannot be cancelled.'))
            if rec.picking_id:
                if rec.picking_id.state == 'done':
                    raise UserError(_('A return with a completed stock transfer cannot be cancelled. Mark it as Received instead.'))
                if rec.picking_id.state != 'cancel':
                    raise UserError(_('Cancel the linked Internal Transfer before cancelling this return.'))
            rec._workflow_write({'state': 'cancelled'})
        return True


class RmReturnLine(models.Model):
    _name = 'rm.return.line'
    _description = 'Raw Material Return Line'

    return_id = fields.Many2one('rm.return', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    qty = fields.Float(required=True, default=0.0)
    uom_id = fields.Many2one('uom.uom', required=True)

    @api.model_create_multi
    def create(self, vals_list):
        Return = self.env['rm.return']
        for vals in vals_list:
            parent = Return.browse(vals.get('return_id'))
            if not parent or parent.state != 'draft':
                raise UserError(_('Return lines can only be added while the request is in Draft.'))
        return super().create(vals_list)

    @api.constrains('qty')
    def _check_qty(self):
        for line in self:
            if line.qty < 0:
                raise ValidationError(_('Return quantity cannot be negative.'))

    def write(self, vals):
        if any(line.return_id.state != 'draft' for line in self):
            raise UserError(_('Return lines can only be edited in Draft.'))
        if 'return_id' in vals:
            target = self.env['rm.return'].browse(vals['return_id'])
            if not target or target.state != 'draft':
                raise UserError(_('Return lines can only be moved to another Draft request.'))
        return super().write(vals)

    def unlink(self):
        if any(line.return_id.state != 'draft' for line in self):
            raise UserError(_('Return lines can only be removed in Draft.'))
        return super().unlink()
