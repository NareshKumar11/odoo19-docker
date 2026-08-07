from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    credit_control_mode = fields.Selection(
        related='company_id.credit_control_mode', readonly=False)
    credit_warn_percent = fields.Float(
        related='company_id.credit_warn_percent', readonly=False)
    credit_block_percent = fields.Float(
        related='company_id.credit_block_percent', readonly=False)
    credit_overdue_days = fields.Integer(
        related='company_id.credit_overdue_days', readonly=False)
    credit_block_delivery = fields.Boolean(
        related='company_id.credit_block_delivery', readonly=False)
    credit_block_invoice = fields.Boolean(
        related='company_id.credit_block_invoice', readonly=False)
