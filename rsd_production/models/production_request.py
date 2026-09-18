# -*- coding: utf-8 -*-
from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError, ValidationError


class ProductionRequest(models.Model):
    _name = 'production.request'
    _description = 'Finished Goods Production Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'create_date desc'

    name = fields.Char(string='Request No.', default='New', readonly=True, copy=False)
    sale_id = fields.Many2one('sale.order', string='Sales Order', required=True, readonly=True, index=True)
    picking_id = fields.Many2one('stock.picking', string='Delivery Order', readonly=True, index=True)
    line_ids = fields.One2many(
        'production.request.line',
        'request_id',
        string='Production Lines',
        copy=True,
    )

    material_ready_date = fields.Date(
        string='Material Ready Date',
        readonly=True,
        tracking=True,
        help='Date committed by Production for making the finished material available to Store/Sales.',
    )
    accepted_by = fields.Many2one('res.users', string='Accepted By', readonly=True, tracking=True)
    accepted_date = fields.Datetime(string='Accepted On', readonly=True, tracking=True)

    state = fields.Selection([
        ('requested', 'Requested'),
        ('accepted', 'Accepted'),
        ('in_production', 'In Production'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='requested', tracking=True)

    requested_by = fields.Many2one('res.users', string='Requested By', readonly=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, readonly=True,
        default=lambda self: self.env.company,
    )

    line_count = fields.Integer(string='Product Lines', compute='_compute_counts')
    execution_count = fields.Integer(string='Execution Documents', compute='_compute_counts')
    mo_count = fields.Integer(string='Manufacturing Orders', compute='_compute_counts')
    pi_count = fields.Integer(string='Packing Instructions', compute='_compute_counts')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('production.request') or 'New'
            vals.setdefault('requested_by', self.env.uid)
            vals.setdefault('state', 'requested')
        return super().create(vals_list)

    def _compute_counts(self):
        for request in self:
            lines = request.line_ids
            mos = lines.mapped('mo_ids').filtered(lambda mo: mo.state != 'cancel')
            pis = lines.mapped('pi_ids').filtered(lambda mo: mo.state != 'cancel')
            request.line_count = len(lines)
            request.mo_count = len(mos)
            request.pi_count = len(pis)
            request.execution_count = len(mos | pis)

    def _check_production_user(self):
        user = self.env.user
        if user.has_group('base.group_system') or user.has_group('mrp.group_mrp_manager'):
            return True
        employee = user.employee_id
        department_name = employee.department_id.name.strip().lower() if employee and employee.department_id else ''
        if department_name not in ('production', 'manufacturing'):
            raise UserError(_('Only Production users can process a Production Request.'))
        return True

    def _check_has_lines(self):
        for request in self:
            if not request.line_ids:
                raise UserError(_('Production Request %s has no product lines.') % request.name)

    def action_accept(self):
        self.ensure_one()
        self._check_production_user()
        if self.state != 'requested':
            raise UserError(_('Only Requested Production Requests can be accepted.'))
        self._check_has_lines()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Accept Production Request'),
            'res_model': 'production.request.accept.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_request_id': self.id,
                'default_material_ready_date': fields.Date.context_today(self),
            },
        }

    def _action_accept_with_date(self, material_ready_date):
        self.ensure_one()
        self._check_production_user()
        if self.state != 'requested':
            raise UserError(_('Only Requested Production Requests can be accepted.'))
        self._check_has_lines()
        if not material_ready_date:
            raise UserError(_('Please enter the Material Ready Date.'))
        if material_ready_date < fields.Date.context_today(self):
            raise UserError(_('Material Ready Date cannot be in the past.'))

        self.write({
            'state': 'accepted',
            'material_ready_date': material_ready_date,
            'accepted_by': self.env.user.id,
            'accepted_date': fields.Datetime.now(),
        })

        date_text = fields.Date.to_string(material_ready_date)
        self.message_post(
            body=_('Production accepted this request. Material Ready Date: <b>%s</b>.') % date_text,
            subtype_xmlid='mail.mt_note',
        )
        if self.sale_id:
            self.sale_id.message_post(
                body=_('Production Request <b>%s</b> was accepted. Material Ready Date: <b>%s</b>.')
                % (self.name, date_text),
                subtype_xmlid='mail.mt_note',
            )
        return True

    def _sync_state_from_lines(self):
        for request in self:
            if request.state in ('cancelled', 'requested'):
                continue

            lines = request.line_ids
            if not lines:
                request.state = 'accepted'
                continue

            executions = lines.mapped('mo_ids') | lines.mapped('pi_ids')
            executions = executions.filtered(lambda doc: doc.state != 'cancel')

            if not executions:
                request.state = 'accepted'
                continue

            all_allocated = all(line.remaining_qty <= 0 for line in lines)
            all_done = all(doc.state == 'done' for doc in executions)

            if all_allocated and all_done:
                request.state = 'done'
            else:
                request.state = 'in_production'

    def action_cancel(self):
        for request in self:
            if request.state == 'done':
                raise UserError(_('Completed Production Requests cannot be cancelled.'))
            active_docs = (request.line_ids.mapped('mo_ids') | request.line_ids.mapped('pi_ids')).filtered(
                lambda doc: doc.state not in ('cancel', 'done')
            )
            if active_docs:
                raise UserError(
                    _('Cannot cancel %s because Manufacturing Orders/Packing Instructions are still active.')
                    % request.name
                )
            request.state = 'cancelled'

    def unlink(self):
        raise UserError(_('Production Requests cannot be deleted. Use Cancel to close the request.'))

    def action_view_mos(self):
        self.ensure_one()
        mos = self.line_ids.mapped('mo_ids').filtered(lambda mo: mo.state != 'cancel')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Manufacturing Orders'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('id', 'in', mos.ids)],
            'context': {'create': False},
        }

    def action_view_pis(self):
        self.ensure_one()
        pis = self.line_ids.mapped('pi_ids').filtered(lambda mo: mo.state != 'cancel')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Packing Instructions'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('id', 'in', pis.ids)],
            'context': {'create': False},
        }


class ProductionRequestLine(models.Model):
    _name = 'production.request.line'
    _description = 'Production Request Line'
    _order = 'id'

    request_id = fields.Many2one(
        'production.request',
        string='Production Request',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sale_line_id = fields.Many2one(
        'sale.order.line',
        string='Sales Order Line',
        readonly=True,
        index=True,
    )
    product_id = fields.Many2one(
        'product.product', string='Finished Product', required=True, readonly=True,
    )
    product_uom_id = fields.Many2one(
        'uom.uom', string='Unit of Measure', required=True, readonly=True,
    )

    required_qty = fields.Float(string='SO Required Qty', required=True, readonly=True)
    fg_available_qty = fields.Float(string='Packed FG Available', required=True, readonly=True)
    shortage_qty = fields.Float(string='FG Shortage Qty', required=True, readonly=True)

    mo_ids = fields.One2many(
        'mrp.production',
        'production_request_line_id',
        string='Manufacturing Orders',
        domain=[('is_packing_order', '=', False)],
        readonly=True,
    )
    pi_ids = fields.One2many(
        'mrp.production',
        'production_request_line_id',
        string='Packing Instructions',
        domain=[('is_packing_order', '=', True)],
        readonly=True,
    )

    mo_qty = fields.Float(string='MO Qty', compute='_compute_execution_qty', store=True)
    pi_qty = fields.Float(string='PI Qty', compute='_compute_execution_qty', store=True)
    allocated_qty = fields.Float(string='Allocated / Fulfilled Qty', compute='_compute_execution_qty', store=True)
    remaining_qty = fields.Float(string='Remaining Qty', compute='_compute_execution_qty', store=True)

    @api.depends(
        'mo_ids.state', 'mo_ids.product_qty', 'mo_ids.product_uom_id',
        'pi_ids.state', 'pi_ids.product_qty', 'pi_ids.product_uom_id',
        'shortage_qty', 'product_uom_id',
    )
    def _compute_execution_qty(self):
        for line in self:
            mo_qty = 0.0
            pi_qty = 0.0
            for mo in line.mo_ids.filtered(lambda doc: doc.state != 'cancel'):
                qty = mo.product_uom_id._compute_quantity(
                    mo.product_qty, line.product_uom_id, round=False
                )
                mo_qty += qty
            for pi in line.pi_ids.filtered(lambda doc: doc.state != 'cancel'):
                qty = pi.product_uom_id._compute_quantity(
                    pi.product_qty, line.product_uom_id, round=False
                )
                pi_qty += qty
            line.mo_qty = mo_qty
            line.pi_qty = pi_qty
            line.allocated_qty = mo_qty + pi_qty
            line.remaining_qty = max(line.shortage_qty - line.allocated_qty, 0.0)

    def _check_execution_allowed(self):
        for line in self:
            if line.request_id.state not in ('accepted', 'in_production'):
                raise UserError(
                    _('Execution documents can only be created for an Accepted or In Production request.')
                )
            if line.remaining_qty <= 0:
                raise UserError(_('No quantity remains to be allocated for %s.') % line.product_id.display_name)

    def action_create_mo(self):
        self.ensure_one()
        self.request_id._check_production_user()
        self._check_execution_allowed()
        return self._open_execution_wizard('mo')

    def action_create_pi(self):
        self.ensure_one()
        self.request_id._check_production_user()
        self._check_execution_allowed()
        return self._open_execution_wizard('pi')

    def _open_execution_wizard(self, execution_type):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Manufacturing Order') if execution_type == 'mo' else _('Create Packing Instruction'),
            'res_model': 'production.request.execution.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_request_line_id': self.id,
                'default_execution_type': execution_type,
                'default_quantity': self.remaining_qty,
            },
        }
