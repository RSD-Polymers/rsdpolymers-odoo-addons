# -*- coding: utf-8 -*-
from odoo import api, fields, models, _, Command
from odoo.exceptions import AccessError, UserError, ValidationError


class ProductionOutputForm(models.Model):
    _name = 'production.output.form'
    _description = 'Production Output Form'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(default='New', readonly=True, copy=False, tracking=True)
    production_id = fields.Many2one('mrp.production', required=True, ondelete='restrict', index=True, tracking=True)
    product_id = fields.Many2one(related='production_id.product_id', store=True, readonly=True)
    lot_id = fields.Many2one('stock.lot', string='Batch / Lot', readonly=True)
    production_date = fields.Datetime(readonly=True)
    planned_output_qty = fields.Float(readonly=True)
    actual_output_qty = fields.Float(readonly=True)
    output_uom_id = fields.Many2one('uom.uom', readonly=True)
    raw_line_ids = fields.One2many('production.output.form.raw.line', 'output_form_id', copy=True)
    variance_reason_ids = fields.One2many('production.output.form.variance.reason', 'output_form_id', copy=True)
    variance_tracking_enabled = fields.Boolean(readonly=True)
    remarks = fields.Text()
    rejection_reason = fields.Text(readonly=True, tracking=True)
    return_reason = fields.Text(string='Send Back Reason', readonly=True, tracking=True)
    returned_by = fields.Many2one('res.users', string='Returned By', readonly=True, tracking=True)
    returned_on = fields.Datetime(string='Returned On', readonly=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'), ('submitted', 'Submitted'), ('rejected', 'Rejected'), ('returned', 'Returned'),
        ('approved', 'Approved'), ('produced', 'Produced'), ('cancelled', 'Cancelled')
    ], default='draft', required=True, tracking=True, index=True)
    prepared_by = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    submitted_by = fields.Many2one('res.users', readonly=True)
    submitted_on = fields.Datetime(readonly=True)
    approved_by = fields.Many2one('res.users', readonly=True)
    approved_on = fields.Datetime(readonly=True)
    produced_on = fields.Datetime(readonly=True)
    variance_total = fields.Float(compute='_compute_variance_total', store=True)
    is_locked = fields.Boolean(compute='_compute_is_locked')
    qa_verified = fields.Boolean(string='QA Verified', compute='_compute_qa_verified')

    @api.depends('raw_line_ids.variance_qty')
    def _compute_variance_total(self):
        for rec in self:
            rec.variance_total = sum(rec.raw_line_ids.mapped('variance_qty'))

    @api.depends('state')
    def _compute_is_locked(self):
        for rec in self:
            rec.is_locked = rec.state in ('submitted', 'approved', 'produced')

    @api.depends('production_id')
    def _compute_qa_verified(self):
        inspection_model = self.env['qa.manufacturing.inspection'].sudo()
        for rec in self:
            rec.qa_verified = bool(inspection_model.search_count([
                ('production_id', '=', rec.production_id.id),
                ('state', '=', 'verified'),
            ])) if rec.production_id else False

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.user.has_group('mrp.group_mrp_user') or self.env.user.has_group('mrp.group_mrp_manager') or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Only Production users can create Output Forms.'))
        for vals in vals_list:
            mo = self.env['mrp.production'].browse(vals.get('production_id')).exists()
            if not mo:
                raise ValidationError(_('Select a valid Manufacturing Order.'))
            mo._check_output_form_eligibility()
            if self.search_count([('production_id', '=', mo.id), ('state', '!=', 'cancelled')]):
                raise UserError(_('An Output Form already exists for this Manufacturing Order.'))
            snapshot = self._snapshot_values(mo)
            vals.update(snapshot)
            vals.update({
                'name': self.env['ir.sequence'].next_by_code('production.output.form') or _('New'),
                'state': 'draft',
                'prepared_by': self.env.user.id,
                'submitted_by': False, 'submitted_on': False,
                'approved_by': False, 'approved_on': False, 'produced_on': False,
            })
        return super().create(vals_list)

    @api.model
    def _snapshot_values(self, mo):
        enabled = self.env['ir.config_parameter'].sudo().get_param('rsd_production.enable_rm_consumption_variance_tracking') == 'True'
        lines = []
        for move in mo.move_raw_ids.filtered(lambda m: m.state != 'cancel' and m.product_id):
            planned = move.product_uom_qty
            actual = move.quantity
            lines.append(Command.create({
                'product_id': move.product_id.id,
                'planned_qty': planned,
                'actual_qty': actual,
                'variance_qty': max(actual - planned, 0.0),
                'uom_id': move.product_uom.id,
                'raw_move_id': move.id,
            }))
        return {
            'lot_id': mo.lot_producing_id.id,
            'production_date': mo.date_start or fields.Datetime.now(),
            'planned_output_qty': mo.product_qty,
            'actual_output_qty': mo.qty_producing,
            'output_uom_id': mo.product_uom_id.id,
            'variance_tracking_enabled': enabled,
            'raw_line_ids': [Command.clear()] + lines,
        }

    def _check_coordinator(self):
        if not (self.env.user.has_group('mrp.group_mrp_user') or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Only Production users can prepare Output Forms.'))

    def write(self, vals):
        protected = {
            'production_id', 'lot_id', 'production_date', 'planned_output_qty',
            'actual_output_qty', 'output_uom_id', 'raw_line_ids', 'state',
            'approved_by', 'approved_on', 'produced_on', 'submitted_by',
            'submitted_on', 'prepared_by', 'name', 'return_reason', 'returned_by', 'returned_on',
        }
        for rec in self:
            if rec.state in ('submitted', 'approved', 'produced') and protected.intersection(vals):
                raise UserError(_('This Output Form is locked. Use the authorized workflow actions.'))
            if 'state' in vals:
                raise AccessError(_('Output Form status can only be changed through its workflow buttons.'))
            if rec.state not in ('draft', 'rejected', 'returned') and any(k in vals for k in ('remarks', 'variance_reason_ids')):
                raise UserError(_('This Output Form is locked.'))
        return super().write(vals)

    def action_submit(self):
        self._check_coordinator()
        for rec in self:
            if rec.state not in ('draft', 'rejected', 'returned'):
                raise UserError(_('Only Draft, Rejected or Returned Output Forms can be submitted.'))
            rec.production_id._check_output_form_eligibility()
            # Re-capture all values after a rejection so approval applies to the
            # corrected, current MO snapshot rather than the previous submission.
            rec.write(self._snapshot_values(rec.production_id))
            if rec.variance_tracking_enabled and rec.variance_total > 0:
                if self.env['ir.config_parameter'].sudo().get_param('rsd_production.require_rm_consumption_variance_reason', 'True') == 'True':
                    for raw_line in rec.raw_line_ids.filtered(lambda line: line.variance_qty > 0):
                        explained = sum(rec.variance_reason_ids.filtered(lambda reason: reason.product_id == raw_line.product_id).mapped('quantity'))
                        if explained + 1e-6 < raw_line.variance_qty:
                            raise ValidationError(_('Provide quantity-wise reasons covering the additional consumption of %s.') % raw_line.product_id.display_name)
            super(ProductionOutputForm, rec).write({'state': 'submitted', 'submitted_by': self.env.user.id, 'submitted_on': fields.Datetime.now(), 'rejection_reason': False})
            rec.message_post(body=_('Output Form submitted for Manager approval. The Output Form and Manufacturing Order are now locked until Manager rejection or Send Back.'))
        return True

    def action_approve(self):
        if not (self.env.user.has_group('mrp.group_mrp_manager') or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Only a Manufacturing Manager or System Administrator can approve Output Forms.'))
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only submitted Output Forms can be approved.'))
            rec.production_id._check_output_form_eligibility()
            super(ProductionOutputForm, rec).write({'state': 'approved', 'approved_by': self.env.user.id, 'approved_on': fields.Datetime.now()})
            rec.message_post(body=_('Output Form approved. Only an authorised Production Supervisor can now use Produce All.'))
        return True

    def action_reject(self):
        self.ensure_one()
        if not (self.env.user.has_group('mrp.group_mrp_manager') or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Only a Manufacturing Manager or System Administrator can reject Output Forms.'))
        return {'type': 'ir.actions.act_window', 'name': _('Reject Output Form'), 'res_model': 'production.output.form.reject.wizard', 'view_mode': 'form', 'target': 'new', 'context': {'default_output_form_id': self.id}}

    def action_send_back(self):
        self.ensure_one()
        if not (self.env.user.has_group('mrp.group_mrp_manager') or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Only a Manufacturing Manager or System Administrator can send back an Output Form.'))
        if self.state not in ('submitted', 'approved'):
            raise UserError(_('Only Submitted or Approved Output Forms can be sent back.'))
        if self.production_id.state == 'done':
            raise UserError(_('A produced Manufacturing Order cannot be sent back through the Output Form workflow.'))
        inspection = self.env['qa.manufacturing.inspection'].sudo().search(
            [('production_id', '=', self.production_id.id)], limit=1
        )
        # Once QA has verified the inspection, sending back is permanently blocked.
        if inspection and inspection.state == 'verified':
            raise UserError(_('This Output Form cannot be sent back because QA has already verified the Manufacturing Order.'))
        # QA must not have started its post-production review. Pending is the
        # only safe state; rejected/rework/under_review mean QA engaged.
        if inspection and inspection.state != 'pending':
            raise UserError(_(
                'This Output Form cannot be sent back because QA Inspection is already %s. '
                'Contact QA to follow the controlled QA workflow.'
            ) % dict(inspection._fields['state'].selection).get(inspection.state, inspection.state))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Back Output Form'),
            'res_model': 'production.output.form.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_output_form_id': self.id},
        }

    def _mark_produced_after_completion(self):
        """Internal completion hook called only after standard MO completion."""
        if not (self.env.user.has_group('rsd_quality.group_unloading_request_supervisor') or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Only an authorised Production Supervisor or System Administrator can finalize an Output Form.'))
        for rec in self:
            if rec.state != 'approved' or rec.production_id.state != 'done':
                continue
            super(ProductionOutputForm, rec).write({
                'state': 'produced', 'produced_on': fields.Datetime.now(),
            })
        return True

    def action_cancel(self):
        self._check_coordinator()
        for rec in self:
            if rec.state not in ('draft', 'rejected', 'returned'):
                raise UserError(_('Only Draft or Rejected Output Forms can be cancelled.'))
            super(ProductionOutputForm, rec).write({'state': 'cancelled'})
        return True

    def action_refresh_snapshot(self):
        self._check_coordinator()
        for rec in self:
            if rec.state not in ('draft', 'rejected', 'returned'):
                raise UserError(_('Snapshot can only be refreshed before submission.'))
            rec.write(self._snapshot_values(rec.production_id))
        return True

    def unlink(self):
        if any(rec.state in ('submitted', 'approved', 'produced', 'returned') for rec in self):
            raise UserError(_('Submitted, approved or produced Output Forms cannot be deleted.'))
        return super().unlink()


class ProductionOutputFormRawLine(models.Model):
    _name = 'production.output.form.raw.line'
    _description = 'Output Form Raw Material Snapshot'
    _order = 'id'

    output_form_id = fields.Many2one('production.output.form', required=True, ondelete='cascade')
    raw_move_id = fields.Many2one('stock.move', readonly=True, ondelete='restrict')
    product_id = fields.Many2one('product.product', required=True, readonly=True)
    planned_qty = fields.Float(readonly=True)
    actual_qty = fields.Float(readonly=True)
    variance_qty = fields.Float(readonly=True)
    uom_id = fields.Many2one('uom.uom', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            form = self.env['production.output.form'].browse(vals.get('output_form_id'))
            if form and form.state not in ('draft', 'rejected', 'returned'):
                raise UserError(_('Raw material snapshots cannot be changed after submission.'))
        return super().create(vals_list)

    def write(self, vals):
        if any(line.output_form_id.state not in ('draft', 'rejected', 'returned') for line in self):
            raise UserError(_('Raw material snapshots cannot be changed after submission.'))
        return super().write(vals)

    def unlink(self):
        if any(line.output_form_id.state not in ('draft', 'rejected', 'returned') for line in self):
            raise UserError(_('Raw material snapshots cannot be deleted after submission.'))
        return super().unlink()


class ProductionOutputFormVarianceReason(models.Model):
    _name = 'production.output.form.variance.reason'
    _description = 'Output Form Consumption Variance Reason'

    output_form_id = fields.Many2one('production.output.form', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    quantity = fields.Float(required=True)
    reason = fields.Text(required=True)
    uom_id = fields.Many2one('uom.uom')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            form = self.env['production.output.form'].browse(vals.get('output_form_id'))
            if form and form.state not in ('draft', 'rejected', 'returned'):
                raise UserError(_('Variance reasons cannot be changed after submission.'))
        return super().create(vals_list)

    def write(self, vals):
        if any(line.output_form_id.state not in ('draft', 'rejected', 'returned') for line in self):
            raise UserError(_('Variance reasons cannot be changed after submission.'))
        return super().write(vals)

    def unlink(self):
        if any(line.output_form_id.state not in ('draft', 'rejected', 'returned') for line in self):
            raise UserError(_('Variance reasons cannot be deleted after submission.'))
        return super().unlink()


class ProductionOutputFormRejectWizard(models.TransientModel):
    _name = 'production.output.form.reject.wizard'
    _description = 'Reject Production Output Form'

    output_form_id = fields.Many2one('production.output.form', required=True, readonly=True)
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.ensure_one()
        if not (self.env.user.has_group('mrp.group_mrp_manager') or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Only a Manufacturing Manager or System Administrator can reject Output Forms.'))
        if not (self.reason or '').strip():
            raise ValidationError(_('A rejection reason is required.'))
        form = self.output_form_id
        if form.state != 'submitted':
            raise UserError(_('Only a submitted Output Form can be rejected.'))
        super(ProductionOutputForm, form).write({
            'state': 'rejected', 'rejection_reason': self.reason,
            'submitted_by': False, 'submitted_on': False,
        })
        form.message_post(body=_('Rejected. Reason: %s. Lock released for Coordinator corrections.') % self.reason)
        return {'type': 'ir.actions.act_window', 'res_model': 'production.output.form', 'view_mode': 'form', 'res_id': form.id, 'target': 'current'}


class ProductionOutputFormReturnWizard(models.TransientModel):
    _name = 'production.output.form.return.wizard'
    _description = 'Send Back Production Output Form'

    output_form_id = fields.Many2one('production.output.form', required=True, readonly=True)
    reason = fields.Text(string='Reason for Sending Back', required=True)

    def action_confirm(self):
        self.ensure_one()
        if not (self.env.user.has_group('mrp.group_mrp_manager') or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Only a Manufacturing Manager or System Administrator can send back an Output Form.'))
        reason = (self.reason or '').strip()
        if not reason:
            raise ValidationError(_('A reason is required when sending an Output Form back.'))
        form = self.output_form_id
        if form.state not in ('submitted', 'approved'):
            raise UserError(_('Only Submitted or Approved Output Forms can be sent back.'))
        if form.production_id.state == 'done':
            raise UserError(_('A produced Manufacturing Order cannot be sent back.'))
        inspection = self.env['qa.manufacturing.inspection'].sudo().search(
            [('production_id', '=', form.production_id.id)], limit=1
        )
        if inspection and inspection.state != 'pending':
            raise UserError(_(
                'QA Inspection has already moved to %s. The Output Form cannot be sent back.'
            ) % dict(inspection._fields['state'].selection).get(inspection.state, inspection.state))
        values = {
            'state': 'returned',
            'return_reason': reason,
            'returned_by': self.env.user.id,
            'returned_on': fields.Datetime.now(),
            'approved_by': False,
            'approved_on': False,
        }
        # Use the model's workflow-controlled write path; the wizard is the
        # only exposed transition and validates manager permissions above.
        super(ProductionOutputForm, form).write(values)
        form.message_post(body=_(
            'Output Form sent back to Production by %s. Reason: %s. '
            'The Manufacturing Order is unlocked for correction.'
        ) % (self.env.user.display_name, reason))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'production.output.form',
            'view_mode': 'form',
            'res_id': form.id,
            'target': 'current',
        }
