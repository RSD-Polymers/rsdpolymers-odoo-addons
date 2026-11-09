from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class RSDQualityTestMixin(models.AbstractModel):
    _name = 'rsd.quality.test.mixin'
    _description = 'RSD Quality Test Workflow Mixin'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(required=True, readonly=True, copy=False, default='New', tracking=True)
    production_id = fields.Many2one(
        'mrp.production', string='Manufacturing Order', required=True,
        index=True, tracking=True, ondelete='restrict',
    )
    product_id = fields.Many2one(
        'product.product', related='production_id.product_id', store=True, readonly=True,
    )
    lot_id = fields.Many2one('stock.lot', string='Batch / Lot', tracking=True, ondelete='restrict')
    company_id = fields.Many2one(
        'res.company', related='production_id.company_id', store=True, readonly=True,
    )
    test_date = fields.Datetime(default=fields.Datetime.now, required=True, tracking=True)
    tested_by = fields.Many2one('res.users', default=lambda self: self.env.user, required=True, tracking=True)
    reviewer_id = fields.Many2one('res.users', readonly=True, tracking=True)
    reviewed_on = fields.Datetime(readonly=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('submitted', 'Submitted for Review'),
        ('passed', 'Passed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True, index=True)
    result_summary = fields.Text(tracking=True)
    deviation_id = fields.Many2one(
        'qa.deviation', string='QA Deviation', readonly=True, copy=False,
        tracking=True, ondelete='restrict',
    )
    sample_line_ids = fields.One2many(
        'rsd.quality.test.line', 'sample_test_id', string='Test Parameters',
    )
    application_line_ids = fields.One2many(
        'rsd.quality.test.line', 'application_test_id', string='Test Parameters',
    )
    test_type = fields.Selection([
        ('sample', 'Sample'),
        ('application', 'Application'),
    ], required=True, default='sample')

    def _check_test_user(self):
        if not (
            self.env.user.has_group('rsd_quality.group_quality_test_user')
            or self.env.user.has_group('rsd_quality.group_unloading_request_supervisor')
            or self.env.user.has_group('rsd_qa_management.group_qa_officer')
            or self.env.user.has_group('base.group_system')
        ):
            raise UserError(_('Only an authorised Quality Test User or QA Officer can perform this operation.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_test_user()
        sequence_codes = {
            'rsd.quality.sample.test': 'rsd.quality.sample.test',
            'rsd.quality.application.test': 'rsd.quality.application.test',
        }
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft':
                raise UserError(_('A new test must start in Draft.'))
            production = self.env['mrp.production'].browse(vals.get('production_id')).exists()
            if not production:
                raise ValidationError(_('Select a valid Manufacturing Order for this production test.'))
            lot = (
                self.env['stock.lot'].browse(vals.get('lot_id')).exists()
                if vals.get('lot_id') else production.lot_producing_id
            )
            if lot and lot.product_id != production.product_id:
                raise ValidationError(_('The selected batch / lot must belong to the Manufacturing Order product.'))
            if lot:
                vals['lot_id'] = lot.id
            vals['tested_by'] = self.env.uid
            vals['reviewer_id'] = False
            vals['reviewed_on'] = False
            vals['deviation_id'] = False
            sequence_code = sequence_codes.get(self._name)
            vals['name'] = self.env['ir.sequence'].next_by_code(sequence_code) or _('New')
        return super().create(vals_list)

    def write(self, vals):
        self._check_test_editor()
        protected_fields = {
            'production_id', 'product_id', 'company_id', 'tested_by',
            'deviation_id', 'reviewer_id', 'reviewed_on', 'state', 'name',
        }
        if protected_fields.intersection(vals):
            raise UserError(_('Manufacturing references, ownership and workflow fields cannot be changed directly.'))
        if any(rec.state not in ('draft', 'in_progress') for rec in self) and set(vals) - {
            'message_follower_ids', 'activity_ids',
        }:
            raise UserError(_('Submitted or completed tests cannot be edited.'))
        return super().write(vals)

    @api.constrains('production_id', 'lot_id')
    def _check_production_lot(self):
        for rec in self:
            if rec.lot_id and rec.lot_id.product_id != rec.production_id.product_id:
                raise ValidationError(_('The selected batch / lot must belong to the Manufacturing Order product.'))

    def _test_lines(self):
        if self._name == 'rsd.quality.sample.test':
            return self.sample_line_ids
        if self._name == 'rsd.quality.application.test':
            return self.application_line_ids
        return self.application_line_ids

    def action_start(self):
        self._check_test_user()
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only Draft tests can be started.'))
            rec._workflow_write({'state': 'in_progress'})
        return True

    def action_submit(self):
        self._check_test_user()
        for rec in self:
            if rec.state not in ('draft', 'in_progress'):
                raise UserError(_('Only Draft or In Progress tests can be submitted.'))
            if not rec._test_lines():
                raise ValidationError(_('Add at least one test parameter before submission.'))
            if any(line.result_value in (False, None, '') for line in rec._test_lines()):
                raise ValidationError(_('Enter a result for every test parameter before submission.'))
            rec._workflow_write({'state': 'submitted'})
            rec.message_post(body=_('Test submitted for QA review.'))
        return True

    def action_pass(self):
        return self._review_test('passed')

    def action_fail(self):
        return self._review_test('failed')

    def _review_test(self, outcome):
        if not (
            self.env.user.has_group('rsd_qa_management.group_qa_officer')
            or self.env.user.has_group('base.group_system')
        ):
            raise UserError(_('Only a QA Officer can review test results.'))
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only submitted tests can be reviewed.'))
            rec._workflow_write({
                'state': outcome,
                'reviewer_id': self.env.uid,
                'reviewed_on': fields.Datetime.now(),
            })
            rec.message_post(body=_('Test result: %s') % dict(rec._fields['state'].selection).get(outcome))
        return True

    def _workflow_write(self, vals):
        return super(RSDQualityTestMixin, self.sudo()).write(vals)

    def action_create_deviation(self):
        if not (
            self.env.user.has_group('rsd_qa_management.group_qa_officer')
            or self.env.user.has_group('base.group_system')
        ):
            raise UserError(_('Only a QA Officer can create a QA Deviation.'))
        self.ensure_one()
        if self.state != 'failed':
            raise UserError(_('A deviation can only be created for a failed test.'))
        self.env.cr.execute('SELECT id FROM %s WHERE id = %%s FOR UPDATE' % self._table, (self.id,))
        self.invalidate_recordset(['deviation_id'])
        if self.deviation_id:
            return {
                'type': 'ir.actions.act_window', 'res_model': 'qa.deviation',
                'view_mode': 'form', 'res_id': self.deviation_id.id,
            }
        deviation = self.env['qa.deviation'].create({
            'deviation_type': 'post_process',
            'production_id': self.production_id.id,
            'product_id': self.product_id.id,
            'lot_id': self.lot_id.id or self.production_id.lot_producing_id.id or False,
            'company_id': self.company_id.id,
            'description': _('%s failed: %s') % (
                self.display_name, self.result_summary or _('Test failure'),
            ),
            'justification': _('Originating quality test: %s') % self.display_name,
        })
        self._workflow_write({'deviation_id': deviation.id})
        self.message_post(body=_('QA Deviation %s created.') % deviation.name)
        return {
            'type': 'ir.actions.act_window', 'res_model': 'qa.deviation',
            'view_mode': 'form', 'res_id': deviation.id,
        }

    def action_cancel(self):
        self._check_test_user()
        for rec in self:
            if rec.state not in ('draft', 'in_progress'):
                raise UserError(_('Only Draft or In Progress tests can be cancelled.'))
            rec._workflow_write({'state': 'cancelled'})
        return True

    def unlink(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only Draft tests can be deleted.'))
        return super().unlink()

    def _check_test_editor(self):
        if not (
            self.env.user.has_group('rsd_quality.group_quality_test_user')
            or self.env.user.has_group('rsd_quality.group_unloading_request_supervisor')
            or self.env.user.has_group('base.group_system')
        ):
            raise UserError(_('You are not allowed to edit quality test details.'))


class RSDQualitySampleTest(models.Model):
    _name = 'rsd.quality.sample.test'
    _description = 'Sample Test'
    _inherit = 'rsd.quality.test.mixin'
    _order = 'test_date desc, id desc'

    test_type = fields.Selection(default='sample', required=True)
    sample_reference = fields.Char(string='Sample Reference', tracking=True)


class RSDQualityApplicationTest(models.Model):
    _name = 'rsd.quality.application.test'
    _description = 'Application Test'
    _inherit = 'rsd.quality.test.mixin'
    _order = 'test_date desc, id desc'

    test_type = fields.Selection(default='application', required=True)
    application_name = fields.Char(string='Application / Customer Use Case', required=True, tracking=True)
    test_method = fields.Text(string='Application Test Method')


class RSDQualityTestLine(models.Model):
    _name = 'rsd.quality.test.line'
    _description = 'Quality Test Parameter Result'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    sample_test_id = fields.Many2one('rsd.quality.sample.test', ondelete='cascade', index=True)
    application_test_id = fields.Many2one('rsd.quality.application.test', ondelete='cascade', index=True)
    parameter = fields.Char(required=True)
    specification = fields.Char(string='Acceptance Criteria')
    result_value = fields.Char(string='Observed Result', required=True)
    uom = fields.Char(string='Unit')
    remarks = fields.Text()

    def _check_line_editor(self):
        if not (
            self.env.user.has_group('rsd_quality.group_quality_test_user')
            or self.env.user.has_group('rsd_quality.group_unloading_request_supervisor')
            or self.env.user.has_group('base.group_system')
        ):
            raise UserError(_('Only Quality Test Users can maintain test parameters.'))

    def _get_parent(self, vals=None):
        vals = vals or {}
        parent_fields = ('sample_test_id', 'application_test_id')
        selected = [(field_name, vals.get(field_name)) for field_name in parent_fields if vals.get(field_name)]
        if len(selected) != 1:
            raise ValidationError(_('A result line must belong to exactly one Sample or Application Test.'))
        model_by_field = {
            'sample_test_id': 'rsd.quality.sample.test',
            'application_test_id': 'rsd.quality.application.test',
        }
        field_name, record_id = selected[0]
        return self.env[model_by_field[field_name]].browse(record_id).exists()

    @api.model_create_multi
    def create(self, vals_list):
        self._check_line_editor()
        for vals in vals_list:
            parent = self._get_parent(vals)
            if not parent or parent.state not in ('draft', 'in_progress'):
                raise UserError(_('Test parameters can only be added to a Draft or In Progress test.'))
        return super().create(vals_list)

    def write(self, vals):
        self._check_line_editor()
        if {'sample_test_id', 'application_test_id'}.intersection(vals):
            raise UserError(_('A result line cannot be moved between tests.'))
        for line in self:
            parent = line.sample_test_id or line.application_test_id
            if parent.state not in ('draft', 'in_progress'):
                raise UserError(_('Test parameters cannot be changed after submission.'))
        return super().write(vals)

    def unlink(self):
        self._check_line_editor()
        for line in self:
            parent = line.sample_test_id or line.application_test_id
            if parent.state not in ('draft', 'in_progress'):
                raise UserError(_('Test parameters cannot be deleted after submission.'))
        return super().unlink()

    @api.constrains('sample_test_id', 'application_test_id')
    def _check_single_parent(self):
        for line in self:
            parent_count = sum(bool(line[field_name]) for field_name in (
                'sample_test_id', 'application_test_id',
            ))
            if parent_count != 1:
                raise ValidationError(_('A result line must belong to exactly one Sample or Application Test.'))
