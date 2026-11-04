# Transcript captured from Mattermost

Fictional demo data. Rules mode. No money moved.

**maya:** @intake claim 42.30 pizza 2026-11-03 event:thursday-meetup receipt:inline
**agent:** @auditor Claim C-001
- payer: maya
- amount: 42.30 USD
- date: 2026-11-03
- category: food
- event: thursday-meetup
- receipt: inline
Please audit C-001. Wording: rules.

**agent:** @bookkeeper C-001 PASS
C-001 is PASS for maya: USD 42.30 on thursday-meetup (food). It is inside the cap, the category is allowed, and the receipt date is in range. The treasurer can `@bookkeeper approve C-001`. Cap 75.00, pre-approval 200.00.

**agent:** Noted C-001. Waiting for the treasurer to approve, reject, or adjust it.

**user:** @bookkeeper approve C-001
**agent:** Approved C-001 for 42.30 USD (food, thursday-meetup). Rules verdict on the booked amount: PASS. E-transfer, for the treasurer to send by hand: pay maya 42.30 USD for C-001. Decided by user at 2026-11-04T15:53:04+00:00. This desk did not move money.

**maya:** @intake claim 90.00 pizza 2026-11-03 event:thursday-meetup receipt:over-cap
**agent:** @bookkeeper C-002 FLAG: amount 90.00 exceeds the 75.00 per-claim cap
C-002 is FLAG for maya: USD 90.00 on thursday-meetup (food). amount 90.00 exceeds the 75.00 per-claim cap. The treasurer can `@bookkeeper adjust C-002 amount=…` or approve it with override="reason". Cap 75.00, pre-approval 200.00.

**agent:** Noted C-002. Waiting for the treasurer to approve, reject, or adjust it.

**user:** @bookkeeper approve C-002
**agent:** C-002 FLAG: amount 90.00 exceeds the 75.00 per-claim cap
Refused: FLAG needs `override="reason"` before it can be approved. amount 90.00 exceeds the 75.00 per-claim cap

**user:** @bookkeeper adjust C-002 amount=38.00
**agent:** Approved C-002 for 38.00 USD (food, thursday-meetup). Rules verdict on the booked amount: PASS. E-transfer, for the treasurer to send by hand: pay maya 38.00 USD for C-002. Decided by user at 2026-11-04T15:53:07+00:00. This desk did not move money.

**maya:** @intake beer $15.00 on 2026-11-03 event:social receipt:bar-tab
**agent:** @bookkeeper C-003 BLOCK: category alcohol is not reimbursed
C-003 is BLOCK for maya: USD 15.00 on social (alcohol). category alcohol is not reimbursed. The treasurer can `@bookkeeper reject C-003`, or approve only with override="reason". Cap 75.00, pre-approval 200.00.

**maya:** @intake claim 42.30 pizza 2026-11-03 event:thursday-meetup receipt:second-copy
**agent:** @bookkeeper C-004 BLOCK: duplicate of an open or approved claim with the same payer, amount, date, and event
C-004 is BLOCK for maya: USD 42.30 on thursday-meetup (food). duplicate of an open or approved claim with the same payer, amount, date, and event. The treasurer can `@bookkeeper reject C-004`, or approve only with override="reason". Cap 75.00, pre-approval 200.00.

**maya:** @intake I think I paid something for snacks
**agent:** I could not read that, please use `claim <amount> <what> <date>`

**maya:** @intake claim 10.00 coffee 2026-11-04 event:office-hours receipt:cup
**agent:** @bookkeeper C-005 PASS
C-005 is PASS for maya: USD 10.00 on office-hours (food). It is inside the cap, the category is allowed, and the receipt date is in range. The treasurer can `@bookkeeper approve C-005`. Cap 75.00, pre-approval 200.00.

**sam:** @bookkeeper approve C-005
**agent:** Refused: only the treasurer can approve C-005. Sender 'sam' is not a treasurer.

**user:** @bookkeeper approve C-005
**agent:** Approved C-005 for 10.00 USD (food, office-hours). Rules verdict on the booked amount: PASS. E-transfer, for the treasurer to send by hand: pay maya 10.00 USD for C-005. Decided by user at 2026-11-04T15:53:13+00:00. This desk did not move money.

**user:** @bookkeeper summary
**agent:** Month summary (ledger document, not a payment):
- approved: 3 claim(s), total 90.30
- rejected: 0
- waiting on the treasurer: C-003 BLOCK, C-004 BLOCK
Budgets:
- office-hours: 10.00 of 150.00
- thursday-meetup: 80.30 of 200.00
No money has moved.

**maya:** @auditor why C-001
**agent:** C-001 recorded PASS on 42.30: no reasons. Ledger: approved 42.30 by user. Re-checked against the room as it is now, the rules would say BLOCK. The ledger row was not changed.

**user:** @bookkeeper ledger
**agent:** Ledger (authoritative copy is the room document):
- C-001 approved 42.30 thursday-meetup by user at 2026-11-04T15:53:04+00:00
- C-002 approved 38.00 thursday-meetup by user at 2026-11-04T15:53:07+00:00 adjusted from 90.00 to 38.00
- C-005 approved 10.00 office-hours by user at 2026-11-04T15:53:13+00:00
No money has moved.

Restarted the desk container. The ledger document was still there.
