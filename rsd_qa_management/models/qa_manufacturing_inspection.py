from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


# Object identity cannot be reproduced by an RPC client through a JSON context.
_QA_INSPECTION_TRANSITION_TOKEN = object()
_QA_DEVIATION_TRANSITION_TOKEN = object()
_QA_MO_VERIFICATION_TOKEN = object()


class QAManufacturingInspection(models.Model):
    _name = 'qa.manufacturing.inspection'
    _description = 'QA Manufacturing Inspection'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Inspection Reference', required=True, copy=False,
        readonly=True, default='New', tracking=True,
    )
    production_id = fields.Many2one(
        'mrp.production', string='Manufacturing Order', required=True,
        index=True, ondelete='restrict', tracking=True,
    )
    product_id = fields.Many2one(
        related='production_id.product_id', store=True, readonly=True,
    )
    product_qty = fields.Float(
        related='production_id.product_qty', store=True, readonly=True,
    )
    lot_id = fields.Many2one(
        'stock.lot', string='Batch / Lot',
        related='production_id.lot_producing_id', store=True, readonly=True,
    )
    company_id = fields.Many2one(
        related='production_id.company_id', store=True, readonly=True,
    )
    state = fields.Selection([
        ('pending', 'Pending'),
        ('under_review', 'Under Review'),
        ('rejected', 'Rejected'),
        ('rework', 'Rework Required'),
        ('verified', 'Verified'),
    ], default='pending', required=True, tracking=True)
    inspection_date = fields.Datetime(string='Inspection Date', tracking=True)
    inspected_by_id = fields.Many2one('res.users', string='QA Inspector', tracking=True)
    verified_by_id = fields.Many2one(
        'res.users', string='Verified By', readonly=True, tracking=True,
    )
    verified_on = fields.Datetime(string='Verified On', readonly=True, tracking=True)
    production_records_reviewed = fields.Boolean(
        string='Production Records Reviewed', tracking=True,
    )
    chemist_approval_reviewed = fields.Boolean(
        string='Chemist Approval Reviewed', tracking=True,
    )
    output_form_approval_reviewed = fields.Boolean(
        string='Output Form Approval Reviewed', tracking=True,
        help='QA confirms that the linked Production Output Form was approved by Manufacturing Management.',
    )
    qc_results_reviewed = fields.Boolean(string='QC Results Reviewed', tracking=True)
    sample_testing_reviewed = fields.Boolean(
        string='Sample Testing Reviewed', tracking=True,
    )
    qc_review_notes = fields.Text(string='QC Review Notes')
    sample_testing_reference = fields.Char(string='Sample Testing Reference')
    sample_testing_results = fields.Text(string='Sample Testing Results / Observations')
    review_notes = fields.Text(string='QA Review / Inspection Notes')
    rejection_reason = fields.Text(string='Rejection / Rework Reason', tracking=True)
    deviation_ids = fields.One2many(
        'qa.deviation', 'inspection_id', string='Deviations',
    )
    deviation_count = fields.Integer(compute='_compute_deviation_count')

    _sql_constraints = [
        (
            'production_unique', 'unique(production_id)',
            'Only one primary QA Manufacturing Inspection can be created for an MO.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            if vals.get('state', 'pending') != 'pending':
                raise UserError(_('A new QA Inspection must start in Pending state.'))
            if vals.get('verified_by_id') or vals.get('verified_on'):
                raise UserError(_('Verification details can only be set by the QA verification workflow.'))
            if vals.get('name', 'New') == 'New':
                vals['name'] = sequence.next_by_code(
                    'qa.manufacturing.inspection'
                ) or 'New'
        return super().create(vals_list)

    @api.depends('deviation_ids', 'deviation_ids.state')
    def _compute_deviation_count(self):
        for rec in self:
            rec.deviation_count = len(rec.deviation_ids)

    def _check_qa_officer(self):
        if not (
            self.env.user.has_group('rsd_qa_management.group_qa_officer')
            or self.env.user.has_group('base.group_system')
        ):
            raise UserError(_('Only a QA Officer or System Administrator can perform this action.'))

    def write(self, vals):
        internal_transition = (
            self.env.context.get('_qa_inspection_transition_token')
            is _QA_INSPECTION_TRANSITION_TOKEN
        )
        if 'state' in vals and not internal_transition:
            raise UserError(_('Use the QA Inspection workflow buttons to change the inspection state.'))

        protected_audit_fields = {'verified_by_id', 'verified_on'}
        if protected_audit_fields.intersection(vals) and not internal_transition:
            raise UserError(_('Verification details can only be changed by the QA workflow.'))

        if not internal_transition and self.filtered(lambda rec: rec.state == 'verified') and vals:
            raise UserError(_('This MO Inspection is QA Verified and permanently locked. No inspection fields can be changed.'))

        # Once verified, the checklist and review evidence are frozen. A QA
        # Manager must revoke verification before any review data is changed.
        review_fields = {
            'production_records_reviewed',
            'chemist_approval_reviewed',
            'output_form_approval_reviewed',
            'qc_results_reviewed',
            'sample_testing_reviewed',
            'qc_review_notes',
            'sample_testing_reference',
            'sample_testing_results',
            'review_notes',
            'rejection_reason',
            'inspection_date',
            'inspected_by_id',
        }
        if not internal_transition and review_fields.intersection(vals):
            verified_records = self.filtered(lambda rec: rec.state == 'verified')
            if verified_records:
                raise UserError(_(
                    'A verified QA Inspection is locked. A QA Manager must revoke '
                    'verification before changing its checklist or review information.'
                ))
        return super().write(vals)

    def _write_inspection_transition(self, vals):
        return self.with_context(
            _qa_inspection_transition_token=_QA_INSPECTION_TRANSITION_TOKEN
        ).write(vals)

    def action_start_review(self):
        self._check_qa_officer()
        for rec in self:
            if rec.state not in ('pending', 'rework'):
                raise UserError(_('Only pending or rework inspections can be started.'))
            rec._write_inspection_transition({
                'state': 'under_review',
                'inspection_date': fields.Datetime.now(),
                'inspected_by_id': self.env.user.id,
            })
        return True

    def action_create_deviation(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Deviation'),
            'res_model': 'qa.deviation',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_inspection_id': self.id,
                'default_production_id': self.production_id.id,
                'default_product_id': self.product_id.id,
                'default_lot_id': self.lot_id.id,
                'default_company_id': self.company_id.id,
            },
        }

    def action_view_deviations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Deviations'),
            'res_model': 'qa.deviation',
            'view_mode': 'list,form',
            'domain': [('inspection_id', '=', self.id)],
            'context': {
                'default_inspection_id': self.id,
                'default_production_id': self.production_id.id,
            },
        }

    def action_verify(self):
        if not self.env.user.has_group('rsd_qa_management.group_qa_manager'):
            raise UserError(_('Only a QA Manager can verify an MO Inspection.'))
        tag = self.env.ref('rsd_qa_management.qa_mo_tag_verified')
        for rec in self:
            if rec.state != 'under_review':
                raise UserError(_('Only an inspection Under Review can be verified.'))
            if rec.production_id.state != 'done':
                raise UserError(_(
                    'QA final verification is available only after the '
                    'Manufacturing Order is produced (Done).'
                ))

            # Output Forms move from Approved to Produced when the MO is
            # completed. Approval audit fields are therefore the durable proof
            # that Manufacturing Management approved the form.
            output_form = self.env['production.output.form'].sudo().search([
                ('production_id', '=', rec.production_id.id),
                ('state', '!=', 'cancelled'),
            ], order='id desc', limit=1)
            if not output_form or output_form.state not in ('approved', 'produced') or not output_form.approved_by or not output_form.approved_on:
                raise UserError(_(
                    'QA verification is blocked: the Manufacturing Order must have an Output Form '
                    'approved by Manufacturing Management before QA can verify it.'
                ))

            missing = []
            for field_name, label in [
                ('production_records_reviewed', _('Production records')),
                ('chemist_approval_reviewed', _('Production Chemist approval')),
                ('output_form_approval_reviewed', _('Output Form approval')),
                ('qc_results_reviewed', _('QC results')),
                ('sample_testing_reviewed', _('Sample testing')),
            ]:
                if not rec[field_name]:
                    missing.append(label)
            if missing:
                raise UserError(_(
                    'Please complete the following QA review confirmations:\n- %s'
                ) % '\n- '.join(missing))

            unresolved = rec.deviation_ids.filtered(
                lambda deviation: deviation.state not in ('approved', 'closed')
            )
            if unresolved:
                raise UserError(_(
                    'All deviations linked to this inspection must be Approved '
                    'or Closed before QA verification.\n%s'
                ) % ', '.join(unresolved.mapped('name')))

            rec._write_inspection_transition({
                'state': 'verified',
                'verified_by_id': self.env.user.id,
                'verified_on': fields.Datetime.now(),
            })
            rec.production_id.sudo().with_context(
                _qa_mo_verification_token=_QA_MO_VERIFICATION_TOKEN,
                _qa_mo_verification_tag_update=True,
            ).write({'qa_inspection_tag_ids': [(4, tag.id)]})
        return True

    def action_reject(self):
        self._check_qa_officer()
        self._check_qa_officer()
        for rec in self:
            if rec.state != 'under_review':
                raise UserError(_('Only an inspection Under Review can be rejected.'))
            if not rec.rejection_reason:
                raise UserError(_('Enter a rejection reason before rejecting the QA inspection.'))
            rec._write_inspection_transition({'state': 'rejected'})
        return True

    def action_request_rework(self):
        self._check_qa_officer()
        for rec in self:
            if rec.state != 'under_review':
                raise UserError(_('Only an inspection Under Review can be sent for rework.'))
            if not rec.rejection_reason:
                raise UserError(_('Enter the rework reason before requesting rework.'))
            rec._write_inspection_transition({'state': 'rework'})
        return True

    def action_revoke_verification(self):
        raise UserError(_('QA verification is final. A verified MO Inspection cannot be reopened or revoked.'))



class QAManufacturingDeviation(models.Model):
    _name = 'qa.deviation'
    _description = 'QA Deviation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Deviation Reference', required=True, copy=False,
        readonly=True, default='New', tracking=True,
    )
    deviation_type = fields.Selection([
        ('planned', 'Planned Deviation'),
        ('post_process', 'Post-Process Deviation'),
    ], required=True, default='post_process', tracking=True)
    inspection_id = fields.Many2one(
        'qa.manufacturing.inspection', string='MO Inspection',
        ondelete='restrict', index=True, tracking=True,
    )
    production_id = fields.Many2one(
        'mrp.production', string='Manufacturing Order', required=True,
        ondelete='restrict', index=True, tracking=True,
    )
    product_id = fields.Many2one(
        'product.product', string='Product', required=True, tracking=True,
    )
    lot_id = fields.Many2one('stock.lot', string='Batch / Lot', tracking=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    date_reported = fields.Date(
        default=fields.Date.context_today, tracking=True,
    )
    reported_by_id = fields.Many2one(
        'res.users', default=lambda self: self.env.user, tracking=True,
    )
    description = fields.Text(required=True, tracking=True)
    justification = fields.Text(string='Justification / Reason')
    impact_assessment = fields.Text(string='Quality / Product Impact Assessment')
    investigation = fields.Text(string='Investigation')
    corrective_action = fields.Text(string='Corrective Action')
    preventive_action = fields.Text(string='Preventive Action')
    qa_remarks = fields.Text(string='QA Remarks')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('investigation', 'Investigation'),
        ('action_required', 'Action Required'),
        ('approved', 'Approved'),
        ('closed', 'Closed'),
        ('rejected', 'Rejected'),
    ], default='draft', required=True, tracking=True)
    approved_by_id = fields.Many2one('res.users', readonly=True, tracking=True)
    approved_on = fields.Datetime(readonly=True, tracking=True)
    closed_by_id = fields.Many2one('res.users', readonly=True, tracking=True)
    closed_on = fields.Datetime(readonly=True, tracking=True)

    def _check_qa_officer(self):
        if not (
            self.env.user.has_group('rsd_qa_management.group_qa_officer')
            or self.env.user.has_group('base.group_system')
        ):
            raise UserError(_('Only a QA Officer or System Administrator can perform this action.'))

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft':
                raise UserError(_('A new Deviation must start in Draft state.'))
            if any(vals.get(field_name) for field_name in (
                'approved_by_id', 'approved_on', 'closed_by_id', 'closed_on'
            )):
                raise UserError(_('Approval and closure details can only be set by the Deviation workflow.'))
            if vals.get('name', 'New') == 'New':
                vals['name'] = sequence.next_by_code('qa.deviation') or 'New'

            inspection = self.env['qa.manufacturing.inspection'].browse(
                vals.get('inspection_id')
            ).exists()
            production = self.env['mrp.production'].browse(
                vals.get('production_id') or (inspection.production_id.id if inspection else False)
            ).exists()
            if inspection and not production:
                production = inspection.production_id
            if production:
                vals['production_id'] = production.id
                vals.setdefault('product_id', production.product_id.id)
                vals.setdefault('company_id', production.company_id.id)
                if not vals.get('lot_id') and production.lot_producing_id:
                    vals['lot_id'] = production.lot_producing_id.id
                if not inspection:
                    inspection = self.env['qa.manufacturing.inspection'].search(
                        [('production_id', '=', production.id)], limit=1
                    )
                    if inspection:
                        vals['inspection_id'] = inspection.id

            self._validate_link_values(vals, production=production, inspection=inspection)
            if vals.get('deviation_type', 'post_process') == 'planned' and production \
                    and production.state not in ('draft', 'confirmed'):
                raise UserError(_(
                    'A Planned Deviation must be created before production starts.'
                ))

        return super().create(vals_list)

    def write(self, vals):
        internal_transition = (
            self.env.context.get('_qa_deviation_transition_token')
            is _QA_DEVIATION_TRANSITION_TOKEN
        )
        if 'state' in vals and not internal_transition:
            raise UserError(_('Use the Deviation workflow buttons to change the deviation state.'))
        protected = {'approved_by_id', 'approved_on', 'closed_by_id', 'closed_on'}
        if protected.intersection(vals) and not internal_transition:
            raise UserError(_('Approval and closure details can only be changed by the Deviation workflow.'))

        # Approved and closed deviations are controlled records. Their
        # investigation, actions and links cannot be edited directly.
        controlled_fields = {
            'deviation_type', 'inspection_id', 'production_id', 'product_id',
            'lot_id', 'company_id', 'date_reported', 'reported_by_id',
            'description', 'justification', 'impact_assessment',
            'investigation', 'corrective_action', 'preventive_action',
            'qa_remarks',
        }
        if not internal_transition and controlled_fields.intersection(vals):
            controlled_records = self.filtered(
                lambda rec: rec.state in ('approved', 'closed')
            )
            if controlled_records:
                raise UserError(_(
                    'Approved or Closed deviations are locked. Contact QA to follow '
                    'the controlled deviation process before changing their records.'
                ))

        for rec in self:
            if 'production_id' in vals and vals['production_id'] != rec.production_id.id:
                raise UserError(_('The Manufacturing Order cannot be changed after a Deviation is created.'))

            production = rec.production_id
            inspection_id = vals.get('inspection_id', rec.inspection_id.id)
            inspection = self.env['qa.manufacturing.inspection'].browse(
                inspection_id
            ).exists() if inspection_id else self.env['qa.manufacturing.inspection']
            resulting_values = {
                'production_id': production.id,
                'inspection_id': inspection.id if inspection else False,
                'product_id': vals.get('product_id', rec.product_id.id),
                'lot_id': vals.get('lot_id', rec.lot_id.id),
                'company_id': vals.get('company_id', rec.company_id.id),
            }
            self._validate_link_values(
                resulting_values, production=production, inspection=inspection
            )

            deviation_type = vals.get('deviation_type', rec.deviation_type)
            if deviation_type == 'planned' and production.state not in ('draft', 'confirmed'):
                raise UserError(_(
                    'A Planned Deviation must be created or changed before production starts.'
                ))
        return super().write(vals)

    def _write_deviation_transition(self, vals):
        return self.with_context(
            _qa_deviation_transition_token=_QA_DEVIATION_TRANSITION_TOKEN
        ).write(vals)

    @api.model
    def _validate_link_values(self, vals, production=None, inspection=None):
        production_id = vals.get('production_id') or (production.id if production else False)
        inspection_id = vals.get('inspection_id') or (inspection.id if inspection else False)
        product_id = vals.get('product_id') or (production.product_id.id if production else False)
        lot_id = vals.get('lot_id') or False
        company_id = vals.get('company_id') or (production.company_id.id if production else False)

        if inspection_id:
            inspection = self.env['qa.manufacturing.inspection'].browse(inspection_id).exists()
            if not inspection:
                raise ValidationError(_('The selected QA Inspection does not exist.'))
            if production_id and inspection.production_id.id != production_id:
                raise ValidationError(_(
                    'The selected QA Inspection must belong to the selected Manufacturing Order.'
                ))
        if production and product_id and production.product_id.id != product_id:
            raise ValidationError(_(
                'The deviation product must match the Manufacturing Order product.'
            ))
        if production and company_id and production.company_id.id != company_id:
            raise ValidationError(_(
                'The deviation company must match the Manufacturing Order company.'
            ))
        if lot_id:
            lot = self.env['stock.lot'].browse(lot_id).exists()
            if not lot:
                raise ValidationError(_('The selected batch / lot does not exist.'))
            if product_id and lot.product_id.id != product_id:
                raise ValidationError(_(
                    'The selected batch / lot must belong to the deviation product.'
                ))

    def action_submit(self):
        self._check_qa_officer()
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only Draft deviations can be submitted.'))
            if not rec.description:
                raise UserError(_('Enter the deviation description.'))

            if rec.deviation_type == 'planned':
                if rec.production_id.state not in ('draft', 'confirmed'):
                    raise UserError(_(
                        'A Planned Deviation must be submitted before production starts. '
                        'Use Post-Process Deviation for an issue identified after production '
                        'has started.'
                    ))
                if not rec.justification:
                    raise UserError(_(
                        'A Planned Deviation requires a justification before submission.'
                    ))
            elif rec.deviation_type == 'post_process':
                if rec.production_id.state != 'done':
                    raise UserError(_(
                        'A Post-Process Deviation can only be submitted after the '
                        'Manufacturing Order is Done.'
                    ))

            rec._write_deviation_transition({'state': 'submitted'})
        return True

    def action_start_investigation(self):
        self._check_qa_officer()
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only Submitted deviations can enter Investigation.'))
            rec._write_deviation_transition({'state': 'investigation'})
        return True

    def action_request_action(self):
        self._check_qa_officer()
        for rec in self:
            if rec.state != 'investigation':
                raise UserError(_('Only deviations under Investigation can move to Action Required.'))
            if not rec.corrective_action:
                raise UserError(_('Enter the corrective action before moving to Action Required.'))
            rec._write_deviation_transition({'state': 'action_required'})
        return True

    def action_approve(self):
        self._check_qa_officer()
        for rec in self:
            if rec.state not in ('submitted', 'investigation', 'action_required'):
                raise UserError(_(
                    'Only Submitted, Investigation, or Action Required deviations can be approved.'
                ))
            if rec.deviation_type == 'planned' and rec.production_id.state not in ('draft', 'confirmed'):
                raise UserError(_(
                    'A Planned Deviation must be approved before production starts.'
                ))
            rec._write_deviation_transition({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approved_on': fields.Datetime.now(),
            })
        return True

    def action_close(self):
        self._check_qa_officer()
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Only Approved deviations can be closed.'))
            if not rec.corrective_action:
                raise UserError(_('Record the corrective action before closing the deviation.'))
            rec._write_deviation_transition({
                'state': 'closed',
                'closed_by_id': self.env.user.id,
                'closed_on': fields.Datetime.now(),
            })
        return True

    def action_reject(self):
        for rec in self:
            if rec.state not in ('draft', 'submitted', 'investigation', 'action_required'):
                raise UserError(_(
                    'This deviation cannot be rejected in its current state.'
                ))
            rec._write_deviation_transition({'state': 'rejected'})
        return True


class QualityCheck(models.Model):
    _inherit = 'quality.check'

    def _qa_verified_productions(self):
        production_ids = self.mapped('production_id').ids if 'production_id' in self._fields else []
        if not production_ids:
            return self.env['qa.manufacturing.inspection']
        return self.env['qa.manufacturing.inspection'].sudo().search([
            ('production_id', 'in', production_ids), ('state', '=', 'verified')
        ])

    def write(self, vals):
        locked = self._qa_verified_productions()
        if locked:
            raise UserError(_('Quality Checks linked to a QA Verified MO are locked.'))
        return super().write(vals)

    def unlink(self):
        if self._qa_verified_productions():
            raise UserError(_('Quality Checks linked to a QA Verified MO cannot be deleted.'))
        return super().unlink()


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def _qa_verified_link(self):
        inspections = self.env['qa.manufacturing.inspection'].sudo().search([('state', '=', 'verified')])
        verified_mo_ids = inspections.mapped('production_id').ids
        for attachment in self:
            if attachment.res_model == 'qa.manufacturing.inspection' and attachment.res_id in inspections.ids:
                return True
            if attachment.res_model == 'mrp.production' and attachment.res_id in verified_mo_ids:
                return True
            if attachment.res_model == 'quality.check':
                check = self.env['quality.check'].sudo().browse(attachment.res_id).exists()
                if check and 'production_id' in check._fields and check.production_id.id in verified_mo_ids:
                    return True
        return False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            model, res_id = vals.get('res_model'), vals.get('res_id')
            if model == 'mrp.production' and self.env['qa.manufacturing.inspection'].sudo().search_count([('production_id', '=', res_id), ('state', '=', 'verified')]):
                raise UserError(_('You cannot add attachments to a QA Verified Manufacturing Order.'))
            if model == 'qa.manufacturing.inspection' and self.env['qa.manufacturing.inspection'].sudo().browse(res_id).state == 'verified':
                raise UserError(_('You cannot add attachments to a QA Verified MO Inspection.'))
            if model == 'quality.check':
                check = self.env['quality.check'].sudo().browse(res_id).exists()
                if check and 'production_id' in check._fields and self.env['qa.manufacturing.inspection'].sudo().search_count([('production_id', '=', check.production_id.id), ('state', '=', 'verified')]):
                    raise UserError(_('You cannot add attachments to a Quality Check linked to a QA Verified MO.'))
        return super().create(vals_list)

    def write(self, vals):
        if self._qa_verified_link():
            raise UserError(_('Attachments linked to a QA Verified MO are locked and cannot be changed.'))
        return super().write(vals)

    def unlink(self):
        if self._qa_verified_link():
            raise UserError(_('Attachments linked to a QA Verified MO cannot be deleted.'))
        return super().unlink()


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    qa_inspection_ids = fields.One2many(
        'qa.manufacturing.inspection', 'production_id',
        string='QA Inspections', readonly=True,
    )
    qa_inspection_count = fields.Integer(compute='_compute_qa_inspection_count')
    qa_is_verified = fields.Boolean(
        string='QA Verified', compute='_compute_qa_is_verified',
    )
    qa_inspection_tag_ids = fields.Many2many(
        'qa.inspection.tag', 'qa_mo_inspection_tag_rel',
        'production_id', 'tag_id', string='QA Tags', copy=False,
    )

    @api.depends('qa_inspection_ids.state')
    def _compute_qa_is_verified(self):
        inspection_model = self.env['qa.manufacturing.inspection'].sudo()

        for mo in self:
            mo.qa_is_verified = bool(inspection_model.search_count([
                ('production_id', '=', mo.id),
                ('state', '=', 'verified'),
            ]))

    @api.depends('qa_inspection_ids')
    def _compute_qa_inspection_count(self):
        inspection_model = self.env['qa.manufacturing.inspection'].sudo()

        for mo in self:
            mo.qa_inspection_count = inspection_model.search_count([
                ('production_id', '=', mo.id)
            ])

    def _check_qa_planned_deviations_before_start(self):
        """Block the first MO start while any Planned Deviation is unresolved."""
        deviation_model = self.env['qa.deviation'].sudo()
        for mo in self.filtered(lambda production: production.state == 'confirmed'):
            unresolved = deviation_model.search([
                ('production_id', '=', mo.id),
                ('deviation_type', '=', 'planned'),
                ('state', 'not in', ('approved', 'closed')),
            ])
            if unresolved:
                raise UserError(_(
                    'Manufacturing Order %s cannot start because these Planned '
                    'Deviations are not approved: %s'
                ) % (mo.display_name, ', '.join(unresolved.mapped('name'))))
        return True

    def action_start(self):
        self._check_qa_planned_deviations_before_start()
        return super().action_start()

    def write(self, vals):
        verification_write = (self.env.context.get('_qa_mo_verification_token') is _QA_MO_VERIFICATION_TOKEN)
        is_qa_user = (
            self.env.user.has_group('rsd_qa_management.group_qa_officer')
            or self.env.user.has_group('rsd_qa_management.group_qa_manager')
        )
        if is_qa_user and not verification_write and set(vals) - {'message_follower_ids', 'message_partner_ids'}:
            raise UserError(_('QA users have read-only access to Manufacturing Orders. Update the QA Inspection instead.'))
        if not verification_write:
            locked = self.env['qa.manufacturing.inspection'].sudo().search([
                ('production_id', 'in', self.ids), ('state', '=', 'verified')
            ])
            if locked:
                raise UserError(_('This Manufacturing Order is locked because its MO Inspection has been QA Verified: %s') % ', '.join(locked.mapped('production_id.display_name')))
        if vals.get('state') == 'progress':
            self._check_qa_planned_deviations_before_start()
        return super().write(vals)

    def action_confirm(self):
        result = super().action_confirm()
        inspection_model = self.env['qa.manufacturing.inspection'].sudo()
        deviation_model = self.env['qa.deviation'].sudo()
        for mo in self:
            if mo.state == 'cancel':
                continue
            inspection = inspection_model.search(
                [('production_id', '=', mo.id)], limit=1
            )
            if not inspection:
                inspection = inspection_model.create({'production_id': mo.id})

            # Planned deviations may be raised before MO confirmation. Link them
            # to the automatically-created inspection once it becomes available.
            unlinked_deviations = deviation_model.search([
                ('production_id', '=', mo.id),
                ('inspection_id', '=', False),
            ])
            if unlinked_deviations:
                unlinked_deviations.write({'inspection_id': inspection.id})
        return result

    def action_view_qa_inspections(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('QA Inspection'),
            'res_model': 'qa.manufacturing.inspection',
            'view_mode': 'list,form',
            'domain': [('production_id', '=', self.id)],
            'context': {'default_production_id': self.id},
        }


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    def _check_qa_planned_deviations_before_start(self):
        productions = self.mapped('production_id').filtered(
            lambda production: production.state == 'confirmed'
        )
        productions._check_qa_planned_deviations_before_start()
        return True

    def button_start(self, raise_on_invalid_state=False, bypass=False):
        self._check_qa_planned_deviations_before_start()
        return super().button_start(
            raise_on_invalid_state=raise_on_invalid_state,
            bypass=bypass,
        )

    def start_employee(self, employee_id):
        self._check_qa_planned_deviations_before_start()
        return super().start_employee(employee_id)

    def write(self, vals):
        verification_write = (self.env.context.get('_qa_mo_verification_token') is _QA_MO_VERIFICATION_TOKEN)
        is_qa_user = (
            self.env.user.has_group('rsd_qa_management.group_qa_officer')
            or self.env.user.has_group('rsd_qa_management.group_qa_manager')
        )
        if is_qa_user and not verification_write and set(vals) - {'message_follower_ids', 'message_partner_ids'}:
            raise UserError(_('QA users have read-only access to Manufacturing Work Orders.'))
        if not verification_write:
            production_ids = self.mapped('production_id').ids

            locked = self.env['qa.manufacturing.inspection'].sudo().search([
                ('production_id', 'in', production_ids),
                ('state', '=', 'verified')
            ])
            if locked:
                raise UserError(_('This Manufacturing Order is locked because its MO Inspection has been QA Verified: %s') % ', '.join(locked.mapped('production_id.display_name')))
        if vals.get('state') == 'progress':
            self._check_qa_planned_deviations_before_start()
        return super().write(vals)


class QAInspectionTag(models.Model):
    _name = 'qa.inspection.tag'
    _description = 'QA Inspection Tag'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    color = fields.Integer(default=10)
    active = fields.Boolean(default=True)