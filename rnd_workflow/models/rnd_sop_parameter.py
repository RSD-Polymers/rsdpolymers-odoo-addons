from odoo import api, fields, models
from odoo.exceptions import UserError


GROUP_RND_MANAGER = 'rnd_workflow.group_rnd_owner'
GROUP_SYSTEM = 'base.group_system'


class RndSopParameter(models.Model):
    _name = 'rnd.sop.parameter'
    _description = 'R&D SOP Parameter'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=False)
    sop_number = fields.Char(string='SOP Number')
    specification_type = fields.Selection([
        ('dropdown', 'Dropdown'),
        ('range', 'Numeric Range'),
        ('number', 'Number'),
        ('text', 'Text'),
    ], required=True, default='text')
    default_specification = fields.Char()
    specification_hint = fields.Char(string='Specification Hint')
    unit = fields.Char(string='Unit of Measurement')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    option_ids = fields.One2many('rnd.sop.parameter.option', 'parameter_id', string='Dropdown Options')
    note = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.user.has_group(GROUP_RND_MANAGER) or self.env.user.has_group(GROUP_SYSTEM)):
            raise UserError('Only the R&D Manager or Odoo Administrator can configure SOP parameters.')
        return super().create(vals_list)

    def write(self, vals):
        if not (self.env.user.has_group(GROUP_RND_MANAGER) or self.env.user.has_group(GROUP_SYSTEM)):
            raise UserError('Only the R&D Manager or Odoo Administrator can configure SOP parameters.')
        return super().write(vals)

    def unlink(self):
        if not (self.env.user.has_group(GROUP_RND_MANAGER) or self.env.user.has_group(GROUP_SYSTEM)):
            raise UserError('Only the R&D Manager or Odoo Administrator can delete SOP parameters.')
        if any(self.mapped('active')):
            raise UserError('Archive SOP parameters instead of deleting active configuration.')
        return super().unlink()


class RndSopParameterOption(models.Model):
    _name = 'rnd.sop.parameter.option'
    _description = 'R&D SOP Parameter Option'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    parameter_id = fields.Many2one('rnd.sop.parameter', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
