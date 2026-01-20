# models/product_category.py
from odoo import models, fields

class ProductCategory(models.Model):
    _inherit = 'product.category'

    is_packaging_category = fields.Boolean(
        string="Packaging Category",
        help="Products under this category are treated as packaging materials in manufacturing."
    )
