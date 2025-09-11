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
        is_system_admin = self.env.user.has_group('base.group_system')
        for attachment in self:
            # Check for a specific context flag used by some Odoo system processes
            if self.env.context.get('install_mode'):
                return super(IrAttachment, self).unlink()

            # Logic 1: Check if the user is in a restricted group (a global rule)
            if self.env.user.has_group('base.group_assignees') or self.env.user.has_group('base.group_checker'):
                # Add an exception for system administrators
                if not is_system_admin:
                    raise UserError(_("You are not allowed to delete any attachments."))

            # Logic 2: Check if the task is in a restricted state (a task-specific rule)
            if attachment.res_model == 'project.task' and attachment.res_id:
                task = self.env['project.task'].browse(attachment.res_id)
                if task.exists() and task.stage_id.name in ['Send For Checking', 'Approved']:
                    raise UserError(_(
                        "You cannot delete attachments from a task that is in 'Send For Checking' or 'Approved' State. "
                        "Task: %s. Current State: %s."
                    ) % (task.name, task.stage_id.name))

        # Call the parent method to actually delete the records
        return super(IrAttachment, self).unlink()
