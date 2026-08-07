import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class CustomerCreditApproval(models.Model):
    _name = 'customer.credit.approval'
    _description = 'Customer Credit Approval'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(default=lambda self: _('New'), copy=False, readonly=True)
    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True, readonly=True,
        index=True, ondelete='cascade')
    sale_order_id = fields.Many2one(
        'sale.order', string='Sales Order', readonly=True, ondelete='set null')
    company_id = fields.Many2one(
        'res.company', required=True, readonly=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True)

    # Snapshot taken when the request is raised. Exposure moves; the approver
    # must see the figures the salesperson saw.
    order_amount = fields.Monetary(string='Order Amount', readonly=True)
    credit_limit = fields.Monetary(string='Credit Limit', readonly=True)
    outstanding = fields.Monetary(string='Outstanding', readonly=True)
    exceeded_amount = fields.Monetary(string='Exceeded By', readonly=True)
    used_percent = fields.Float(string='Credit Used (%)', readonly=True)
    block_reason = fields.Selection(
        selection=[
            ('hold', 'Customer on credit hold'),
            ('overdue', 'Invoices overdue'),
            ('over_limit', 'Over the credit limit'),
        ],
        string='Reason for Block', readonly=True)

    reason = fields.Text(string='Reason for the Request', required=True)
    expected_payment_date = fields.Date(string='Expected Payment Date')
    request_user_id = fields.Many2one(
        'res.users', string='Requested By', readonly=True,
        default=lambda self: self.env.user)
    request_date = fields.Datetime(
        string='Requested On', readonly=True, default=fields.Datetime.now)

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('to_approve', 'To Approve'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('expired', 'Expired'),
            ('cancelled', 'Cancelled'),
        ],
        default='draft', tracking=True, copy=False)
    decision = fields.Selection(
        selection=[
            ('order_only', 'This order only'),
            ('temporary', 'Temporary credit limit'),
        ],
        string='Decision', readonly=True, copy=False)
    temporary_amount = fields.Monetary(string='Temporary Increase')
    temporary_expiry = fields.Date(string='Valid Until')
    approver_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Decided On', readonly=True)
    decision_note = fields.Text(string='Approver Note')

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'customer.credit.approval') or _('New')
            self._credit_fill_snapshot(vals)
        records = super().create(vals_list)
        for record in records:
            order = record.sale_order_id
            if order and not order.credit_approval_id:
                order.sudo().credit_approval_id = record.id
        return records

    @api.model
    def _credit_fill_snapshot(self, vals):
        """Take the figures from the server, not from the form."""
        if vals.get('order_amount') or not vals.get('partner_id'):
            return
        partner = self.env['res.partner'].browse(vals['partner_id'])
        company = self.env['res.company'].browse(
            vals.get('company_id') or self.env.company.id)
        order = self.env['sale.order'].browse(vals['sale_order_id']) \
            if vals.get('sale_order_id') else self.env['sale.order']
        amount = order._credit_amount_company_currency() if order else 0.0
        position = partner._credit_position(company=company, additional_amount=amount)
        vals.update({
            'order_amount': position['document_amount'],
            'credit_limit': position['effective_limit'],
            'outstanding': position['outstanding'],
            'exceeded_amount': position['exceeded'],
            'used_percent': position['used_percent'],
            'block_reason': position['reason'] if position['reason'] in (
                'hold', 'overdue', 'over_limit') else False,
        })

    @api.constrains('temporary_amount', 'temporary_expiry')
    def _check_temporary(self):
        for record in self:
            if record.decision != 'temporary':
                continue
            if record.temporary_amount <= 0:
                raise ValidationError(_("Enter the temporary increase amount."))
            if not record.temporary_expiry:
                raise ValidationError(_("Enter the date the temporary limit expires."))
            if record.temporary_expiry < fields.Date.context_today(record):
                raise ValidationError(_("The expiry date cannot be in the past."))

    # ------------------------------------------------------------------
    def action_submit(self):
        for record in self:
            if record.state != 'draft':
                continue
            record.state = 'to_approve'
            record._notify_approvers()
        return {'type': 'ir.actions.act_window_close'}

    def _credit_approver_users(self):
        """Everyone who can decide a request.

        Odoo 19 removed the reverse field ``res.groups.users``, and the group can
        also be held indirectly through Accounting Manager, so this goes from the
        users side. Internal users only, and only a handful in practice.
        """
        internal = self.env['res.users'].sudo().search([
            ('share', '=', False), ('active', '=', True)])
        return internal.filtered(
            lambda user: user.has_group('customer_credit_limit.group_credit_approver'))

    def _credit_notify(self, template_xmlid, users, toast_type, toast_title,
                       toast_message, log_body):
        """Email, chatter entry and a live toast, for one set of users."""
        self.ensure_one()
        users = users.filtered(lambda user: user.active)
        if not users:
            return
        partners = users.partner_id

        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if template and partners:
            try:
                template.send_mail(
                    self.id, force_send=False,
                    email_values={'partner_ids': partners.ids})
            except Exception:
                # A mail server problem must never block a credit decision.
                _logger.warning("Credit notification email failed for %s",
                                self.name, exc_info=True)

        self.message_post(body=log_body, subtype_xmlid='mail.mt_note')

        # Toast for whoever happens to be logged in right now.
        for partner in partners:
            try:
                self.env['bus.bus']._sendone(partner, 'simple_notification', {
                    'type': toast_type,
                    'title': toast_title,
                    'message': toast_message,
                    'sticky': False,
                })
            except Exception:
                _logger.debug("Credit toast not delivered to %s", partner.display_name,
                              exc_info=True)

    def _notify_approvers(self):
        self.ensure_one()
        approvers = self._credit_approver_users()
        if not approvers:
            return
        # Do not ask someone to approve their own request unless they are the
        # only approver there is.
        if len(approvers) > 1:
            approvers -= self.env.user
        for user in approvers:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=user.id,
                summary=_('Credit approval requested for %s', self.partner_id.display_name),
                note=self.reason or '')

        self._credit_notify(
            'customer_credit_limit.mail_template_credit_request',
            approvers,
            'warning',
            _('Credit approval needed'),
            _('%(user)s requested a credit release for %(partner)s.',
              user=self.request_user_id.display_name,
              partner=self.partner_id.display_name),
            _('Sent for approval to %s.',
              ', '.join(approvers.mapped('name')) or _('nobody')))

    def _check_approver(self):
        self.ensure_one()
        if not self.env.user.has_group('customer_credit_limit.group_credit_approver'):
            raise UserError(_("Only a Credit Approver can decide this request."))
        if self.env.user == self.request_user_id and not self.env.su:
            raise UserError(_("You cannot approve your own request."))

    def action_approve_order(self):
        """Release this one order. The limit itself is untouched."""
        for record in self:
            record._check_approver()
            record._set_decision('order_only')
            record._try_confirm_order()
        return True

    def action_approve_temporary(self):
        """Grant a temporary limit that expires by itself."""
        for record in self:
            record._check_approver()
            if not record.temporary_amount or not record.temporary_expiry:
                raise UserError(_(
                    "Enter the temporary increase and its expiry date first."))
            record._set_decision('temporary')
            record._try_confirm_order()
        return True

    def action_reject(self):
        for record in self:
            record._check_approver()
            record.write({
                'state': 'rejected',
                'approver_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })
            record.activity_unlink(['mail.mail_activity_data_todo'])
            if record.sale_order_id:
                record.sale_order_id.message_post(body=_(
                    "Credit approval rejected by %s.", self.env.user.display_name))
            record._notify_requester_decision()
        return True

    def action_cancel(self):
        for record in self:
            if record.state in ('approved', 'rejected'):
                raise UserError(_("A decided request cannot be cancelled."))
            record.state = 'cancelled'
            record.activity_unlink(['mail.mail_activity_data_todo'])
        return True

    def _set_decision(self, decision):
        self.ensure_one()
        self.write({
            'decision': decision,
            'state': 'approved',
            'approver_id': self.env.user.id,
            'approval_date': fields.Datetime.now(),
        })
        self.activity_unlink(['mail.mail_activity_data_todo'])
        self._notify_requester_decision()

    def _notify_requester_decision(self):
        """Close the loop with whoever raised the request."""
        self.ensure_one()
        if not self.request_user_id:
            return
        approved = self.state == 'approved'
        if approved and self.decision == 'temporary':
            detail = _('Temporary limit of %(amount)s until %(date)s.',
                       amount=self.temporary_amount, date=self.temporary_expiry)
        elif approved:
            detail = _('Released for this order only.')
        else:
            detail = self.decision_note or _('No reason given.')
        self._credit_notify(
            'customer_credit_limit.mail_template_credit_approved' if approved
            else 'customer_credit_limit.mail_template_credit_rejected',
            self.request_user_id,
            'success' if approved else 'danger',
            _('Credit request approved') if approved else _('Credit request rejected'),
            _('%(partner)s: %(detail)s', partner=self.partner_id.display_name,
              detail=detail),
            _('%(state)s notification sent to %(user)s.',
              state=_('Approval') if approved else _('Rejection'),
              user=self.request_user_id.display_name))

    def _try_confirm_order(self):
        """Confirm the order the request came from, if it is still a quotation."""
        self.ensure_one()
        order = self.sale_order_id
        if not order or order.state not in ('draft', 'sent'):
            return
        order.message_post(body=_(
            "Credit approval granted by %(user)s (%(decision)s).",
            user=self.env.user.display_name,
            decision=dict(self._fields['decision'].selection).get(self.decision, '')))
        order.with_context(credit_approval_release=True).action_confirm()

    # ------------------------------------------------------------------
    def _is_release_valid_for(self, order):
        """A one-time release covers one order, at the amount it was asked for."""
        self.ensure_one()
        if self.state != 'approved' or self.sale_order_id != order:
            return False
        if self.decision == 'temporary':
            return True
        amount = order._credit_amount_company_currency()
        return amount <= (self.order_amount or 0.0) + 0.01

    # ------------------------------------------------------------------
    @api.model
    def _cron_expire_temporary(self):
        """Expire temporary limits, and warn three days ahead."""
        today = fields.Date.context_today(self)
        expired = self.search([
            ('state', '=', 'approved'),
            ('decision', '=', 'temporary'),
            ('temporary_expiry', '<', today),
        ])
        for record in expired:
            record.state = 'expired'
            record.message_post(body=_("The temporary credit limit expired today."))

        due_soon = self.search([
            ('state', '=', 'approved'),
            ('decision', '=', 'temporary'),
            ('temporary_expiry', '>=', today),
            ('temporary_expiry', '<=', fields.Date.add(today, days=3)),
        ])
        for record in due_soon:
            if record.activity_ids:
                continue
            record.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=record.approver_id.id or self.env.uid,
                date_deadline=record.temporary_expiry,
                summary=_('Temporary credit limit for %s expires on %s',
                          record.partner_id.display_name, record.temporary_expiry))
        return True
