# -*- coding: utf-8 -*-

from odoo import models, api, _
from odoo.exceptions import UserError


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def unlink(self):
        """
        Overrides the unlink method to prevent attachments from being deleted
        if they are linked to a project task that is not in a 'Done' or 'Cancelled' stage.
        """
        # Iterate through the attachments being deleted
        for attachment in self:
            # Check if the attachment is linked to a project.task
            if attachment.res_model == 'project.task' and attachment.res_id:
                task = self.env['project.task'].browse(attachment.res_id)
                # Check if the task exists and its stage name is in the restricted list
                if task.exists() and task.stage_id.name in ['Send For Checking', 'Approved']:
                    # If it's in a restricted state, raise an error
                    raise UserError(_(
                        "You cannot delete attachments from a task that is in 'Send For Checking' or 'Approved' State. "
                        "Task: %s. Current State: %s."
                    ) % (task.name, task.stage_id.name))

        # Call the parent method to actually delete the records
        return super(IrAttachment, self).unlink()
