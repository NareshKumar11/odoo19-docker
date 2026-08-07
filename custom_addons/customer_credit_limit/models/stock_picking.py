from odoo import _, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _credit_gate(self):
        """Only outgoing deliveries, only when the setting is on."""
        self.ensure_one()
        company = self.company_id or self.env.company
        if company.credit_control_mode in ('off', 'warn'):
            return
        if not company.credit_block_delivery:
            return
        if self.picking_type_id.code != 'outgoing' or not self.partner_id:
            return
        order = self.sale_id if 'sale_id' in self._fields else self.env['sale.order']
        if order and order._credit_valid_release():
            return
        position = self.partner_id._credit_position(company=company)
        if position['band'] == 'red':
            raise UserError(_(
                "%(message)s\n\nThis delivery cannot be validated until the credit "
                "position is cleared.", message=position['message']))

    def button_validate(self):
        for picking in self:
            picking._credit_gate()
        return super().button_validate()
