from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CustomerCreditLog(models.Model):
    _name = 'customer.credit.log'
    _description = 'Customer Credit Limit History'
    _order = 'create_date desc, id desc'

    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True, index=True,
        ondelete='cascade')
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True)
    old_limit = fields.Monetary(string='Previous Limit')
    new_limit = fields.Monetary(string='New Limit')
    difference = fields.Monetary(string='Change', compute='_compute_difference', store=True)
    user_id = fields.Many2one(
        'res.users', string='Changed By', default=lambda self: self.env.user)
    reason = fields.Char(string='Reason')
    approval_id = fields.Many2one('customer.credit.approval', string='Approval')

    @api.depends('old_limit', 'new_limit')
    def _compute_difference(self):
        for record in self:
            record.difference = (record.new_limit or 0.0) - (record.old_limit or 0.0)

    def write(self, vals):
        raise UserError(_("The credit limit history cannot be changed."))

    def unlink(self):
        raise UserError(_("The credit limit history cannot be deleted."))
