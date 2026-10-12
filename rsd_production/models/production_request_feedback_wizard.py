from odoo import fields, models, _, api
from odoo.exceptions import UserError


class ProductionRequestFeedbackWizard(models.TransientModel):
    _name = 'production.request.feedback.wizard'
    _description = 'Production Request Store Feedback Wizard'

    request_id = fields.Many2one('production.request', required=True, readonly=True)
    intime = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Intime', required=True)
    correct = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Correct', required=True)

    def action_submit_feedback(self):
        self.ensure_one()
        request = self.request_id
        if not request._is_authorized_store_user(self.env.user):
            raise UserError(_('Only authorized Store users can submit this feedback.'))
        if not request.store_acknowledged:
            raise UserError(_('Store feedback can be submitted only after Store acknowledgement.'))
        if request.store_feedback_submitted:
            raise UserError(_('Store feedback has already been submitted.'))
        request.sudo().write({
            'store_feedback_intime': self.intime,
            'store_feedback_correct': self.correct,
            'store_feedback_submitted': True,
            'store_feedback_by': self.env.user.id,
            'store_feedback_date': fields.Datetime.now(),
        })
        request.sudo().message_post(
            body=_('Store feedback submitted for Production Request <b>%s</b>.') % request.name,
            subtype_xmlid='mail.mt_comment',
        )
        return {'type': 'ir.actions.client', 'tag': 'reload'}
