from odoo import models, fields


class LotLabelLayout(models.TransientModel):
    _inherit = 'lot.label.layout'

    def process(self):
        # Intercept Odoo's native '4x12' format
        if self.print_format == '4x12':

            mo_ids = False

            # Failsafe 1: Check context
            if self.env.context.get('active_model') == 'mrp.production':
                mo_ids = self.env.context.get('active_ids')

            # Failsafe 2: Trace through move lines
            if not mo_ids and self.move_line_ids:
                mos = self.move_line_ids.mapped('move_id.production_id')
                if mos:
                    mo_ids = mos.ids

            # If we found the MO, trigger your Thermal Report!
            if mo_ids:
                return self.env.ref('rsd_production.action_report_mo_thermal_pagination').report_action(mo_ids)

        # If it's not an MO, or they picked ZPL, run standard Odoo behavior
        return super().process()