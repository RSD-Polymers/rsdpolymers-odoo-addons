# -\*- coding: utf-8 -\*-

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

    rejection_reason = fields.Text(string='Rejection Reason', readonly=True, tracking=True)
    rejected_by = fields.Many2one('res.users', string='Rejected By', readonly=True, tracking=True)
    rejected_date = fields.Datetime(string='Rejected On', readonly=True, tracking=True)

    production_done_by = fields.Many2one('res.users', string='Production Completed By', readonly=True, tracking=True)
    production_done_date = fields.Datetime(string='Production Completed On', readonly=True, tracking=True)
    store_acknowledged = fields.Boolean(string='Store Acknowledged', readonly=True, tracking=True, default=False)
    store_acknowledged_by = fields.Many2one('res.users', string='Store Acknowledged By', readonly=True, tracking=True)
    store_acknowledged_date = fields.Datetime(string='Store Acknowledged On', readonly=True, tracking=True)
    can_acknowledge_store = fields.Boolean(
        string='Can Acknowledge as Store', compute='_compute_can_acknowledge_store',
    )
    # Retained for compatibility with existing records; Sales acknowledgement is no longer used.
    sales_acknowledged = fields.Boolean(string='Sales Acknowledged', readonly=True, tracking=True, default=False)
    sales_acknowledged_by = fields.Many2one('res.users', string='Sales Acknowledged By', readonly=True, tracking=True)
    sales_acknowledged_date = fields.Datetime(string='Sales Acknowledged On', readonly=True, tracking=True)



    state = fields.Selection([

        ('requested', 'Requested'),

        ('accepted', 'Accepted'),

        ('in_production', 'In Production'),

        ('production_done', 'Production Done'),

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



    @api.model
    def _get_financial_year(self, request_date=None):
        request_date = fields.Date.to_date(request_date or fields.Date.context_today(self))
        if request_date.month >= 4:
            return request_date.year, request_date.year + 1
        return request_date.year - 1, request_date.year

    @api.model
    def _next_production_request_name(self, request_date=None):
        request_date = fields.Date.to_date(request_date or fields.Date.context_today(self))
        fy_start, fy_end = self._get_financial_year(request_date)

        sequence = self.env['ir.sequence'].search([
            ('code', '=', 'production.request'),
            '|',
            ('company_id', '=', self.env.company.id),
            ('company_id', '=', False),
        ], order='company_id desc, id', limit=1)
        if not sequence:
            return 'New'

        generated = sequence.with_context(
            ir_sequence_date=request_date,
        ).next_by_id()
        if not generated:
            return 'New'

        fy_prefix = f'PR/{fy_start}-{str(fy_end)[-2:]}/'
        numeric_part = generated.rsplit('/', 1)[-1]
        return f'{fy_prefix}{numeric_part}'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self._next_production_request_name()
            vals.setdefault('requested_by', self.env.uid)
            vals.setdefault('state', 'requested')
        return super().create(vals_list)



    @api.model
    def get_dashboard_data(self):
        """Return the data used by the Manufacturing Production Request dashboard.

        The method deliberately uses the current user's access rights and record
        rules; it does not use sudo, so the dashboard shows only records the
        logged-in user is allowed to see.
        """
        today = fields.Date.context_today(self)
        Line = self.env['production.request.line']

        data = {
            'today': fields.Date.to_string(today),
            'total': self.search_count([]),
            'requested': self.search_count([('state', '=', 'requested')]),
            'accepted': self.search_count([('state', '=', 'accepted')]),
            'in_production': self.search_count([('state', '=', 'in_production')]),
            'done': self.search_count([('state', '=', 'done')]),
            'cancelled': self.search_count([('state', '=', 'cancelled')]),
            'material_ready_pending': self.search_count([('state', '=', 'requested')]),
            'overdue': self.search_count([
                ('material_ready_date', '<', today),
                ('state', 'not in', ['done', 'cancelled']),
            ]),
            'products': [],
            'recent': [],
        }

        product_groups = Line.read_group(
            domain=[],
            fields=['product_id', 'required_qty:sum', 'request_id:count_distinct'],
            groupby=['product_id'],
            orderby='required_qty desc',
            limit=10,
        )
        for group in product_groups:
            product = group.get('product_id')
            if not product:
                continue
            data['products'].append({
                'id': product[0],
                'name': product[1],
                'request_count': group.get('request_id_count_distinct', 0),
                'required_qty': group.get('required_qty_sum', 0.0),
            })

        recent_requests = self.search([], order='create_date desc, id desc', limit=10)
        state_labels = dict(self._fields['state'].selection)
        for request in recent_requests:
            first_line = request.line_ids[:1]
            data['recent'].append({
                'id': request.id,
                'name': request.name,
                'product': first_line.product_id.display_name if first_line else '',
                'state_label': state_labels.get(request.state, request.state or ''),
            })

        return data


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
        partners = self._get_notification_partners()
        accepted_body = _('Production Request <b>%s</b> was accepted. Material Ready Date: <b>%s</b>.') % (
            self.name, date_text)
        self.sudo().message_post(
            body=accepted_body,
            partner_ids=partners.ids,
            subtype_xmlid='mail.mt_comment',
        )
        if self.sale_id:
            self.sale_id.sudo().message_post(
                body=accepted_body,
                partner_ids=partners.ids,
                subtype_xmlid='mail.mt_comment',
            )

        return True



    def _get_notification_partners(self):
        self.ensure_one()
        partners = self.env['res.partner']
        if self.requested_by and self.requested_by.partner_id:
            partners |= self.requested_by.partner_id
        if self.sale_id and self.sale_id.user_id and self.sale_id.user_id.partner_id:
            partners |= self.sale_id.user_id.partner_id
        return partners

    def action_reject(self):
        self.ensure_one()
        self._check_production_user()
        if self.state in ('done', 'cancelled', 'production_done'):
            raise UserError(_('This Production Request can no longer be rejected.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject Production Request'),
            'res_model': 'production.request.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def _action_reject(self, reason):
        self.ensure_one()
        self._check_production_user()
        if self.state in ('done', 'cancelled', 'production_done'):
            raise UserError(_('This Production Request can no longer be rejected.'))
        active_docs = (self.line_ids.mapped('mo_ids') | self.line_ids.mapped('pi_ids')).filtered(
            lambda doc: doc.state not in ('cancel', 'done')
        )
        if active_docs:
            raise UserError(_(
                'Cannot reject %s because Manufacturing Orders/Packing Instructions are still active.'
            ) % self.name)
        values = {
            'state': 'cancelled',
            'rejection_reason': reason,
            'rejected_by': self.env.user.id,
            'rejected_date': fields.Datetime.now(),
        }
        self.sudo().write(values)
        partners = self._get_notification_partners()
        body = _('Production Request <b>%s</b> was rejected by %s.<br/><b>Reason:</b> %s') % (
            self.name, self.env.user.display_name, reason)
        self.sudo().message_post(body=body, partner_ids=partners.ids, subtype_xmlid='mail.mt_comment')
        if self.sale_id:
            self.sale_id.sudo().message_post(
                body=body, partner_ids=partners.ids, subtype_xmlid='mail.mt_comment')
        return True

    def _all_execution_documents_done(self):
        self.ensure_one()
        lines = self.line_ids
        executions = lines.mapped('mo_ids') | lines.mapped('pi_ids')
        executions = executions.filtered(lambda doc: doc.state != 'cancel')
        return bool(lines and executions and all(line.remaining_qty <= 1e-6 for line in lines)
                    and all(doc.state == 'done' for doc in executions))

    def _schedule_store_ack_activity(self):
        """Create one Approve activity for the eligible request creator."""
        Activity = self.env['mail.activity'].sudo()
        activity_type = self.env.ref(
            'web_studio.mail_activity_data_approve'
        )
        store_group = self.env.ref(
            'rsd_production.group_production_request_store_acknowledger'
        )

        for request in self:
            # Do not create duplicate acknowledgement activities.
            existing = Activity.search([
                ('production_request_id', '=', request.id),
                ('activity_type_id', '=', activity_type.id),
            ], limit=1)

            if existing:
                continue

            # Assign the activity to the actual request creator only.
            store_user = request.create_uid

            if (
                    not store_user
                    or not store_user.active
                    or store_group not in store_user.groups_id
            ):
                raise UserError(_(
                    'Production Request %(request)s cannot be marked as '
                    'Production Done because its creator must be an active '
                    'member of the Production Request Store Acknowledger group.'
                ) % {'request': request.name})

            # Attach the activity to the linked Delivery Order when available.
            target = request.picking_id or request
            model = 'stock.picking' if request.picking_id else 'production.request'

            Activity.create({
                'activity_type_id': activity_type.id,
                'res_model_id': self.env['ir.model']._get_id(model),
                'res_id': target.id,
                'user_id': store_user.id,
                'summary': _('Acknowledge Production Request %s') % request.name,
                'note': _(
                    'Please acknowledge completion of Production Request '
                    '%(request)s for Sales Order %(sale)s. '
                    'This activity is explicitly linked to the Production Request.'
                ) % {
                            'request': request.name,
                            'sale': request.sale_id.display_name or '',
                        },
                'date_deadline': fields.Date.context_today(request),
                'production_request_id': request.id,
            })

    def action_mark_production_done(self):
        for request in self:
            request._check_production_user()
            if request.state not in ('accepted', 'in_production'):
                raise UserError(_('Only accepted or in-production requests can be marked Production Done.'))

            execution_creation_enabled = self.env['ir.config_parameter'].sudo().get_param(
                'rsd_production.allow_production_request_mo_pi', 'False'
            ) == 'True'
            if execution_creation_enabled and not request._all_execution_documents_done():
                raise UserError(_(
                    'All required quantities must be allocated and all linked '
                    'Manufacturing Orders/Packing Instructions must be Done first.'
                ))

            request.sudo().write({
                'state': 'production_done',
                'production_done_by': self.env.user.id,
                'production_done_date': fields.Datetime.now(),
            })
            request._schedule_store_ack_activity()
            partners = request._get_notification_partners()
            body = _(
                'Production Request <b>%s</b> has been marked Production Done. '
                'Store acknowledgement is required to close the request.'
            ) % request.name
            request.sudo().message_post(
                body=body, partner_ids=partners.ids, subtype_xmlid='mail.mt_comment')
            if request.sale_id:
                request.sale_id.sudo().message_post(
                    body=body, partner_ids=partners.ids, subtype_xmlid='mail.mt_comment')
        return True

    def _is_authorized_store_user(self, user):
        self.ensure_one()
        return user.has_group(
            'rsd_production.group_production_request_store_acknowledger'
        )

    @api.depends_context('uid')
    def _compute_can_acknowledge_store(self):
        user = self.env.user
        for request in self:
            request.can_acknowledge_store = bool(
                request.state == 'production_done'
                and not request.store_acknowledged
                and request._is_authorized_store_user(user)
            )

    def _check_store_acknowledger(self):
        self.ensure_one()
        if not self._is_authorized_store_user(self.env.user):
            raise UserError(_(
                'Only members of the Production Request Store Acknowledger group '
                'can acknowledge completion.'
            ))

    def action_acknowledge_store(self):
        for request in self:
            if request.state not in ('production_done', 'done'):
                raise UserError(_(
                    'Store can acknowledge only after Production marks '
                    'the request done.'
                ))

            request._check_store_acknowledger()

            if not request.store_acknowledged:
                request.sudo().write({
                    'store_acknowledged': True,
                    'store_acknowledged_by': self.env.user.id,
                    'store_acknowledged_date': fields.Datetime.now(),
                })

                request.sudo().message_post(
                    body=_(
                        'Store acknowledged completion of Production Request '
                        '<b>%s</b>.'
                    ) % request.name,
                    partner_ids=request._get_notification_partners().ids,
                    subtype_xmlid='mail.mt_comment',
                )

            # Find only the Approve activity linked to this request.
            approve_type = self.env.ref(
                'web_studio.mail_activity_data_approve',
                raise_if_not_found=False,
            )

            if (
                    approve_type
                    and not self.env.context.get('skip_activity_completion')
            ):
                activities = self.env['mail.activity'].sudo().search([
                    ('production_request_id', '=', request.id),
                    ('activity_type_id', '=', approve_type.id),
                ])

                if activities:
                    activities.with_context(
                        skip_production_request_ack_sync=True
                    ).action_feedback(
                        feedback=_(
                            'Acknowledged through the Production Request button.'
                        )
                    )

            # Close the request after Store acknowledgement.
            request._close_if_acknowledged()

        return True

    def _close_if_acknowledged(self):
        for request in self:
            if request.state == 'production_done' and request.store_acknowledged:
                request.sudo().write({'state': 'done'})
                request.sudo().message_post(
                    body=_('Production Request <b>%s</b> is now closed after Store acknowledgement.') % request.name,
                    partner_ids=request._get_notification_partners().ids,
                    subtype_xmlid='mail.mt_comment')

    def _sync_state_from_lines(self):

        for request in self:

            if request.state in ('cancelled', 'requested', 'production_done', 'done'):

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



            # Completion is a deliberate Production action; do not close automatically.
            request.state = 'in_production'



    def action_cancel(self):
        # Keep legacy calls safe, but route users through the reason-required Reject wizard.
        return self.action_reject()


    def unlink(self):

        raise UserError(_('Production Requests cannot be deleted. Use Reject to close the request.'))



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

    def action_open_production_request(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Production Request'),
            'res_model': 'production.request',
            'view_mode': 'form',
            'res_id': self.request_id.id,
            'target': 'current',
        }



    sale_id = fields.Many2one(

        'sale.order',

        string='Sales Order',

        related='request_id.sale_id',

        store=True,

        readonly=True,

        index=True,

    )

    picking_id = fields.Many2one(

        'stock.picking',

        string='Delivery Order',

        related='request_id.picking_id',

        store=True,

        readonly=True,

        index=True,

    )

    material_ready_date = fields.Date(

        string='Material Ready Date',

        related='request_id.material_ready_date',

        store=True,

        readonly=True,

    )

    state = fields.Selection(

        string='Status',

        related='request_id.state',

        store=True,

        readonly=True,

    )

    execution_creation_enabled = fields.Boolean(
        string='MO/PI Creation Enabled',
        compute='_compute_execution_creation_enabled',
    )

    @api.depends_context('uid')
    def _compute_execution_creation_enabled(self):
        enabled = self.env['ir.config_parameter'].sudo().get_param(
            'rsd_production.allow_production_request_mo_pi', 'False'
        ) == 'True'
        for line in self:
            line.execution_creation_enabled = enabled

    def _check_execution_creation_enabled(self):
        enabled = self.env['ir.config_parameter'].sudo().get_param(
            'rsd_production.allow_production_request_mo_pi', 'False'
        ) == 'True'
        if not enabled:
            raise UserError(_(
                'Creating Manufacturing Orders and Packing Instructions from Production Requests is disabled. '
                'An administrator can enable it in Manufacturing Settings.'
            ))

    requested_by = fields.Many2one(

        'res.users',

        string='Requested By',

        related='request_id.requested_by',

        store=True,

        readonly=True,

    )

    accepted_by = fields.Many2one(

        'res.users',

        string='Accepted By',

        related='request_id.accepted_by',

        store=True,

        readonly=True,

    )



    product_packaging_id = fields.Many2one(

        'product.packaging',

        string='Packaging',

        related='sale_line_id.product_packaging_id',

        store=True,

        readonly=True,

    )

    product_packaging_qty = fields.Float(

        string='Packaging Qty',

        related='sale_line_id.product_packaging_qty',

        store=True,

        readonly=True,

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

    required_qty = fields.Float(
        string='SO Required Qty',
        required=True,
    )

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
            line._check_execution_creation_enabled()

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
