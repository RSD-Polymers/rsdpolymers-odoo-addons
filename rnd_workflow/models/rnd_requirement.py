from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


GROUP_SM_USER = 'rnd_workflow.group_rnd_sm'
GROUP_SM_MANAGER = 'rnd_workflow.group_rnd_sm_manager'
GROUP_RND_MANAGER = 'rnd_workflow.group_rnd_owner'
GROUP_SYSTEM = 'base.group_system'


class RndRequirement(models.Model):
    _name = 'rnd.requirement'
    _description = 'R&D Requirement Submission'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Requirement / Product Name', required=True, tracking=True)
    code = fields.Char(string='Request No.', readonly=True, copy=False, default='New')
    request_date = fields.Date(default=fields.Date.context_today, readonly=True)
    requester_id = fields.Many2one('res.users', string='Submitted By', default=lambda self: self.env.user,
                                   readonly=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('under_review', 'Under Review'),
        ('information_required', 'Information Required'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('converted', 'Converted to Project'),
    ], default='draft', required=True, tracking=True, copy=False)

    # Main R&D Workflow.xlsx sections
    purpose = fields.Text(string='Purpose')
    sample_provided_qty = fields.Text(string='Sample Provided & Quantity')
    product_description = fields.Text(string='Product Description (Pure Polymer / Formulation)')
    chemical_composition = fields.Text(string='Product Chemical Composition')
    implied_needs = fields.Text(string='Implied Needs')
    application_testing_needs = fields.Text(string='Application Testing Needs')
    stability_criteria = fields.Text(string='Stability Criteria')
    production_experience = fields.Selection([
        ('yes', 'Yes'), ('no', 'No'), ('not_known', 'Not Known')
    ], string='Production Experience of Similar Product')
    production_experience_details = fields.Text()
    statutory_requirements = fields.Text(string='Statutory Requirements')
    packing = fields.Text(string='Packing')
    feasibility_statement = fields.Selection([
        ('feasible', 'Feasible'), ('not_feasible', 'Not Feasible'), ('conditional', 'Feasible with Conditions')
    ], string='Feasibility Statement')
    feasibility_details = fields.Text()
    sample_requirement = fields.Selection([
        ('yes', 'Yes'), ('no', 'No'), ('to_be_discussed', 'To Be Discussed')
    ], string='Sample Requirement')

    parameter_line_ids = fields.One2many('rnd.requirement.parameter.line', 'requirement_id',
                                         string='Product Physical Specifications', copy=True)
    attachment_ids = fields.Many2many('ir.attachment', 'rnd_requirement_attachment_rel',
                                      'requirement_id', 'attachment_id', string='Supporting Documents')

    rnd_owner_id = fields.Many2one(
        'res.users', string='R&D Owner', tracking=True,
        default=lambda self: self._default_rnd_owner_id())

    @api.model
    def _default_rnd_owner_id(self):
        configured_id = self.env['ir.config_parameter'].sudo().get_param(
            'rnd_workflow.default_owner_id')
        try:
            owner = self.env['res.users'].browse(int(configured_id)).exists() if configured_id else False
        except (TypeError, ValueError):
            owner = False
        if owner and self.env.ref(GROUP_RND_MANAGER) in owner.groups_id:
            return owner.id
        return False
    expected_completion_date = fields.Date(string='R&D Committed Completion Date', tracking=True)
    rnd_comments = fields.Text(string='R&D Comments')
    rejection_reason = fields.Text(string='Rejection Reason')
    information_request = fields.Text(string='Information Required')
    project_id = fields.Many2one('rnd.project', string='Created R&D Project', readonly=True, copy=False)
    project_count = fields.Integer(compute='_compute_project_count')
    provided_by_id = fields.Many2one('res.users', string='Provided By (Sales & Marketing Manager)')
    approved_by_id = fields.Many2one('res.users', string='Approved By (Technical Director)')
    received_by_id = fields.Many2one('res.users', string='Received By (R&D Chemist)')

    @api.depends('project_id')
    def _compute_project_count(self):
        for rec in self:
            rec.project_count = 1 if rec.project_id else 0

    @api.constrains('rnd_owner_id')
    def _check_rnd_owner_group(self):
        manager_group = self.env.ref(GROUP_RND_MANAGER)
        for rec in self:
            if rec.rnd_owner_id and manager_group not in rec.rnd_owner_id.groups_id:
                raise ValidationError('The selected R&D Owner must belong to the R&D Manager group.')

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group(GROUP_SM_USER):
            raise UserError('Only Sales & Marketing users can create R&D requirements.')
        allowed_create_fields = {
            'name', 'purpose', 'sample_provided_qty', 'product_description',
            'chemical_composition', 'implied_needs', 'application_testing_needs',
            'stability_criteria', 'production_experience', 'production_experience_details',
            'statutory_requirements', 'packing', 'feasibility_statement',
            'feasibility_details', 'sample_requirement', 'parameter_line_ids',
            'attachment_ids', 'provided_by_id', 'rnd_owner_id', 'code', 'request_date',
            'requester_id', 'state',
        }
        for vals in vals_list:
            forbidden = set(vals) - allowed_create_fields
            if forbidden:
                raise UserError('Sales & Marketing cannot set R&D review, project or system fields during creation.')
            if vals.get('provided_by_id') and not self.env.user.has_group(GROUP_SM_MANAGER):
                raise UserError('Only the Sales & Marketing Manager can set the Provided By sign-off.')
            if vals.get('rnd_owner_id'):
                configured_owner = self._default_rnd_owner_id()
                if vals['rnd_owner_id'] != configured_owner:
                    raise UserError('Sales & Marketing cannot select or change the R&D Owner.')
            vals['code'] = self.env['ir.sequence'].next_by_code('rnd.requirement') or 'New'
            vals.pop('request_date', None)
            vals['requester_id'] = self.env.user.id
            vals['state'] = 'draft'
        return super().create(vals_list)

    def _workflow_write(self, vals):
        """Internal write for methods that have already authorized a workflow transition."""
        return super().write(vals)

    def write(self, vals):
        user = self.env.user
        is_rnd_manager = user.has_group(GROUP_RND_MANAGER)
        is_sm_manager = user.has_group(GROUP_SM_MANAGER)
        is_sm_user = user.has_group(GROUP_SM_USER)
        allowed_sm_fields = {
            'name', 'purpose', 'sample_provided_qty', 'product_description',
            'chemical_composition', 'implied_needs', 'application_testing_needs',
            'stability_criteria', 'production_experience', 'production_experience_details',
            'statutory_requirements', 'packing', 'feasibility_statement',
            'feasibility_details', 'sample_requirement', 'parameter_line_ids',
            'attachment_ids', 'provided_by_id',
        }
        if is_rnd_manager:
            if any(rec.state == 'converted' for rec in self):
                if 'expected_completion_date' in vals:
                    raise UserError('After project creation, update the Project Deadline on the R&D Project. The requirement date will synchronize automatically.')
                if 'rnd_owner_id' in vals:
                    raise UserError('After project creation, update the R&D Project Owner on the project. The requirement owner will synchronize automatically.')
            rnd_fields = {
                'rnd_owner_id', 'expected_completion_date', 'rnd_comments',
                'information_request', 'rejection_reason', 'approved_by_id', 'received_by_id',
            }
            if set(vals) - rnd_fields:
                raise UserError('R&D can update review and commitment fields only. Submitted Sales requirements are preserved.')
            return super().write(vals)
        if is_sm_user or is_sm_manager:
            if set(vals) - allowed_sm_fields:
                raise UserError('Sales & Marketing cannot change R&D review, commitment or workflow fields.')
            if 'provided_by_id' in vals and not is_sm_manager:
                raise UserError('Only the Sales & Marketing Manager can update the Provided By sign-off.')
            for rec in self:
                if rec.state not in ('draft', 'information_required'):
                    raise UserError('Submitted requirements cannot be edited unless R&D has requested information.')
                if rec.requester_id != user and not is_sm_manager:
                    raise UserError('Sales & Marketing users can edit only their own requirements.')
            return super().write(vals)
        raise UserError('You are not allowed to modify R&D requirements.')

    def _check_rnd_manager(self):
        if not self.env.user.has_group(GROUP_RND_MANAGER):
            raise UserError('Only the R&D Manager can perform this action.')

    def _validate_submission(self):
        for rec in self:
            if not rec.name:
                raise UserError('Enter the requirement / product name.')
            if not rec.parameter_line_ids:
                raise UserError('Select at least one applicable Product Physical Specification parameter.')
            for line in rec.parameter_line_ids:
                if line.specification_type == 'dropdown' and not line.option_id:
                    raise UserError(f'Select a desired specification for {line.parameter_name}.')
                if line.specification_type == 'range' and not (line.min_value_set or line.max_value_set or line.specification_text):
                    raise UserError(f'Enter a range or specification for {line.parameter_name}.')
                if line.specification_type == 'number' and not (line.numeric_value_set or line.specification_text):
                    raise UserError(f'Enter a numeric value for {line.parameter_name}.')
                if line.specification_type == 'text' and not line.specification_text:
                    raise UserError(f'Enter a specification for {line.parameter_name}.')

    def action_submit(self):
        if not self.env.user.has_group(GROUP_SM_USER):
            raise UserError('Only Sales & Marketing can submit requirements.')
        for rec in self:
            if rec.state != 'draft':
                raise UserError('Only draft requirements can be submitted.')
            if rec.requester_id != self.env.user and not self.env.user.has_group(GROUP_SM_MANAGER):
                raise UserError('You can submit only your own requirements.')
            rec._validate_submission()
            rec._workflow_write({'state': 'submitted'})
            rec.message_post(body='Requirement submitted to R&D.')
            rec._notify_rnd_manager('New R&D requirement submitted')

    def _notify_rnd_manager(self, summary):
        managers = self.env.ref(GROUP_RND_MANAGER).users
        for manager in managers:
            self.activity_schedule('mail.mail_activity_data_todo', user_id=manager.id,
                                   summary=summary, note=f'Requirement {self.code}: {self.name}')

    def _notify_requester(self, summary, note):
        for rec in self:
            if rec.requester_id:
                rec.activity_schedule('mail.mail_activity_data_todo',
                                      user_id=rec.requester_id.id,
                                      summary=summary, note=note)

    def action_start_review(self):
        self._check_rnd_manager()
        for rec in self:
            if rec.state != 'submitted':
                raise UserError('Only submitted requirements can enter review.')
            rec._workflow_write({'state': 'under_review'})
            rec.message_post(body='R&D review started.')

    def action_request_information(self):
        self._check_rnd_manager()
        for rec in self:
            if rec.state not in ('submitted', 'under_review'):
                raise UserError('Information can only be requested for submitted requirements.')
            if not rec.information_request:
                raise UserError('Enter the information required from Sales & Marketing.')
            rec._workflow_write({'state': 'information_required'})
            rec.message_post(body=f'Information required: {rec.information_request}')
            rec._notify_requester('R&D requires more information',
                                  f'Please update requirement {rec.code}: {rec.information_request}')

    def action_resubmit(self):
        if not self.env.user.has_group(GROUP_SM_USER):
            raise UserError('Only Sales & Marketing can resubmit a requirement.')
        for rec in self:
            if rec.state != 'information_required':
                raise UserError('Only requirements marked Information Required can be resubmitted.')
            if rec.requester_id != self.env.user and not self.env.user.has_group(GROUP_SM_MANAGER):
                raise UserError('Only the requester or Sales & Marketing Manager can resubmit.')
            rec._validate_submission()
            # After submission, the requirement is locked again for audit history.
            rec._workflow_write({'state': 'submitted'})
            rec.message_post(body='Additional information submitted to R&D.')
            rec._notify_rnd_manager('R&D requirement resubmitted')

    def action_accept(self):
        self._check_rnd_manager()
        for rec in self:
            if rec.state != 'under_review':
                raise UserError('Requirement must be Under Review before acceptance.')
            if not rec.expected_completion_date:
                raise UserError('Enter the R&D committed completion date before accepting.')
            if not rec.rnd_owner_id:
                raise UserError('Assign an R&D Project Owner before accepting.')
            if self.env.ref(GROUP_RND_MANAGER) not in rec.rnd_owner_id.groups_id:
                raise UserError('The selected R&D Owner must belong to the R&D Manager group.')
            rec._workflow_write({'state': 'accepted'})
            rec.message_post(body=f'Requirement accepted. Expected completion: {rec.expected_completion_date}.')
            rec._notify_requester('R&D committed date confirmed',
                                  f'R&D accepted requirement {rec.code}. Committed completion date: {rec.expected_completion_date}.')

    def action_reject(self):
        self._check_rnd_manager()
        for rec in self:
            if rec.state not in ('submitted', 'under_review'):
                raise UserError('Only submitted or under-review requirements can be rejected.')
            if not rec.rejection_reason:
                raise UserError('Enter a rejection reason.')
            rec._workflow_write({'state': 'rejected'})
            rec.message_post(body=f'Requirement rejected: {rec.rejection_reason}')
            rec._notify_requester('R&D requirement rejected',
                                  f'Requirement {rec.code} was rejected: {rec.rejection_reason}')

    def action_create_project(self):
        self._check_rnd_manager()
        for rec in self:
            if rec.state != 'accepted':
                raise UserError('Only accepted requirements can be converted into projects.')
            if rec.project_id:
                raise UserError('An R&D Project has already been created for this requirement.')
            project = self.env['rnd.project'].create({
                'name': rec.name,
                'sm_user_id': rec.requester_id.id,
                'rnd_owner_id': rec.rnd_owner_id.id,
                'delivery_date': rec.expected_completion_date,
                'deadline': rec.expected_completion_date,
                'requirement_id': rec.id,
                'description': rec.purpose or rec.product_description or '',
                'state': 'planning',
            })
            rec._workflow_write({
                'state': 'converted',
                'project_id': project.id,
            })
            rec.message_post(body=f'Converted to R&D Project {project.code}.')
            rec._notify_requester('R&D project created',
                                  f'Requirement {rec.code} has been accepted and converted into an R&D project. R&D committed completion date: {rec.expected_completion_date}.')
        return self[:1].action_view_project() if self else True

    def action_view_project(self):
        if not self.env.user.has_group(GROUP_RND_MANAGER):
            raise UserError('Only the R&D Manager can open the internal R&D Project.')
        self.ensure_one()
        if not self.project_id:
            raise UserError('No R&D Project has been created yet.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'R&D Project',
            'res_model': 'rnd.project',
            'view_mode': 'form',
            'res_id': self.project_id.id,
            'target': 'current',
        }

    def unlink(self):
        if not self.env.user.has_group(GROUP_SM_USER):
            raise UserError('Only Sales & Marketing can delete draft requirements.')
        if any(rec.state != 'draft' for rec in self):
            raise UserError('Only draft requirements can be deleted.')
        return super().unlink()


class RndRequirementParameterLine(models.Model):
    _name = 'rnd.requirement.parameter.line'
    _description = 'R&D Requirement SOP Specification'
    _order = 'sequence, id'

    requirement_id = fields.Many2one('rnd.requirement', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    parameter_id = fields.Many2one('rnd.sop.parameter', string='SOP Parameter', required=True,
                                   domain="[('active', '=', True)]")
    parameter_name = fields.Char(required=True)
    sop_number = fields.Char(string='SOP Number')
    specification_type = fields.Selection([
        ('dropdown', 'Dropdown'), ('range', 'Numeric Range'),
        ('number', 'Number'), ('text', 'Text')
    ], required=True)
    unit = fields.Char()
    option_id = fields.Many2one('rnd.sop.parameter.option', string='Selected Option')
    option_value = fields.Char(string='Selected Option Snapshot')
    min_value = fields.Float(string='Minimum')
    min_value_set = fields.Boolean()
    max_value = fields.Float(string='Maximum')
    max_value_set = fields.Boolean()
    numeric_value = fields.Float(string='Value')
    numeric_value_set = fields.Boolean()
    specification_text = fields.Text(string='Desired Specification / Notes')
    specification_hint = fields.Char(string='Specification Hint')
    display_specification = fields.Char(compute='_compute_display_specification', store=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group(GROUP_SM_USER):
            raise UserError('Only Sales & Marketing can add SOP parameters to a requirement.')
        for vals in vals_list:
            requirement = self.env['rnd.requirement'].browse(vals.get('requirement_id')).exists()
            if not requirement or requirement.state not in ('draft', 'information_required'):
                raise UserError('SOP parameters can be added only while a requirement is Draft or Information Required.')
            parameter = self.env['rnd.sop.parameter'].browse(vals.get('parameter_id')).exists()
            if not parameter or not parameter.active:
                raise UserError('Select an active SOP parameter.')
            if parameter:
                vals['parameter_name'] = parameter.name
                vals['sop_number'] = parameter.sop_number
                vals['specification_type'] = parameter.specification_type
                vals['unit'] = parameter.unit
                vals.setdefault('specification_hint', parameter.specification_hint)
                vals.setdefault('specification_text', parameter.default_specification or False)
            option = self.env['rnd.sop.parameter.option'].browse(vals.get('option_id')).exists()
            if vals.get('option_id') and not option:
                raise ValidationError('The selected dropdown option no longer exists.')
            if option:
                if not option.active:
                    raise ValidationError('The selected dropdown option is archived. Select an active option.')
                if option.parameter_id != parameter:
                    raise ValidationError('The selected option does not belong to the selected SOP parameter.')
                if parameter.specification_type != 'dropdown':
                    raise ValidationError('A dropdown option can only be selected for a Dropdown parameter.')
                vals['option_value'] = option.name
            else:
                vals['option_value'] = False

            # Preserve explicit zero values while distinguishing an empty field from zero.
            for value_field, flag_field in (
                ('min_value', 'min_value_set'),
                ('max_value', 'max_value_set'),
                ('numeric_value', 'numeric_value_set'),
            ):
                # Flags are derived server-side; callers cannot mark an empty field as entered.
                vals[flag_field] = (
                    value_field in vals
                    and vals[value_field] is not False
                    and vals[value_field] is not None
                )
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.user.has_group(GROUP_SM_USER):
            raise UserError('Only Sales & Marketing can modify submitted SOP parameter lines.')
        for line in self:
            if line.requirement_id.state not in ('draft', 'information_required'):
                raise UserError('Submitted SOP specifications are locked. Contact R&D if a correction is required.')

        vals = dict(vals)
        parameter_snapshot_fields = {
            'parameter_name', 'sop_number', 'specification_type', 'unit', 'specification_hint',
        }
        if parameter_snapshot_fields.intersection(vals) and 'parameter_id' not in vals:
            raise UserError('SOP parameter snapshot fields are maintained automatically from the selected parameter.')
        if 'option_value' in vals and 'option_id' not in vals:
            raise UserError('The selected option snapshot is maintained automatically from the selected option.')
        if 'requirement_id' in vals:
            raise UserError('An SOP parameter line cannot be moved to another requirement.')

        parameter = None
        if 'parameter_id' in vals:
            parameter = self.env['rnd.sop.parameter'].browse(vals['parameter_id']).exists()
            if not parameter or not parameter.active:
                raise UserError('Select an active SOP parameter.')
            vals.update(
                parameter_name=parameter.name,
                sop_number=parameter.sop_number,
                specification_type=parameter.specification_type,
                unit=parameter.unit,
                specification_hint=parameter.specification_hint,
            )
            if 'option_id' not in vals:
                vals.update(option_id=False, option_value=False)
            if 'min_value' not in vals:
                vals.update(min_value=False, min_value_set=False)
            if 'max_value' not in vals:
                vals.update(max_value=False, max_value_set=False)
            if 'numeric_value' not in vals:
                vals.update(numeric_value=False, numeric_value_set=False)
            if 'specification_text' not in vals:
                vals['specification_text'] = parameter.default_specification or False

        if 'option_id' in vals:
            option = self.env['rnd.sop.parameter.option'].browse(vals['option_id']).exists()
            if vals['option_id'] and not option:
                raise ValidationError('The selected dropdown option no longer exists.')
            target_parameters = parameter or self.mapped('parameter_id')
            if option:
                if not option.active:
                    raise ValidationError('The selected dropdown option is archived. Select an active option.')
                if any(target != option.parameter_id for target in target_parameters):
                    raise ValidationError('The selected option does not belong to the selected SOP parameter.')
                if any(target.specification_type != 'dropdown' for target in target_parameters):
                    raise ValidationError('A dropdown option can only be selected for a Dropdown parameter.')
                vals['option_value'] = option.name
            else:
                vals['option_value'] = False

        # Explicit numeric zero is valid; False/None means the input was cleared.
        for value_field, flag_field in (
            ('min_value', 'min_value_set'),
            ('max_value', 'max_value_set'),
            ('numeric_value', 'numeric_value_set'),
        ):
            if value_field in vals:
                vals[flag_field] = vals[value_field] is not False and vals[value_field] is not None
            else:
                # Do not allow clients to forge the hidden entered-value flags.
                vals.pop(flag_field, None)

        return super().write(vals)

    def unlink(self):
        if not self.env.user.has_group(GROUP_SM_USER):
            raise UserError('Only Sales & Marketing can remove SOP parameter lines.')
        if any(line.requirement_id.state not in ('draft', 'information_required') for line in self):
            raise UserError('Submitted SOP specifications are locked.')
        return super().unlink()

    @api.onchange('parameter_id')
    def _onchange_parameter_id(self):
        for line in self:
            if line.parameter_id:
                parameter = line.parameter_id
                line.parameter_name = parameter.name
                line.sop_number = parameter.sop_number
                line.specification_type = parameter.specification_type
                line.unit = parameter.unit
                line.specification_hint = parameter.specification_hint
                line.option_id = False
                line.option_value = False
                line.min_value = False
                line.min_value_set = False
                line.max_value = False
                line.max_value_set = False
                line.numeric_value = False
                line.numeric_value_set = False
                line.specification_text = parameter.default_specification or False

    @api.onchange('min_value')
    def _onchange_min_value(self):
        for line in self:
            # False/None means the input was cleared; numeric zero remains valid.
            line.min_value_set = line.min_value is not False and line.min_value is not None

    @api.onchange('max_value')
    def _onchange_max_value(self):
        for line in self:
            # False/None means the input was cleared; numeric zero remains valid.
            line.max_value_set = line.max_value is not False and line.max_value is not None

    @api.onchange('numeric_value')
    def _onchange_numeric_value(self):
        for line in self:
            # False/None means the input was cleared; numeric zero remains valid.
            line.numeric_value_set = line.numeric_value is not False and line.numeric_value is not None

    @api.onchange('option_id')
    def _onchange_option_id(self):
        for line in self:
            line.option_value = line.option_id.name if line.option_id else False

    @api.depends('specification_type', 'option_value', 'min_value', 'min_value_set',
                 'max_value', 'max_value_set', 'numeric_value', 'numeric_value_set',
                 'specification_text', 'unit')
    def _compute_display_specification(self):
        for line in self:
            if line.specification_type == 'dropdown':
                value = line.option_value or ''
            elif line.specification_type == 'range':
                value = ''
                if line.min_value_set or line.max_value_set:
                    lower = f'{line.min_value:g}' if line.min_value_set else ''
                    upper = f'{line.max_value:g}' if line.max_value_set else ''
                    value = f'{lower} - {upper}'.strip(' -')
                if line.specification_text:
                    value = (value + ' ' + line.specification_text).strip()
            elif line.specification_type == 'number':
                value = f'{line.numeric_value:g}' if line.numeric_value_set else ''
                if line.specification_text:
                    value = (value + ' ' + line.specification_text).strip()
            else:
                value = line.specification_text or ''
            if value and line.unit:
                value = f'{value} {line.unit}'
            line.display_specification = value

    _sql_constraints = [
        ('requirement_parameter_unique', 'unique(requirement_id, parameter_id)',
         'A parameter can be selected only once per requirement.'),
    ]

    @api.constrains('parameter_id', 'specification_type', 'option_id',
                    'min_value', 'max_value', 'min_value_set', 'max_value_set',
                    'numeric_value', 'numeric_value_set')
    def _check_specification(self):
        for line in self:
            if line.option_id:
                if line.specification_type != 'dropdown':
                    raise ValidationError('A dropdown option can only be used with a Dropdown parameter.')
                if line.option_id.parameter_id != line.parameter_id:
                    raise ValidationError('The selected option does not belong to the selected SOP parameter.')
                if not line.option_id.active:
                    raise ValidationError('The selected dropdown option is archived. Select an active option.')
            if line.specification_type == 'range':
                if line.min_value_set and line.max_value_set and line.min_value > line.max_value:
                    raise ValidationError('Minimum value cannot be greater than maximum value.')
            elif line.min_value_set or line.max_value_set:
                raise ValidationError('Minimum and maximum values can only be entered for Numeric Range parameters.')
            if line.specification_type != 'number' and line.numeric_value_set:
                raise ValidationError('A numeric value can only be entered for Number parameters.')
