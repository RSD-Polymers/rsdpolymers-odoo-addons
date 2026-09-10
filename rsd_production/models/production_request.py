# -*- coding: utf-8 -*-
from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError


class ProductionRequest(models.Model):
    _name = 'production.request'
    _description = 'Finished Goods Production Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'create_date desc'

    name = fields.Char(string='Request No.', default='New', readonly=True, copy=False)
    sale_id = fields.Many2one('sale.order', string='Sales Order', required=True, readonly=True, index=True)
    sale_line_id = fields.Many2one('sale.order.line', string='Sales Order Line', required=True, readonly=True)
    product_id = fields.Many2one('product.product', string='Finished Product', required=True, readonly=True)
    product_uom_id = fields.Many2one('uom.uom', string='Unit of Measure', required=True, readonly=True)

    required_qty = fields.Float(string='SO Required Qty', required=True, readonly=True)
    fg_available_qty = fields.Float(string='Packed FG Available', required=True, readonly=True)
    shortage_qty = fields.Float(string='FG Shortage Qty', required=True, readonly=True)
    planned_qty = fields.Float(
        string='Planned Production Qty',
        help='Quantity allocated to this request by Production planning. It may be greater than the shortage when a batch is planned.'
    )

    state = fields.Selection([
        ('requested', 'Requested'),
        ('accepted', 'Accepted'),
        ('planned', 'Planned'),
        ('in_production', 'In Production'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='requested', tracking=True)

    # Production confirmation / commitment information.
    material_ready_date = fields.Date(
        string='Material Ready Date',
        readonly=True,
        tracking=True,
        help='Date committed by Production for making the finished material available to Store/Sales.',
    )
    accepted_by = fields.Many2one(
        'res.users',
        string='Accepted By',
        readonly=True,
        tracking=True,
    )
    accepted_date = fields.Datetime(
        string='Accepted On',
        readonly=True,
        tracking=True,
    )

    mo_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True, index=True)
    requested_by = fields.Many2one('res.users', string='Requested By', readonly=True)
    planned_by = fields.Many2one('res.users', string='Planned By', readonly=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, readonly=True,
        default=lambda self: self.env.company,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('production.request') or 'New'
            vals.setdefault('requested_by', self.env.uid)
            vals.setdefault('state', 'requested')
        return super().create(vals_list)

    def _check_production_user(self):
        user = self.env.user
        if user.has_group('base.group_system') or user.has_group('mrp.group_mrp_manager'):
            return True
        employee = user.employee_id
        department_name = employee.department_id.name.strip().lower() if employee and employee.department_id else ''
        if department_name not in ('production', 'manufacturing'):
            raise UserError(_('Only Production users can accept a Production Request.'))
        return True

    def action_open_sale_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sales Order'),
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.sale_id.id,
            'target': 'current',
        }

    def action_open_mo(self):
        self.ensure_one()
        if not self.mo_id:
            raise UserError(_('No Manufacturing Order is linked to this Production Request.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Manufacturing Order'),
            'res_model': 'mrp.production',
            'view_mode': 'form',
            'res_id': self.mo_id.id,
            'target': 'current',
        }

    def action_accept(self):
        """Open the Production confirmation wizard and collect the committed ready date."""
        self.ensure_one()
        self._check_production_user()
        if self.state != 'requested':
            raise UserError(_('Only Requested Production Requests can be accepted.'))

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
        """Internal method used by the acceptance wizard."""
        self.ensure_one()
        self._check_production_user()
        if self.state != 'requested':
            raise UserError(_('Only Requested Production Requests can be accepted.'))
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

    def action_plan_selected(self):
        requests = self.filtered(lambda r: r.state == 'accepted' and not r.mo_id)
        if not requests:
            raise UserError(_('Select at least one Accepted Production Request without an MO.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Production Planning'),
            'res_model': 'production.request.plan.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_ids': [Command.set(requests.ids)]},
        }

    def action_cancel(self):
        for request in self:
            if request.mo_id and request.mo_id.state not in ('cancel', 'done'):
                raise UserError(_('Cannot cancel %s because its Manufacturing Order is still active.') % request.name)
            request.state = 'cancelled'

    def _sync_state_from_mo(self):
        for request in self:
            if not request.mo_id:
                continue
            if request.mo_id.state == 'done':
                request.state = 'done'
            elif request.mo_id.state in ('progress', 'to_close'):
                request.state = 'in_production'
            elif request.mo_id.state == 'cancel':
                request.state = 'cancelled'
            else:
                # Do not move an accepted request backwards if an MO was linked manually.
                request.state = 'planned'
