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
        if self.env.context.get('skip_od_filter'):
            return args

        ctx = self.env.context
        employee_id = ctx.get('default_employee_id') or ctx.get('employee_id')
        od_date = ctx.get('od_worked_on')

        # allow current selected type to be readable
        active_id = ctx.get('active_id')
        current_type_id = ctx.get('default_holiday_status_id')

        # If no OD date → hide comp off EXCEPT current record
        if not employee_id or not od_date:
            if current_type_id:
                args = expression.AND([
                    args,
                    ['|',
                     ('id', '=', current_type_id),
                     ('is_od_comp_off', '=', False)
                     ]
                ])
            else:
                args = expression.AND([args, [('is_od_comp_off', '=', False)]])
            return args

        has_od = self.env['hr.leave'].with_context(skip_od_filter=True).sudo().search_count([
            ('employee_id', '=', employee_id),
            ('state', '=', 'validate'),
            ('holiday_status_id.is_out_duty', '=', True),
            ('request_date_from', '<=', od_date),
            ('request_date_to', '>=', od_date),
        ]) > 0

        if not has_od:
            args = expression.AND([args, [('is_od_comp_off', '=', False)]])

        return args

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        args = list(args or [])
        args = self._apply_od_filter(args)
        return super().name_search(name=name, args=args, operator=operator, limit=limit)
