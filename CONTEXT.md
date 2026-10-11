# OddsExecutionEngine

Answers whether a target price is fillable across sportsbooks right now, where to fill it best, and alerts the operator when a watched price becomes fillable.

## Language

### People

**Operator**:
The person who owns and runs the system: sets watches, controls Auto-Refresh, and receives every notification, including system warnings. There is no multi-user model yet.
_Avoid_: User, account, customer, admin

### Monitoring

**Auto-Refresh**:
The operator's on/off switch that lets the system refresh quotes on its own: each sport with an active watch it can act on is kept within about one interval of fresh. Off means refresh is manual only. Manual refresh works either way.
_Avoid_: Session, polling, scheduler

**Notification**:
A push message sent to the operator. Comes in two kinds: an opportunity notification and a quota warning.
_Avoid_: Alert, ping, message

**Opportunity notification**:
The notification for one `OpportunityIdentified`: selection, best price and book, target line, fillable. One opportunity yields exactly one, however many books match.

**Quota warning**:
The notification sent when remaining provider credits fall below a floor. Informs only; it does not switch Auto-Refresh off.

### Events

**Workflow event**:
An internal record of something that happened in a workflow, kept for audit. Never seen outside the system.
_Avoid_: Domain event (when you mean the stored record)

**Public event**:
A versioned event the system publishes to anything outside it (the notifier today, webhooks or an SDK later). Only explicitly chosen workflow events have a public counterpart.
_Avoid_: External event, outbound message, notification (a notification is one channel's rendering of a public event)

### Delivery

**Channel**:
A kind of transport that public events leave by: Web Push today, a webhook later.
_Avoid_: Provider, transport (when naming the kind)

**Destination**:
One address on a channel: one browser's push subscription, one webhook URL. The operator may have several. A destination is active or disabled, either removed by the operator or gone because the channel rejected it. A gone destination comes back only through a fresh subscription.
_Avoid_: Subscriber, endpoint, device (a device can hold more than one destination)

**Delivery**:
One public event going to one destination, with its attempts and final outcome: delivered, gone, failed or expired.
_Avoid_: Send, dispatch (dispatch is the fan-out that creates deliveries)
