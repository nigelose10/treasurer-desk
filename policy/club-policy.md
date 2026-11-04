# Club reimbursement policy

This is the rule sheet the treasurer can read. The auditor enforces the copy
stored in the Switch room document `club-policy`. Packaged defaults:

- A single claim over **$75.00** is flagged. The treasurer may adjust it or approve it with `override="reason"`.
- A claim over **$200.00** is blocked until someone records a pre-approval. Approving it also requires an override.
- **Alcohol** is not reimbursed.
- The receipt date must be within **14 days**.
- Each event has a remaining budget. `thursday-meetup` starts at **$200.00**. Anything else starts at **$150.00**.
- A second open or approved claim with the same payer, amount, date, and event is a duplicate.

The desk never sends money. An approval writes a ledger row and an e-transfer line for the treasurer to pay by hand.

To replace the live policy from the room, the treasurer posts:

```
@auditor apply-policy
```yaml
max_claim_amount: "80.00"
preapproval_threshold: "200.00"
receipt_max_age_days: 14
banned_categories: [alcohol]
default_event_budget: "150.00"
event_budgets:
  thursday-meetup: "200.00"
```
```
