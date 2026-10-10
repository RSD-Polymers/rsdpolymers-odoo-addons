# -*- coding: utf-8 -*-
from odoo import fields, models, _


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    production_request_id = fields.Many2one(
        'production.request',
        string='Production Request',
        index=True,
        ondelete='set null',
        copy=False,
    )

    def action_feedback(self, feedback=False, attachment_ids=None):
        approve_type = self.env.ref(
            'web_studio.mail_activity_data_approve',
            raise_if_not_found=False,
        )

        linked_requests = self.env['production.request']

        if (
                approve_type
                and not self.env.context.get('skip_production_request_ack_sync')
        ):
            for activity in self:
                request = activity.production_request_id

                if (
                        request
                        and activity.activity_type_id == approve_type
                        and request.state == 'production_done'
                        and not request.store_acknowledged
                ):
                    request._check_store_acknowledger()
                    linked_requests |= request

        result = super().action_feedback(
            feedback=feedback,
            attachment_ids=attachment_ids,
        )

        for request in linked_requests.exists():
            if request.state == 'production_done':
                request.with_context(
                    skip_activity_completion=True
                ).action_acknowledge_store()

        return result
