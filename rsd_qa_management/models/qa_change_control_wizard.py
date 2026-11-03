from odoo import fields, models, _
from odoo.exceptions import AccessError, UserError


class QaChangeControlRejectWizard(models.TransientModel):
    _name = 'qa.change.control.reject.wizard'
    _description = 'Reject Change Request'

    change_control_id = fields.Many2one('qa.change.control', required=True, readonly=True)
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.ensure_one()
        cr = self.change_control_id.exists()
        if not cr:
            raise UserError(_('The Change Request no longer exists.'))

        cr._check_qa_user()
        if cr.state != 'open':
            raise UserError(_('Only Open requests can be rejected.'))
        if not self.reason or not self.reason.strip():
            raise UserError(_('Please provide a rejection reason.'))

        reason = self.reason.strip()
        cr.write({'rejection_reason': reason})
        cr._transition('rejected', _('Change Request rejected by QA. Reason: %s') % reason)
        cr.message_post(body=_('Rejection reason: %s') % reason)
        return {'type': 'ir.actions.act_window_close'}



class QaChangeControlApprovalWizard(models.TransientModel):
    _name = 'qa.change.control.approval.wizard'
    _description = 'Refuse Change Request Approval'

    change_control_id = fields.Many2one(
        'qa.change.control',
        required=True,
        readonly=True
    )
    reason = fields.Text(
        string='Refusal Reason',
        required=True
    )

    def action_confirm(self):
        self.ensure_one()

        cr = self.change_control_id.exists()

        if not cr:
            raise UserError(_('The Change Request no longer exists.'))

        # Only a QA Manager can refuse the approval.
        cr._check_ab_user()

        if cr.state != 'approval_pending':
            raise UserError(
                _('This request is not awaiting approval.')
            )

        if not self.reason or not self.reason.strip():
            raise UserError(
                _('Please provide a reason for refusing the request.')
            )

        cr._record_ab_refusal(self.reason.strip())

        return {'type': 'ir.actions.act_window_close'}

class QaChangeControlTaskReworkWizard(models.TransientModel):
    _name = 'qa.change.control.task.rework.wizard'
    _description = 'Request Change Control Task Rework'

    task_id = fields.Many2one(
        'qa.change.control.task', string='Evaluation Task', required=True, readonly=True
    )
    instructions = fields.Text(
        string='Rework Instructions',
        required=True,
        help='Explain exactly what the assigned employee must correct, add or resubmit.'
    )

    def action_confirm(self):
        self.ensure_one()
        if not (
            self.env.user.has_group('rsd_qa_management.group_qa_officer')
            or self.env.user.has_group('rsd_qa_management.group_qa_manager')
            or self.env.user.has_group('base.group_system')
        ):
            raise AccessError(_('Only QA can request task rework.'))
        self.task_id._apply_rework_request(self.instructions)
        return {'type': 'ir.actions.act_window_close'}
