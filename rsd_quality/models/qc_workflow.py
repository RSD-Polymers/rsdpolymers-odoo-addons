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

    @api.onchange('template_id')
    def _onchange_template_id(self):
        for rec in self:
            if rec.template_id:
                rec.line_ids = [(5, 0, 0)] + [(0, 0, {'template_line_id': line.id, 'sequence': line.sequence}) for line in rec.template_id.line_ids]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('test_kind') not in ('performance', 'internal_coa'):
                raise ValidationError(_('Invalid QC test type.'))
            prod = self.env['mrp.production'].browse(vals.get('production_id')).exists()
            if not prod:
                raise ValidationError(_('Select a valid Manufacturing Order.'))
            vals['name'] = self.env['ir.sequence'].next_by_code('rsd.quality.stage.test') or _('New')
            vals.setdefault('lot_id', prod.lot_producing_id.id)
        return super().create(vals_list)

    def _check_qc_user(self):
        if not (self.env.user.has_group('rsd_quality.group_quality_test_user') or self.env.user.has_group('rsd_quality.group_unloading_request_chemist') or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Only authorised QC users can process QC tests.'))

    def action_acknowledge(self):
        self._check_qc_user()
        for rec in self:
            if rec.test_kind != 'performance' or rec.state != 'draft':
                raise UserError(_('Only a draft Performance Test can be acknowledged.'))
            if not rec.expected_result_datetime:
                raise ValidationError(_('Enter the expected result date and time.'))
            rec.write({'state': 'acknowledged', 'acknowledged_on': fields.Datetime.now()})
        return True

    def action_start(self):
        self._check_qc_user()
        for rec in self:
            if rec.state not in ('draft', 'acknowledged'):
                raise UserError(_('Only a draft or acknowledged test can be started.'))
            rec.write({'state': 'in_progress'})
        return True

    def action_evaluate(self):
        self._check_qc_user()
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
        self._check_qc_user()
        for rec in self:
            if rec.test_kind != 'performance' or rec.state != 'draft':
                raise UserError(_('Only a draft Performance Test can be marked Not Required.'))
            rec.write({'state': 'not_required', 'result_date': fields.Datetime.now()})
        return True


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


class MrpProductionQCGate(models.Model):
    _inherit = 'mrp.production'

    qc_performance_required = fields.Boolean(string='Performance Test Required', default=True, copy=False)
    qc_performance_test_ids = fields.One2many('rsd.quality.stage.test', 'production_id', domain=[('test_kind', '=', 'performance')])
    qc_internal_coa_test_ids = fields.One2many('rsd.quality.stage.test', 'production_id', domain=[('test_kind', '=', 'internal_coa')])
    qc_performance_state = fields.Selection([('pending', 'Pending'), ('passed', 'Passed'), ('failed', 'Failed'), ('not_required', 'Not Required')], compute='_compute_qc_gate')
    qc_internal_coa_state = fields.Selection([('pending', 'Pending'), ('passed', 'Passed'), ('failed', 'Failed')], compute='_compute_qc_gate')
    qc_batch_eligible = fields.Boolean(compute='_compute_qc_gate', string='Eligible for Output', store=False)

    @api.depends('qc_performance_test_ids.state', 'qc_internal_coa_test_ids.state', 'unloading_request_ids.state')
    def _compute_qc_gate(self):
        for mo in self:
            perf = mo.qc_performance_test_ids.sorted('id')[-1:] if mo.qc_performance_test_ids else self.env['rsd.quality.stage.test']
            coa = mo.qc_internal_coa_test_ids.sorted('id')[-1:] if mo.qc_internal_coa_test_ids else self.env['rsd.quality.stage.test']
            pstate = perf.state if perf else ('not_required' if not mo.qc_performance_required else 'pending')
            cstate = coa.state if coa else 'pending'
            mo.qc_performance_state = pstate if pstate in ('passed', 'failed', 'not_required') else 'pending'
            mo.qc_internal_coa_state = cstate if cstate in ('passed', 'failed') else 'pending'
            unloading_ok = any(r.state == 'accepted' for r in mo.unloading_request_ids)
            mo.qc_batch_eligible = unloading_ok and pstate in ('passed', 'not_required') and cstate == 'passed'

    def action_create_qc_stage_test(self):
        self.ensure_one()
        kind = self.env.context.get('qc_test_kind')
        if kind not in ('performance', 'internal_coa'):
            raise UserError(_('Select a valid QC test type.'))
        return {'type': 'ir.actions.act_window', 'name': _('New %s') % dict([('performance', 'Performance Test'), ('internal_coa', 'Internal COA')])[kind], 'res_model': 'rsd.quality.stage.test', 'view_mode': 'form', 'target': 'current', 'context': {'default_production_id': self.id, 'default_test_kind': kind}}
