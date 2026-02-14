from odoo import models, fields, api
from odoo.osv import expression


class HrLeaveType(models.Model):
    _inherit = "hr.leave.type"

    is_out_duty = fields.Boolean(string="Is Out Duty")
    is_od_comp_off = fields.Boolean(string="Is Comp Off Against OD")

    # -----------------------------
    # CORE FILTER
    # -----------------------------
    def _apply_od_filter(self, args):
        # prevent recursion
        if self.env.context.get('skip_od_filter'):
            return args

        ctx = self.env.context

        employee_id = ctx.get('default_employee_id') or ctx.get('employee_id')
        request_date = ctx.get('default_request_date_from') or ctx.get('request_date_from')

        if not employee_id or not request_date:
            return args

        # 👇 IMPORTANT: skip filter in this search
        has_od = self.env['hr.leave'].with_context(skip_od_filter=True).sudo().search_count([
            ('employee_id', '=', employee_id),
            ('state', '=', 'validate'),
            ('holiday_status_id.is_out_duty', '=', True),
            ('request_date_from', '<=', request_date),
            ('request_date_to', '>=', request_date),
        ]) > 0

        if not has_od:
            args = expression.AND([args, [('is_od_comp_off', '=', False)]])

        return args

    # dropdown + search more
    @api.model
    def _search(self, args, offset=0, limit=None, order=None):
        args = list(args or [])
        args = self._apply_od_filter(args)
        return super()._search(args, offset=offset, limit=limit, order=order)

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        args = list(args or [])
        args = self._apply_od_filter(args)
        return super().name_search(name=name, args=args, operator=operator, limit=limit)
