from odoo import models, _
from odoo.exceptions import UserError


class MailMessage(models.Model):
    _inherit = "mail.message"

    def unlink(self):
        for message in self:
            if message.model == "project.task":
                raise UserError(_("Deleting chatter messages in Project Tasks is not allowed."))
        return super().unlink()


class MailNotification(models.Model):
    _inherit = "mail.notification"

    def unlink(self):
        for notif in self:
            if notif.mail_message_id and notif.mail_message_id.model == "project.task":
                raise UserError(_("Deleting chatter messages in Project Tasks is not allowed."))
        return super().unlink()
