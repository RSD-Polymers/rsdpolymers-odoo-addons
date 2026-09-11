from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class RmIssue(models.Model):
    _name = 'rm.issue'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'RM Issue'
    _rec_name = 'name'

    name = fields.Char(default='New', readonly=True, copy=False)

    mo_id = fields.Many2one('mrp.production', required=True, string="Manufacturing Order")
    sale_id = fields.Many2one('sale.order', string="Sales Order")

    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    internal_transfer_ref = fields.Many2one(
        'stock.picking',
        string='Internal Transfer'
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('requested', 'Requested'),
        ('issued', 'Issued'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True)

    availability_state = fields.Selection([
        ('not_checked', 'Not Checked'),
        ('available', 'Available'),
        ('partial', 'Partially Available'),
        ('unavailable', 'Unavailable'),
    ], default='not_checked', compute='_compute_availability_state', store=False)

    availability_note = fields.Char(compute='_compute_availability_state', store=False)

    @api.depends(
        'line_ids.qty',
        'line_ids.product_id',
        'internal_transfer_ref.state',
        'internal_transfer_ref.move_ids.state',
        'internal_transfer_ref.move_ids.move_line_ids.quantity',
        'internal_transfer_ref.move_ids.move_line_ids.product_uom_id',
    )
    def _compute_availability_state(self):
        for rm in self:
            if not rm.line_ids:
                rm.availability_state = 'not_checked'
                rm.availability_note = 'No RM lines.'
                continue
            if rm.internal_transfer_ref:
                moves = rm.internal_transfer_ref.move_ids.filtered(lambda m: m.state not in ('cancel',))
                if not moves:
                    rm.availability_state = 'not_checked'
                    rm.availability_note = 'Internal transfer has no active moves.'
                    continue
                total_required = sum(m.product_uom_qty for m in moves)
                total_reserved = sum(
                    ml.product_uom_id._compute_quantity(
                        ml.quantity,
                        ml.move_id.product_uom,
                        round=False,
                    )
                    for m in moves
                    for ml in m.move_line_ids
                )
                if total_reserved >= total_required:
                    rm.availability_state = 'available'
                    rm.availability_note = 'All requested raw materials are reserved.'
                elif total_reserved > 0:
                    rm.availability_state = 'partial'
                    rm.availability_note = 'Some raw materials are reserved; remaining quantity is short.'
                else:
                    rm.availability_state = 'unavailable'
                    rm.availability_note = 'No requested raw material is currently reserved.'
            else:
                rm.availability_state = 'not_checked'
                rm.availability_note = 'Create the internal transfer to check/reserve RM availability.'

    def _get_existing_internal_transfers(self):
        self.ensure_one()
        return self.env['stock.picking'].search([
            ('picking_type_id.code', '=', 'internal'),
            ('company_id', '=', self.company_id.id),
            ('origin', '=', self.name),
            ('state', '!=', 'cancel'),
        ], order='id asc')

    def _check_store_user(self):
        user = self.env.user
        if (
            user.has_group('base.group_system')
            or user.has_group('stock.group_stock_manager')
        ):
            return True

        employee = user.employee_id
        department = (
            employee.department_id.name.strip().lower()
            if employee and employee.department_id
            else ''
        )
        if department != 'store':
            raise UserError(_('Only Store users can process RM Issues.'))
        return True

    def action_check_availability(self):
        self.ensure_one()
        self._check_store_user()

        if self.state != 'requested':
            raise UserError(
                _('RM availability can be checked only for a Requested RM Issue.')
            )

        if not self.internal_transfer_ref:
            existing = self._get_existing_internal_transfers()

            if len(existing) == 1:
                self.with_context(skip_internal_transfer_link_check=True).write({'internal_transfer_ref': existing.id})
                existing.action_assign()
            elif len(existing) > 1:
                if not (
                    self.env.user.has_group('base.group_system')
                    or self.env.user.has_group('stock.group_stock_manager')
                ):
                    raise UserError(_(
                        'Multiple existing Internal Transfers were found for %s. '
                        'Only a Store Admin can select the correct transfer.'
                    ) % self.name)
                raise UserError(_(
                    'Multiple existing Internal Transfers were found. '
                    'Select the correct Internal Transfer in the field and '
                    'click Check RM Availability again.'
                ))
            else:
                return self.action_create_internal_transfer()
        else:
            self.internal_transfer_ref.action_assign()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Internal Transfer'),
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': self.internal_transfer_ref.id,
            'target': 'current',
        }

    def _check_internal_transfer_link(self, transfer_id):
        if not transfer_id:
            return
        transfer = self.env['stock.picking'].browse(transfer_id).exists()
        if not transfer:
            raise UserError(_('The selected Internal Transfer does not exist.'))
        if transfer.picking_type_id.code != 'internal':
            raise UserError(_('The linked document must be an Internal Transfer.'))
        if transfer.company_id != self.company_id:
            raise UserError(_('The Internal Transfer must belong to the same company as the RM Issue.'))
        if transfer.state in ('cancel', 'done'):
            raise UserError(_('A cancelled or completed Internal Transfer cannot be linked.'))

    def write(self, vals):
        if 'internal_transfer_ref' in vals and not self.env.context.get('skip_internal_transfer_link_check'):
            new_transfer_id = vals.get('internal_transfer_ref') or False
            if new_transfer_id:
                self._check_internal_transfer_link(new_transfer_id)

            changing_transfer = any(
                rm.internal_transfer_ref.id != new_transfer_id
                for rm in self
            )
            if changing_transfer and not (
                self.env.user.has_group('base.group_system')
                or self.env.user.has_group('stock.group_stock_manager')
            ):
                raise UserError(
                    _('Only a Store Admin can manually link or change the Internal Transfer.')
                )
        return super().write(vals)

    line_ids = fields.One2many('rm.issue.line', 'rm_issue_id')


    requested_by = fields.Many2one('res.users')
    issued_by = fields.Many2one('res.users')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('rm.issue') or 'New'
        return super().create(vals_list)

    def action_mark_requested(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only Draft RM Issues can be submitted.'))
        self.state = 'requested'
        self.requested_by = self.env.user

    def action_issue_material(self):
        self._check_store_user()
        for rm in self:
            if rm.state != 'requested':
                raise UserError("RM issue request is not in Requested state.")

            if not rm.internal_transfer_ref:
                raise UserError(
                    "Please create the Internal Transfer before marking the RM Issue as Issued."
                )

            if rm.internal_transfer_ref.state != 'done':
                raise UserError(
                    "The Internal Transfer must be completed before marking Raw Materials as Issued."
                )

            rm.write({
                'state': 'issued',
                'issued_by': self.env.user.id,
            })
            if rm.mo_id:
                rm.mo_id.rm_issue_status = 'issued'

            body = f"""
                <p>Hello Production Team,</p>
                <p>Raw materials have been issued for the following Manufacturing Order:</p>
                <p>
                    <b>MO:</b> {rm.mo_id.name}<br/>
                    <b>Product:</b> {rm.mo_id.product_id.display_name}<br/>
                    <b>Quantity:</b> {rm.mo_id.product_qty}
                </p>
                <p>You may now start production.</p>
            """
            self.env['mail.mail'].sudo().create({
                'subject': f'Raw Material Issued for {rm.mo_id.name}',
                'body_html': body,
                'email_to': 'production@rsdpolymers.com',
                'email_from': 'store@rsdpolymers.com',
            }).send()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': 'Raw Materials issued successfully. Production team notified.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_print_rm_slip(self):
        self.ensure_one()

        # Ensure there is an MO linked before trying to print
        if not self.mo_id:
            raise UserError("There is no Manufacturing Order linked to this RM Issue to print.")

        # Call the existing report, passing the linked mo_id as the target record
        # Note: Replace 'your_module_name' with the actual technical name of the
        # module where the report XML is located (likely 'rm_issue_slip' based on your code).
        return self.env.ref('rsd_production.action_rm_issue_slip').report_action(self.mo_id)

    def action_cancel(self):
        for rm in self:
            if rm.state == 'issued':
                raise UserError(_('An Issued RM Issue cannot be cancelled.'))
            if rm.internal_transfer_ref and rm.internal_transfer_ref.state not in ('cancel', 'done'):
                raise UserError(_(
                    'Cancel the linked Internal Transfer before cancelling RM Issue %s.'
                ) % rm.name)
            rm.state = 'cancelled'
        return True

    def unlink(self):
        for rm in self:
            if rm.internal_transfer_ref or rm.state in ('requested', 'issued'):
                raise UserError(_(
                    'RM Issue %s cannot be deleted after stock processing has started. '
                    'Use Cancel instead.'
                ) % rm.name)
        return super().unlink()

    def action_create_internal_transfer(self):
        self.ensure_one()
        self._check_store_user()

        if self.internal_transfer_ref:
            raise UserError(
                f"Internal Transfer already exists: {self.internal_transfer_ref.name}"
            )

        # Find Internal Transfer Operation Type
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('company_id', '=', self.company_id.id)
        ], limit=1)

        if not picking_type:
            raise UserError("No Internal Transfer operation type found.")

        # Create Transfer
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'origin': self.name,
            'company_id': self.company_id.id,
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': picking_type.default_location_dest_id.id,
        })

        # Create Move Lines
        for line in self.line_ids:
            self.env['stock.move'].create({
                'name': line.product_id.display_name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty,
                'product_uom': line.uom_id.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
                'picking_id': picking.id,
            })

        picking.action_confirm()
        picking.action_assign()
        self.with_context(skip_internal_transfer_link_check=True).write({'internal_transfer_ref': picking.id})

        return {
            'type': 'ir.actions.act_window',
            'name': 'Internal Transfer',
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': picking.id,
            'target': 'current',
        }
