from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rnd_notify_stage_change = fields.Boolean(
        string='Notify users on stage change',
        config_parameter='rnd_workflow.notify_stage_change',
        default=True,
        help='When enabled, an activity/notification is created for the '
             'assigned users when an experiment moves to a new stage.')

    rnd_default_owner_id = fields.Many2one(
        'res.users', string='Default R&D Project Owner',
        config_parameter='rnd_workflow.default_owner_id')


    @api.constrains('rnd_default_owner_id')
    def _check_rnd_default_owner_group(self):
        owner_group = self.env.ref('rnd_workflow.group_rnd_owner')
        for rec in self:
            if rec.rnd_default_owner_id and owner_group not in rec.rnd_default_owner_id.groups_id:
                raise ValidationError('The default R&D Project Owner must belong to the R&D Manager group.')
