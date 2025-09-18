# -*- coding: utf-8 -*-

from odoo import models, api, _
from odoo.exceptions import UserError, ValidationError, AccessError
import logging
_logger = logging.getLogger(__name__)

class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def create(self, vals):
        _logger.info("Attachment create method called with vals: %s", vals)

        # Check if vals is a dictionary or a list of dictionaries
        if isinstance(vals, dict):
            # Handle a single dictionary
            if vals.get('res_model') == 'project.task' and vals.get('res_id'):
                task = self.env['project.task'].browse(vals['res_id'])
                allowed_states = ['01_in_progress', '05_send_for_checking']
                if task.state not in allowed_states:
                    raise AccessError(
                        _("You are not allowed to upload an attachment here.")
                    )
        elif isinstance(vals, list):
            # Handle a list of dictionaries (multiple attachments)
            for single_vals in vals:
                if single_vals.get('res_model') == 'project.task' and single_vals.get('res_id'):
                    task = self.env['project.task'].browse(single_vals['res_id'])
                    allowed_states = ['01_in_progress', '05_send_for_checking']
                    if task.state not in allowed_states:
                        raise AccessError(
                            _("You are not allowed to upload an attachment here.")
                        )
        else:
            # If vals is a string or another unsupported type, log a warning
            _logger.warning("Unexpected data type in create method: %s", type(vals))
            # Odoo's super() call might still handle it.
            # We just need to make sure our code doesn't crash on it.

        return super(IrAttachment, self).create(vals)

    def write(self, vals):
        # self is a recordset, which can contain one or multiple records.
        # We should iterate over it to apply the logic to each record.
        for attachment in self:
            if attachment.res_model == 'project.task' and attachment.res_id:
                task = self.env['project.task'].browse(attachment.res_id)
                allowed_states = ['01_in_progress', '05_send_for_checking']
                if task.state not in allowed_states:
                    raise AccessError(
                        _("You are not allowed to update an attachment here.")
                    )
        # After all validations pass, call the original 'write' method
        return super(IrAttachment, self).write(vals)

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
