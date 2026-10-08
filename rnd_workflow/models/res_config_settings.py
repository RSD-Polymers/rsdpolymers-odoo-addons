from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rnd_notify_stage_change = fields.Boolean(
        string='Notify users on stage change',
        config_parameter='rnd_workflow.notify_stage_change',
        default=True,
        help='When enabled, an activity/notification is created for the '
             'responsible user each time a project or experiment moves to a new stage.')

    rnd_default_owner_id = fields.Many2one(
        'res.users', string='Default R&D Project Owner',
        config_parameter='rnd_workflow.default_owner_id')
