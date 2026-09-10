from odoo import models, api, fields


class AccountMove(models.Model):
    _inherit = 'account.move'

    delivery_terms = fields.Text(string="Terms of Delivery")
    dispatch_doc_no = fields.Char(string="Dispatch Doc No")
    dispatch_through = fields.Char(string="Dispatched through")
    bill_of_lading = fields.Char(string="Bill of Lading/LR-RR No")
    motor_vehicle_no = fields.Char(string="Motor Vehicle No")
    delivery_note = fields.Char(string="Delivery Note")
    tally_response = fields.Char(
        string="Tally Sync Status",
        readonly=True,
        help="Populated by a Tally integration app if one is installed. Left blank otherwise.",
    )

    def action_print_custom_invoice(self):
        """Return your custom invoice report."""
        return self.env.ref('rsd_sales.action_custom_invoice_pdf').report_action(self, config=False)

    @api.model
    def _get_tax_components(self, tax):
        """
        Helper to safely extract the tax rate and determine its component type (CGST, SGST, or IGST).
        Returns the effective rate and the type for easy identification.
        """
        if tax.amount_type != 'percent' or tax.amount <= 0:
            return {'rate': 0.0, 'type': 'none'}

        tax_name = tax.name.upper()
        rate = tax.amount

        if 'IGST' in tax_name:
            return {'rate': rate, 'type': 'igst'}

        # If it's a combined tax, assume 50/50 split on the rate for display purposes.
        elif 'CGST' in tax_name:
            return {'rate': rate, 'type': 'cgst'}

        elif 'SGST' in tax_name:
            return {'rate': rate, 'type': 'sgst'}

        return {'rate': rate, 'type': 'other'}

    def _get_hsn_summary_data(self):
        """
        Calculates and groups invoice line tax data by HSN/SAC code for the summary table.
        It accumulates the actual tax amounts calculated by Odoo for each line to ensure
        accuracy and match the invoice totals, and fixes the logic for setting the rate
        only if it's not already set for that HSN component.
        """
        self.ensure_one()
        summary_data = {}

        # Filter lines that have both HSN code and taxes
        lines_to_summarize = self.invoice_line_ids.filtered(
            lambda l: l.product_id and l.product_id.l10n_in_hsn_code and l.tax_ids)

        for line in lines_to_summarize:
            hsn = line.product_id.l10n_in_hsn_code

            # Initialize or retrieve the HSN entry
            if hsn not in summary_data:
                summary_data[hsn] = {
                    'hsn_code': hsn,
                    'taxable_value': 0.0,
                    # Rates are stored for display, amounts for accumulation
                    'cgst_rate': 0.0,
                    'sgst_rate': 0.0,
                    'igst_rate': 0.0,
                    'cgst_amount': 0.0,
                    'sgst_amount': 0.0,
                    'igst_amount': 0.0,
                }

            hsn_entry = summary_data[hsn]
            # 1. Accumulate the taxable base (price_subtotal)
            hsn_entry['taxable_value'] += line.price_subtotal

            # 2. Use Odoo's built-in tax computation for the line to get the accurate, rounded amounts
            tax_results = line.tax_ids.compute_all(
                line.price_unit * (1 - (line.discount / 100.0)),
                currency=line.move_id.currency_id,
                quantity=line.quantity,
                product=line.product_id,
                partner=line.move_id.partner_id,
                is_refund=line.move_id.move_type in ('out_refund', 'in_refund')
            )

            # 3. Process the tax breakdown and accumulate the actual amounts
            for tax_info in tax_results.get('taxes', []):
                tax_obj = self.env['account.tax'].browse(tax_info['id'])
                components = self._get_tax_components(tax_obj)
                tax_amount = tax_info['amount']  # The actual calculated, rounded tax amount

                tax_type = components['type']
                rate = components['rate']

                # Accumulate the amounts and set the rate for display.
                # Crucial Fix: Only set the rate if it hasn't been set yet (or is 0.0)
                # to avoid overwriting a rate if multiple lines for the same HSN exist.
                if tax_type == 'igst':
                    # Set the rate only if it's not already set
                    if hsn_entry['igst_rate'] == 0.0:
                        hsn_entry['igst_rate'] = rate
                    hsn_entry['igst_amount'] += tax_amount

                elif tax_type == 'cgst':
                    if hsn_entry['cgst_rate'] == 0.0:
                        hsn_entry['cgst_rate'] = rate
                    hsn_entry['cgst_amount'] += tax_amount

                elif tax_type == 'sgst':
                    if hsn_entry['sgst_rate'] == 0.0:
                        hsn_entry['sgst_rate'] = rate
                    hsn_entry['sgst_amount'] += tax_amount

        # 4. Final pass: Apply currency rounding and calculate the final row total.
        final_summary = []
        currency = self.currency_id or self.company_id.currency_id

        for hsn, data in summary_data.items():
            # Rounding to ensure precision matches the invoice totals
            data['taxable_value'] = currency.round(data['taxable_value'])
            data['cgst_amount'] = currency.round(data['cgst_amount'])
            data['sgst_amount'] = currency.round(data['sgst_amount'])
            data['igst_amount'] = currency.round(data['igst_amount'])

            data['total_tax_amount_hsn'] = data['cgst_amount'] + data['sgst_amount'] + data['igst_amount']
            data['total_tax_amount_hsn'] = currency.round(data['total_tax_amount_hsn'])

            final_summary.append(data)

        return final_summary