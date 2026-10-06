# -*- coding: utf-8 -*-

from odoo import fields, models


class IrSequence(models.Model):
    _inherit = 'ir.sequence'

    def _create_date_range_seq(self, date):
        """Create Production Request sequence ranges using the Indian FY."""
        self.ensure_one()

        if self.code != 'production.request' or not self.use_date_range:
            return super()._create_date_range_seq(date)

        date_obj = fields.Date.to_date(date)

        if date_obj.month >= 4:
            date_from = date_obj.replace(month=4, day=1)
            date_to = date_obj.replace(
                year=date_obj.year + 1,
                month=3,
                day=31,
            )
        else:
            date_from = date_obj.replace(
                year=date_obj.year - 1,
                month=4,
                day=1,
            )
            date_to = date_obj.replace(month=3, day=31)

        date_range_model = self.env['ir.sequence.date_range'].sudo()

        existing = date_range_model.search([
            ('sequence_id', '=', self.id),
            ('date_from', '=', date_from),
            ('date_to', '=', date_to),
        ], limit=1)

        if existing:
            return existing

        return date_range_model.create({
            'date_from': date_from,
            'date_to': date_to,
            'sequence_id': self.id,
            'number_next': 1,
        })

    def _get_prefix_suffix(self, date=None, date_range=None):
        """Use Indian financial year in Production Request sequence.

        Format:
            PR/26-27/0001
        """
        prefix, suffix = super()._get_prefix_suffix(
            date=date,
            date_range=date_range,
        )

        if self.code != 'production.request':
            return prefix, suffix

        sequence_date = fields.Date.to_date(
            date or self._context.get('ir_sequence_date')
        )

        if not sequence_date:
            sequence_date = fields.Date.context_today(self)

        if sequence_date.month >= 4:
            fy_start = sequence_date.year
            fy_end = sequence_date.year + 1
        else:
            fy_start = sequence_date.year - 1
            fy_end = sequence_date.year

        financial_year = f"{fy_start % 100:02d}-{fy_end % 100:02d}"

        return f"PR/{financial_year}/", suffix