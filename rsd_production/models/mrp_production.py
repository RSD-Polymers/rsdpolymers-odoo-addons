from odoo import models, fields

class MrpProduction(models.Model):
    _inherit = "mrp.production"

    tare_weight = fields.Float("Tare Weight (KG)")

    packed_by = fields.Many2one(
        "res.users",
        string="Packed By"
    )

    prepared_by = fields.Many2one(
        "res.users",
        string="Prepared By",
        default=lambda self: self.env.user,
        readonly=True
    )

    def _compute_prepared_by(self):
        for rec in self:
            rec.prepared_by = rec.create_uid.name