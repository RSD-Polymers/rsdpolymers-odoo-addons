from odoo import models, api, _
from odoo.exceptions import UserError

class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    @api.ondelete(at_uninstall=False) # This decorator ensures the method runs on record deletion
    def _unlink_restrict_task_attachments(self):
        # Iterate through the attachments being deleted
        for attachment in self:
            # Check if the attachment is linked to a project.task
            if attachment.res_model == 'project.task' and attachment.res_id:
                task = self.env['project.task'].browse(attachment.res_id)
                # Check if the task exists and is in a restricted state
                if task.exists() and task.state in ['05_send_for_checking', '03_approved']:
                    # If it's in a restricted state, raise an error
                    task_state_label = dict(task._fields['state'].selection).get(task.state, task.state)

                    raise UserError(_(
                        "You cannot delete attachments from a task that is in 'Send For Checking' or 'Approved' State. "
                        "Task : %s. Current State : %s."
                    ) % (task.name, task_state_label))

        # If no error is raised, proceed with the original unlink operation
        return super(IrAttachment, self)._unlink_restrict_task_attachments()