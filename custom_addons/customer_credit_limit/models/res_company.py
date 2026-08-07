from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    credit_control_mode = fields.Selection(
        selection=[
            ('off', 'Off'),
            ('warn', 'Warn only'),
            ('block', 'Block'),
            ('approval', 'Block, approval can release'),
        ],
        string='Credit Control',
        default='approval',
        required=True,
        help="Off: nothing happens.\n"
             "Warn only: a message is shown, the order still confirms.\n"
             "Block: confirmation is refused.\n"
             "Block, approval can release: confirmation is refused but a request "
             "can be sent to a credit approver.",
    )
    credit_warn_percent = fields.Float(
        string='Warning At (%)', default=80.0,
        help="Show a warning once this share of the credit limit is used.")
    credit_block_percent = fields.Float(
        string='Block At (%)', default=100.0,
        help="Block once this share of the credit limit is used. "
             "Set above 100 to allow a small tolerance.")
    credit_overdue_days = fields.Integer(
        string='Overdue Days That Block', default=30,
        help="Block the customer when an invoice is overdue by more than this "
             "many days, even if credit is still available. Zero disables the check.")
    credit_block_delivery = fields.Boolean(
        string='Also Block Delivery', default=False,
        help="Re-check the credit position when a delivery is validated.")
    credit_block_invoice = fields.Boolean(
        string='Also Block Invoice', default=False,
        help="Re-check the credit position when a customer invoice is posted.")
