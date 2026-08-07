from odoo import _, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _credit_gate(self):
        """Only customer invoices, only when the setting is on."""
        self.ensure_one()
        company = self.company_id or self.env.company
        if company.credit_control_mode in ('off', 'warn'):
            return
        if not company.credit_block_invoice:
            return
        if self.move_type != 'out_invoice' or not self.partner_id:
            return
        position = self.partner_id._credit_position(company=company)
        if position['band'] == 'red':
            raise UserError(_(
                "%(message)s\n\nThis invoice cannot be posted until the credit "
                "position is cleared.", message=position['message']))

    def _post(self, soft=True):
        for move in self:
            move._credit_gate()
        return super()._post(soft=soft)
