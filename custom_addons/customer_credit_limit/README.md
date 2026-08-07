# Customer Credit Limit — Odoo 19

Blocks sales orders when a customer is over their credit limit, on credit hold, or
overdue. A credit approver can release the order or grant a temporary limit that
expires by itself. Works with no configuration.

## Install

```bash
cp -r customer_credit_limit /path/to/addons/
./odoo-bin -u customer_credit_limit -d yourdb
```

Depends on `sale_management`, `account`, `stock`.

## Settings — Sales → Configuration → Settings → Customer Credit

| Setting | Default |
|---|---|
| Credit control: off / warn only / block / block with approval | block with approval |
| Warning at | 80% |
| Block at | 100% |
| Block when overdue by | 30 days |
| Also block delivery | off |
| Also block invoice | off |

The credit limit itself stays on the customer, where Odoo already keeps it
(`res.partner.credit_limit`, per company). A customer with a limit of zero is
never blocked by the limit or overdue checks — only by a manual credit hold.

## The four checks

Run in this order on confirmation, first match decides:

1. `credit_hold` on the customer → blocked
2. Oldest overdue invoice older than the configured days → blocked
3. Projected usage ≥ block % → blocked
4. Projected usage ≥ warning % → banner only

Everything comes from one method, `res.partner._credit_position()`, so the
customer form, the order panel and the gates can never disagree.

```
outstanding = unpaid receivables (credit notes and payments already netted)
            + confirmed orders not yet invoiced
limit       = credit_limit + active temporary increase
available   = limit − outstanding − this order
```

All amounts are converted to the company currency before comparing.

## Permissions

One group, **Credit Approver**, implied by Accounting Manager. Only that group can
change `credit_limit`, `credit_hold`, `credit_check_exempt` or the threshold
overrides — enforced in `res.partner.write()`, not only in the view. Decisions are
blocked for the requester of the request. `customer.credit.log` refuses `write`
and `unlink` for everyone, including administrators.

## Manual test list

1. Customer with no limit → no banner, order confirms.
2. Set a limit, add an order to 85% → yellow banner, still confirms.
3. Order over 100% → confirmation refused, **Request Credit Approval** appears.
4. Request → approver approves this order → order confirms automatically.
5. Same customer, second order over the limit → blocked again (release is not reused).
6. Approve with a temporary limit → limit rises, order confirms, expiry set.
7. Set the expiry to yesterday and run the cron → state becomes Expired, band turns red again.
8. Register payment on an old invoice → outstanding drops, band recovers.
9. Put a customer on credit hold with credit available → still blocked.
10. Invoice overdue past the configured days, credit available → still blocked.
11. Log in as a salesperson → panel visible, credit limit not editable.
12. Try to edit a row in Credit Limit History → refused.

## Verify on your instance

I could not run an Odoo server while writing this, so confirm these anchors on
first install — they are the only version-sensitive parts:

- `//app[@name='sale_management']` in `sale.res_config_settings_view_form`
  (Odoo 19 settings use `<app>` / `<block>` / `<setting>`, not `<div data-key>`)
- `//sheet/group[1]` and `//button[@name='action_confirm'][1]` in `sale.view_order_form`
- `sale.view_order_tree`, `base.view_partner_tree` (field `email`), `base.view_partner_form`
- `account.menu_finance_receivables`
- `sale.order.amount_to_invoice` — the code falls back to `amount_total − amount_invoiced`
  and then to `amount_total` if it is missing
- `<chatter/>` element in the approval form
- `account.group_account_manager` still exists (used only to imply the new group —
  if it fails, delete that one record and assign Credit Approver by hand)

### Odoo 19 security note

Odoo 19 replaced `res.groups.category_id` with `privilege_id`, pointing at the new
`res.groups.privilege` model. `security/credit_security.xml` defines its own
privilege, *Customer Credit*, under the Accounting category. The `comment` field
was dropped from the group for the same reason — it is cosmetic.

## Known limits of version 1

- Computed credit fields are not stored, so they are hidden by default in list
  views. Showing them on a list of several thousand customers will be slow;
  a stored daily snapshot is the version 2 answer.
- One approval level, no escalation, no delegation.
- No credit profiles, configurable exposure components, risk scoring or dashboards.
- Website checkout does not raise an error; it posts a message on the order instead.
- Reducing a limit below current exposure does not re-check confirmed orders.

## Files

```
models/res_company.py          six settings
models/res_config_settings.py  settings panel
models/res_partner.py          the engine: position, bands, thresholds, audit
models/sale_order.py           panel fields, banner, confirmation gate
models/stock_picking.py        optional delivery gate
models/account_move.py         optional invoice gate
models/credit_approval.py      request, three decisions, expiry cron
models/credit_log.py           append-only limit history
```
