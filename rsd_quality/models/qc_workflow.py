from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class RSDQualitySpecTemplate(models.Model):
    _name = 'rsd.quality.spec.template'
    _description = 'QC Product Specification Template'
    _inherit = ['mail.thread']
    _order = 'product_id, test_kind, name'

    name = fields.Char(required=True, tracking=True)
    product_id = fields.Many2one('product.product', required=True, index=True, ondelete='cascade', tracking=True)
    test_kind = fields.Selection([('unloading', 'Unloading Analysis'), ('performance', 'Performance Test'), ('internal_coa', 'Internal COA')], required=True, tracking=True)
    active = fields.Boolean(default=True)
    line_ids = fields.One2many('rsd.quality.spec.template.line', 'template_id', copy=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    _sql_constraints = [('product_kind_company_unique', 'unique(product_id, test_kind, company_id)', 'Only one active template of each type is allowed per product and company.')]

    @api.constrains('line_ids')
    def _check_lines(self):
        for rec in self:
            if not rec.line_ids:
                raise ValidationError(_('A specification template must contain at least one parameter.'))


class RSDQualitySpecTemplateLine(models.Model):
    _name = 'rsd.quality.spec.template.line'
    _description = 'QC Specification Parameter'
    _order = 'sequence, id'

    template_id = fields.Many2one('rsd.quality.spec.template', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    uom_id = fields.Many2one('uom.uom')
    value_type = fields.Selection([('number', 'Number'), ('text', 'Text'), ('yes_no', 'Yes / No')], default='number', required=True)
    min_value = fields.Float()
    max_value = fields.Float()
    expected_text = fields.Char()
    required = fields.Boolean(default=True)

    @api.constrains('min_value', 'max_value', 'value_type')
    def _check_range(self):
        for rec in self:
            if rec.value_type == 'number' and rec.min_value > rec.max_value and rec.max_value:
                raise ValidationError(_('Minimum value cannot exceed maximum value.'))


class RSDQualityStageTest(models.Model):
    _name = 'rsd.quality.stage.test'
    _description = 'QC Performance / Internal COA Test'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(required=True, readonly=True, copy=False, default='New')
    production_id = fields.Many2one('mrp.production', required=True, ondelete='restrict', index=True, tracking=True)
    product_id = fields.Many2one(related='production_id.product_id', store=True, readonly=True)
    lot_id = fields.Many2one('stock.lot', ondelete='restrict')
    company_id = fields.Many2one(related='production_id.company_id', store=True)
    test_kind = fields.Selection([('performance', 'Performance Test'), ('internal_coa', 'Internal COA')], required=True, index=True)
    state = fields.Selection([('draft', 'Draft'), ('acknowledged', 'Sample Acknowledged'), ('in_progress', 'In Progress'), ('passed', 'Passed'), ('failed', 'Failed'), ('not_required', 'Not Required')], default='draft', required=True, tracking=True)
    template_id = fields.Many2one('rsd.quality.spec.template', domain="[('product_id', '=', product_id), ('test_kind', '=', test_kind), ('active', '=', True)]")
    requested_by = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    assigned_user_id = fields.Many2one('res.users', tracking=True)
    expected_result_datetime = fields.Datetime(tracking=True)
    acknowledged_on = fields.Datetime(readonly=True)
    result_date = fields.Datetime(readonly=True)
    line_ids = fields.One2many('rsd.quality.stage.test.line', 'test_id', copy=True)
    result_summary = fields.Text()

    @api.constrains('assigned_user_id')
    def _check_assigned_user_group(self):
        for rec in self:
            if rec.assigned_user_id and not (
                rec.assigned_user_id.has_group('rsd_quality.group_application_test_user')
                or rec.assigned_user_id.has_group('base.group_system')
            ):
                raise ValidationError(_('The assigned user must belong to the Application Test User group.'))

    @api.onchange('template_id')
    def _onchange_template_id(self):
        for rec in self:
            if rec.template_id:
                rec.line_ids = [(5, 0, 0)] + [(0, 0, {'template_line_id': line.id, 'sequence': line.sequence}) for line in rec.template_id.line_ids]

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.user.has_group('rsd_quality.group_application_test_user') or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Only an Application Test User or System Administrator can create a Performance Test.'))
        for vals in vals_list:
            if vals.get('test_kind') not in ('performance', 'internal_coa'):
                raise ValidationError(_('Invalid QC test type.'))
            prod = self.env['mrp.production'].browse(vals.get('production_id')).exists()
            if not prod:
                raise ValidationError(_('Select a valid Manufacturing Order.'))
            if vals.get('test_kind') == 'internal_coa':
                raise ValidationError(_('Internal COA is managed through the existing Odoo Quality Check workflow.'))
            assigned_id = vals.get('assigned_user_id')
            if assigned_id:
                assigned = self.env['res.users'].browse(assigned_id)
                if not assigned.has_group('rsd_quality.group_application_test_user') and not assigned.has_group('base.group_system'):
                    raise ValidationError(_('The assigned user must belong to the Application Test User group.'))
            vals['name'] = self.env['ir.sequence'].next_by_code('rsd.quality.stage.test') or _('New')
            vals.setdefault('lot_id', prod.lot_producing_id.id)
        return super().create(vals_list)

    def _check_qc_user(self):
        if not (self.env.user.has_group('rsd_quality.group_application_test_user') or self.env.user.has_group('rsd_quality.group_quality_test_user') or self.env.user.has_group('rsd_quality.group_unloading_request_chemist') or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Only authorised Application Test Users or System Administrators can process Performance Tests.'))

    def _check_assigned_application_user(self):
        for rec in self:
            if rec.test_kind == 'performance' and not self.env.user.has_group('base.group_system'):
                if not self.env.user.has_group('rsd_quality.group_application_test_user'):
                    raise AccessError(_('Only an Application Test User can process a Performance Test.'))
                if rec.assigned_user_id and rec.assigned_user_id != self.env.user:
                    raise AccessError(_('This Performance Test is assigned to another Application Test User.'))

    def action_acknowledge(self):
        self._check_assigned_application_user()
        for rec in self:
            if rec.test_kind != 'performance' or rec.state != 'draft':
                raise UserError(_('Only a draft Performance Test can be acknowledged.'))
            if not rec.expected_result_datetime:
                raise ValidationError(_('Enter the expected result date and time.'))
            rec.write({'state': 'acknowledged', 'acknowledged_on': fields.Datetime.now()})
        return True

    def action_start(self):
        self._check_assigned_application_user()
        for rec in self:
            if rec.state not in ('draft', 'acknowledged'):
                raise UserError(_('Only a draft or acknowledged test can be started.'))
            rec.write({'state': 'in_progress'})
        return True

    def action_evaluate(self):
        self._check_assigned_application_user()
        for rec in self:
            if rec.state not in ('in_progress', 'acknowledged', 'draft'):
                raise UserError(_('This test has already been evaluated.'))
            if not rec.template_id or not rec.line_ids:
                raise ValidationError(_('Select a specification template and enter its results.'))
            lines = rec.line_ids
            if any(not line.result_value for line in lines):
                raise ValidationError(_('Enter a result for every test parameter.'))
            failures = lines.filtered(lambda l: not l.is_pass)
            outcome = 'failed' if failures else 'passed'
            rec.write({'state': outcome, 'result_date': fields.Datetime.now(), 'result_summary': _('Failed parameters: %s') % ', '.join(failures.mapped('name')) if failures else _('All parameters are within specification.')})
            rec.message_post(body=_('Automatic QC evaluation: %s') % outcome.title())
        return True

    def action_mark_not_required(self):
        raise UserError(_('Performance Test necessity is decided by the Production Supervisor on the Manufacturing Order.'))


class RSDQualityStageTestLine(models.Model):
    _name = 'rsd.quality.stage.test.line'
    _description = 'QC Test Result Line'
    _order = 'sequence, id'

    test_id = fields.Many2one('rsd.quality.stage.test', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    template_line_id = fields.Many2one('rsd.quality.spec.template.line', required=True, ondelete='restrict')
    name = fields.Char(related='template_line_id.name', store=True)
    value_type = fields.Selection(related='template_line_id.value_type', store=True)
    min_value = fields.Float(related='template_line_id.min_value', store=True)
    max_value = fields.Float(related='template_line_id.max_value', store=True)
    expected_text = fields.Char(related='template_line_id.expected_text', store=True)
    result_value = fields.Char(required=True)
    is_pass = fields.Boolean(compute='_compute_is_pass', store=True)

    @api.depends('result_value', 'value_type', 'min_value', 'max_value', 'expected_text')
    def _compute_is_pass(self):
        for rec in self:
            value = (rec.result_value or '').strip()
            if rec.value_type == 'number':
                try:
                    number = float(value)
                    rec.is_pass = number >= rec.min_value and (not rec.max_value or number <= rec.max_value)
                except (TypeError, ValueError):
                    rec.is_pass = False
            elif rec.value_type == 'yes_no':
                rec.is_pass = value.lower() in ('yes', 'true', '1')
            else:
                rec.is_pass = value.casefold() == (rec.expected_text or '').strip().casefold()


class ProductProductQCTestPolicy(models.Model):
    _inherit = 'product.product'

    performance_test_policy = fields.Selection([
        ('mandatory', 'Mandatory'),
        ('optional', 'Optional'),
    ], string='Performance Test Policy', default='optional', required=True,
    help='Mandatory: a Performance Test is automatically created after unloading approval. Optional: the Production Supervisor decides whether to request it.')


class MrpProductionQCGate(models.Model):
    _inherit = 'mrp.production'

    qc_performance_required = fields.Boolean(string='Performance Test Required', compute='_compute_qc_gate')
    qc_performance_policy = fields.Selection(related='product_id.performance_test_policy', string='Performance Test Policy', readonly=True)
    qc_performance_decision = fields.Selection([
        ('pending', 'Supervisor Decision Pending'),
        ('required', 'Required'),
        ('not_required', 'Not Required'),
    ], string='Optional Performance Test Decision', default='pending', copy=False, tracking=True)
    qc_performance_test_ids = fields.One2many('rsd.quality.stage.test', 'production_id', domain=[('test_kind', '=', 'performance')])
    qc_quality_check_ids = fields.One2many('quality.check', 'production_id', string='Quality Checks')
    qc_internal_coa_state = fields.Selection([
        ('pending', 'Pending'),
        ('passed', 'Passed'),
        ('failed', 'Failed'),
        ('not_required', 'Not Required'),
    ], compute='_compute_qc_gate')
    qc_performance_state = fields.Selection([('pending', 'Pending'), ('passed', 'Passed'), ('failed', 'Failed'), ('not_required', 'Not Required')], compute='_compute_qc_gate')
    qc_batch_eligible = fields.Boolean(compute='_compute_qc_gate', string='Eligible for Output', store=False)
    qc_unloading_approved = fields.Boolean(compute='_compute_qc_gate', string='Unloading Approved')

    def _internal_coa_checks(self):
        self.ensure_one()
        return self.qc_quality_check_ids.sudo().filtered(
            lambda check: check.product_id == self.product_id
            and check.point_id and 'internal qc' in (check.point_id.title or '').casefold()
        )

    @api.depends('product_id.performance_test_policy', 'qc_performance_decision',
                 'qc_performance_test_ids.state', 'unloading_request_ids.state',
                 'qc_quality_check_ids.quality_state', 'qc_quality_check_ids.point_id.title',
                 'qc_quality_check_ids.product_id')
    def _compute_qc_gate(self):
        for mo in self:
            perf = mo.qc_performance_test_ids.filtered(lambda t: t.test_kind == 'performance').sorted('id')[-1:]
            policy = mo.product_id.performance_test_policy or 'optional'
            if perf:
                pstate = perf.state
                # A Mandatory Performance Test can never be waived.
                if policy == 'mandatory' and pstate == 'not_required':
                    pstate = 'pending'
            elif policy == 'mandatory':
                pstate = 'pending'
            elif mo.qc_performance_decision == 'not_required':
                pstate = 'not_required'
            elif mo.qc_performance_decision == 'required':
                pstate = 'pending'
            else:
                # Optional tests remain blocked until the Production Supervisor
                # explicitly chooses Required or Not Required.
                pstate = 'pending'
            mo.qc_performance_required = policy == 'mandatory' or mo.qc_performance_decision == 'required'
            mo.qc_performance_state = pstate if pstate in ('passed', 'failed', 'not_required') else 'pending'

            internal_points = self.env['quality.point'].sudo().search([
                ('product_ids', 'in', [mo.product_id.id]),
                ('title', 'ilike', 'Internal QC'),
            ])
            if not internal_points:
                # No Internal QC Quality Point is configured for this product,
                # so Internal COA is not applicable to this Manufacturing Order.
                cstate = 'not_required'
            else:
                point_states = []
                for point in internal_points:
                    point_checks = mo._internal_coa_checks().filtered(lambda check: check.point_id == point)
                    latest_check = point_checks.sorted('id')[-1:] if point_checks else self.env['quality.check']
                    point_states.append(latest_check.quality_state if latest_check else 'none')
                if any(state == 'fail' for state in point_states):
                    cstate = 'failed'
                elif all(state == 'pass' for state in point_states):
                    cstate = 'passed'
                else:
                    cstate = 'pending'
            mo.qc_internal_coa_state = cstate
            latest_unloading = mo.unloading_request_ids.sorted(lambda r: (r.request_date, r.id))[-1:]
            unloading_ok = bool(latest_unloading and latest_unloading.state == 'accepted')
            mo.qc_unloading_approved = unloading_ok
            mo.qc_batch_eligible = (
                unloading_ok
                and pstate in ('passed', 'not_required')
                and cstate in ('passed', 'not_required')
            )

    def _create_mandatory_performance_test(self):
        for mo in self:
            if mo.product_id.performance_test_policy != 'mandatory':
                continue
            existing = mo.qc_performance_test_ids.filtered(lambda t: t.state != 'cancelled')
            if existing:
                continue
            template = self.env['rsd.quality.spec.template'].search([
                ('product_id', '=', mo.product_id.id), ('test_kind', '=', 'performance'),
                ('active', '=', True), ('company_id', 'in', [False, mo.company_id.id]),
            ], limit=1)
            self.env['rsd.quality.stage.test'].sudo().create({
                'production_id': mo.id,
                'test_kind': 'performance',
                'template_id': template.id if template else False,
            })

    def action_request_optional_performance_test(self):
        self.ensure_one()
        if not (self.env.user.has_group('rsd_quality.group_unloading_request_supervisor') or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Only the Production Supervisor or System Administrator can decide whether an optional Performance Test is required.'))
        if self.product_id.performance_test_policy != 'optional':
            raise UserError(_('This product has a Mandatory Performance Test policy.'))
        if not self.qc_unloading_approved:
            raise UserError(_('Unloading must be approved before deciding on an optional Performance Test.'))
        if self.qc_performance_decision != 'pending':
            raise UserError(_('The optional Performance Test decision has already been made.'))
        self.write({'qc_performance_decision': 'required'})
        self.env['rsd.quality.stage.test'].sudo().create({
            'production_id': self.id,
            'test_kind': 'performance',
            'template_id': self.env['rsd.quality.spec.template'].search([
                ('product_id', '=', self.product_id.id), ('test_kind', '=', 'performance'),
                ('active', '=', True), ('company_id', 'in', [False, self.company_id.id]),
            ], limit=1).id,
        })
        return True

    def action_skip_optional_performance_test(self):
        self.ensure_one()
        if not (self.env.user.has_group('rsd_quality.group_unloading_request_supervisor') or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Only the Production Supervisor or System Administrator can decide whether an optional Performance Test is required.'))
        if self.product_id.performance_test_policy != 'optional':
            raise UserError(_('A Mandatory Performance Test cannot be skipped.'))
        if not self.qc_unloading_approved:
            raise UserError(_('Unloading must be approved before deciding on an optional Performance Test.'))
        if self.qc_performance_decision != 'pending':
            raise UserError(_('The optional Performance Test decision has already been made.'))
        self.write({'qc_performance_decision': 'not_required'})
        return True

    def action_create_qc_stage_test(self):
        self.ensure_one()
        kind = self.env.context.get('qc_test_kind')
        if kind != 'performance':
            raise UserError(_('Internal COA is handled by the existing Odoo Quality Check; only Performance Tests can be created here.'))
        if not (self.env.user.has_group('rsd_quality.group_application_test_user') or self.env.user.has_group('rsd_quality.group_quality_test_user') or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Only an Application Test User or System Administrator can create a Performance Test.'))
        return {'type': 'ir.actions.act_window', 'name': _('New Performance Test'), 'res_model': 'rsd.quality.stage.test', 'view_mode': 'form', 'target': 'current', 'context': {'default_production_id': self.id, 'default_test_kind': kind}}
