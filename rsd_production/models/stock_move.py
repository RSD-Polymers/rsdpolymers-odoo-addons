from odoo import api, models, _
from odoo.exceptions import UserError


def _assert_output_form_unlocked(env, mo_ids, label):
    mo_ids = list(set(filter(None, mo_ids)))
    if not mo_ids:
        return
    forms = env['production.output.form'].sudo().search([
        ('production_id', 'in', mo_ids),
        ('state', 'in', ['submitted', 'approved', 'produced']),
    ])
    if not forms:
        return
    allow_completion = any(form.production_id.output_form_completion_in_progress for form in forms)
    is_supervisor = (
        env.user.has_group('rsd_quality.group_unloading_request_supervisor')
        or env.user.has_group('base.group_system')
    )
    approved_forms = forms.filtered(lambda form: form.state == 'approved')
    if not (allow_completion and is_supervisor and approved_forms and len(approved_forms) == len(forms)):
        raise UserError(_('%s are locked by a submitted, approved or produced Output Form.') % label)


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _check_output_form_lock(self):
        raw_moves = self.filtered(lambda move: move.raw_material_production_id)
        _assert_output_form_unlocked(self.env, raw_moves.mapped('raw_material_production_id').ids, _('Raw material moves'))

    @api.model_create_multi
    def create(self, vals_list):
        mo_ids = [vals.get('raw_material_production_id') for vals in vals_list if vals.get('raw_material_production_id')]
        _assert_output_form_unlocked(self.env, mo_ids, _('Raw material moves'))
        return super().create(vals_list)

    def write(self, vals):
        self._check_output_form_lock()
        if vals.get('raw_material_production_id'):
            _assert_output_form_unlocked(self.env, [vals['raw_material_production_id']], _('Raw material moves'))
        return super().write(vals)

    def unlink(self):
        self._check_output_form_lock()
        return super().unlink()


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _check_output_form_lock(self):
        mo_ids = self.mapped('move_id.raw_material_production_id').ids
        _assert_output_form_unlocked(self.env, mo_ids, _('Raw material operation lines'))

    @api.model_create_multi
    def create(self, vals_list):
        move_ids = [vals.get('move_id') for vals in vals_list if vals.get('move_id')]
        moves = self.env['stock.move'].browse(move_ids)
        _assert_output_form_unlocked(self.env, moves.mapped('raw_material_production_id').ids, _('Raw material operation lines'))
        return super().create(vals_list)

    def write(self, vals):
        self._check_output_form_lock()
        if vals.get('move_id'):
            move = self.env['stock.move'].browse(vals['move_id'])
            _assert_output_form_unlocked(self.env, move.mapped('raw_material_production_id').ids, _('Raw material operation lines'))
        return super().write(vals)

    def unlink(self):
        self._check_output_form_lock()
        return super().unlink()


class QualityCheck(models.Model):
    _inherit = 'quality.check'

    def _check_output_qc_lock(self, production_ids=None):
        self._check_output_form_lock((production_ids or self.mapped('production_id').ids), _('Quality Checks'))

    def _check_output_form_lock(self, mo_ids, label):
        forms = self.env['production.output.form'].sudo().search([
            ('production_id', 'in', mo_ids), ('state', 'in', ['submitted', 'approved', 'produced'])
        ])
        if forms:
            raise UserError(_('%s are locked by the submitted, approved or produced Output Form.') % label)

    @api.model_create_multi
    def create(self, vals_list):
        self._check_output_qc_lock([v.get('production_id') for v in vals_list if v.get('production_id')])
        return super().create(vals_list)

    def write(self, vals):
        self._check_output_qc_lock()
        if vals.get('production_id'):
            self._check_output_qc_lock([vals['production_id']])
        return super().write(vals)

    def unlink(self):
        self._check_output_qc_lock()
        return super().unlink()


class RSDQualityStageTest(models.Model):
    _inherit = 'rsd.quality.stage.test'

    def _check_output_qc_lock(self, production_ids=None):
        mo_ids = production_ids if production_ids is not None else self.mapped('production_id').ids
        forms = self.env['production.output.form'].sudo().search([
            ('production_id', 'in', mo_ids), ('state', 'in', ['submitted', 'approved', 'produced'])
        ])
        if forms:
            raise UserError(_('Performance Test records are locked by the submitted, approved or produced Output Form.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_output_qc_lock([v.get('production_id') for v in vals_list if v.get('production_id')])
        return super().create(vals_list)

    def write(self, vals):
        self._check_output_qc_lock()
        if vals.get('production_id'):
            self._check_output_qc_lock([vals['production_id']])
        return super().write(vals)

    def unlink(self):
        self._check_output_qc_lock()
        return super().unlink()


class RSDQualityUnloadingRequest(models.Model):
    _inherit = 'rsd.quality.unloading.request'

    def _check_output_qc_lock(self, production_ids=None):
        mo_ids = production_ids if production_ids is not None else self.mapped('production_id').ids
        forms = self.env['production.output.form'].sudo().search([
            ('production_id', 'in', mo_ids), ('state', 'in', ['submitted', 'approved', 'produced'])
        ])
        if forms:
            raise UserError(_('Unloading records are locked by the submitted, approved or produced Output Form.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_output_qc_lock([v.get('production_id') for v in vals_list if v.get('production_id')])
        return super().create(vals_list)

    def write(self, vals):
        self._check_output_qc_lock()
        if vals.get('production_id'):
            self._check_output_qc_lock([vals['production_id']])
        return super().write(vals)

    def unlink(self):
        self._check_output_qc_lock()
        return super().unlink()
