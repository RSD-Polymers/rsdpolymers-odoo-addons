# project_customization/models/project_task_refuse_wizard.py
from odoo import models, fields, _
from odoo.exceptions import UserError


class ProjectTaskRefuseWizard(models.TransientModel):
    _name = 'project.task.reject.wizard'
    _description = 'Wizard to enter rejection reason for a task'

    task_id = fields.Many2one('project.task', string='Task', required=True, ondelete='cascade')
    rejection_reason = fields.Text(string='Reason for Rejection', required=True)

    def action_reject_confirm(self):
        """
        Confirms rejection and updates the task with remarks and sets the rejected flag.
        Also, clears the accepted flag if it was set.
        """
        active_id = self.env.context.get('active_id')
        if not active_id:
            raise UserError("No task selected for rejection.")

        task = self.env['project.task'].browse(active_id)
        if not task:
            raise UserError("Selected task not found.")

        task.with_context(is_action_specific_task_op=True).write({
            'is_rejected': True,
            'is_accepted': False,  # Assuming rejection implies not accepted
            'rejection_remarks': self.rejection_reason,  # Get remarks from the wizard field
            'state': '06_rejected',
        })

        # It's usually better to post a message to the task's chatter
        # for a permanent record of the rejection reason.
        self.task_id.message_post(
            body=_("Task has been **Rejected** with the following reason:\n%s") % self.rejection_reason,
            subject=_("Task Rejection")
        )
        return {'type': 'ir.actions.act_window_close'}